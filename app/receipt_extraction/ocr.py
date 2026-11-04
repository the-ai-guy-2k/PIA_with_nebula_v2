"""Local text recognition. Replace this module to change OCR providers.

The recognizer uses Windows OCR on Windows and local Tesseract on Linux.
It does not call a paid service and it does not write the receipt image.
"""

from __future__ import annotations

import asyncio
import io
import subprocess
import sys

from PIL import Image

from app.config import MAX_IMAGE_PIXELS
from app.receipt_extraction.errors import UnreadableReceipt

_UNREADABLE = "The preserved receipt image could not be read."
_OCR_FAILED = "Text could not be read from this receipt."
_MAX_EDGE = 4000


async def recognize_lines(image_bytes: bytes) -> list[str]:
    """Return recognized lines in reading order. The original bytes are not modified."""
    return await asyncio.to_thread(_recognize_sync, image_bytes)


def _recognize_sync(image_bytes: bytes) -> list[str]:
    if sys.platform != "win32":
        payload = _prepare_ocr_bytes(image_bytes)
        try:
            result = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "6"],
                input=payload,
                capture_output=True,
                timeout=30,
                check=True,
            )
            return [
                line.strip() for line in result.stdout.decode("utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise UnreadableReceipt(_OCR_FAILED) from None
    return asyncio.run(_recognize(image_bytes))


async def _recognize(image_bytes: bytes) -> list[str]:
    payload = _prepare_ocr_bytes(image_bytes)
    try:
        import winrt.windows.foundation
        import winrt.windows.foundation.collections
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except ImportError:
        raise UnreadableReceipt(_OCR_FAILED) from None

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise UnreadableReceipt(_OCR_FAILED)

    try:
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(payload)
        await writer.store_async()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            text = " ".join(word.text for word in line.words).strip()
            if text:
                lines.append(text)
        return lines
    except UnreadableReceipt:
        raise
    except Exception:
        raise UnreadableReceipt(_OCR_FAILED) from None


def _prepare_ocr_bytes(image_bytes: bytes) -> bytes:
    """Decode for a readability check. Scale only the in-memory OCR copy."""
    if not image_bytes:
        raise UnreadableReceipt(_UNREADABLE)
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            width, height = image.size
            if width <= _MAX_EDGE and height <= _MAX_EDGE:
                return image_bytes
            scale = _MAX_EDGE / max(width, height)
            resized = image.convert("RGB").resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
    except (OSError, ValueError, Image.DecompressionBombError):
        raise UnreadableReceipt(_UNREADABLE) from None

    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()

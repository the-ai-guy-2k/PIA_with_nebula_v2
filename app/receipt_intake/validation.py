"""Validate receipt uploads without trusting the filename or declared type."""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError
from fastapi import UploadFile

from app.config import MAX_IMAGE_PIXELS, MULTIPART_OVERHEAD_BYTES, size_limit_message
from app.receipt_intake.errors import IntakeRejected

SUPPORTED_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
MIME_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_ILLEGAL_FILENAME_CHARS = set('<>:"|?*\\/\x00')
_UNSUPPORTED = "This file type is not supported. Upload a JPEG, PNG, or WEBP image."
_UNREADABLE = "The file could not be read as a JPEG, PNG, or WEBP image."


def declared_body_too_large(content_length: str | None, max_upload_bytes: int) -> bool:
    if content_length is None:
        return False
    try:
        declared = int(content_length)
    except ValueError:
        return False
    if declared < 0:
        return False
    return declared > max_upload_bytes + MULTIPART_OVERHEAD_BYTES


def sanitize_original_filename(name: str | None) -> str:
    """Keep the file's own name and drop any path or illegal characters."""
    if not name:
        return "receipt"
    base = name.replace("\\", "/").split("/")[-1]
    cleaned = []
    for character in base:
        if character in _ILLEGAL_FILENAME_CHARS or ord(character) < 32:
            continue
        cleaned.append(character)
    result = "".join(cleaned).strip().strip(".").strip()
    if not result or result in {".", ".."}:
        return "receipt"
    return result[:255]


async def read_limited_upload(upload: UploadFile, max_upload_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            block = await upload.read(64 * 1024)
            if not block:
                break
            if total + len(block) > max_upload_bytes:
                raise IntakeRejected(size_limit_message(max_upload_bytes))
            chunks.append(block)
            total += len(block)
    finally:
        await upload.close()
    if total == 0:
        raise IntakeRejected("The file is empty.")
    return b"".join(chunks)


def validate_receipt_bytes(content: bytes, max_upload_bytes: int) -> str:
    """Return the detected MIME type for an original image, or reject it."""
    if not content:
        raise IntakeRejected("The file is empty.")
    if len(content) > max_upload_bytes:
        raise IntakeRejected(size_limit_message(max_upload_bytes))

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            detected = (image.format or "").upper()
    except Image.DecompressionBombError:
        raise IntakeRejected(_UNREADABLE) from None
    except UnidentifiedImageError:
        raise IntakeRejected(_UNSUPPORTED) from None
    except (OSError, ValueError):
        raise IntakeRejected(_UNREADABLE) from None

    if detected == "MPO" and content.startswith(b"\xff\xd8\xff"):
        detected = "JPEG"

    mime_type = SUPPORTED_MIME_TYPES.get(detected)
    if mime_type is None or not _magic_matches(content, detected):
        raise IntakeRejected(_UNSUPPORTED)
    return mime_type


def _magic_matches(content: bytes, image_format: str) -> bool:
    if image_format == "JPEG":
        return content.startswith(b"\xff\xd8\xff")
    if image_format == "PNG":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if image_format == "WEBP":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False

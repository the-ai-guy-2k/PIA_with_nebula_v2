"""Run the ACI-001 cases against a live local server.

Usage:
  python tests/live_http_validate.py --base-url http://127.0.0.1:8765 --data-dir PATH
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def make_image(image_format: str, color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (32, 32), color)
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def post_file(base_url: str, filename: str, content: bytes, content_type: str) -> tuple[int, dict]:
    boundary = "----piaaci001boundary"
    disposition = f'Content-Disposition: form-data; name="file"; filename="{filename}"'
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f"{disposition}\r\n".encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            content,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/receipts",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload


def evidence_count(data_dir: Path) -> int:
    database = data_dir / "evidence.sqlite"
    if not database.exists():
        return 0
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT COUNT(*) FROM receipt_evidence").fetchone()[0]


def preserved_path(data_dir: Path, storage_reference: str) -> Path:
    name = storage_reference.split("/")[-1]
    return data_dir / "files" / name


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str, str]] = []

    def add(self, name: str, expected: str, actual: str, passed: bool) -> None:
        self.results.append((name, expected, actual, "PASS" if passed else "FAIL"))

    @property
    def ok(self) -> bool:
        return all(item[3] == "PASS" for item in self.results)

    def print(self) -> None:
        for name, expected, actual, status in self.results:
            print(f"TEST: {name}")
            print(f"EXPECTED: {expected}")
            print(f"ACTUAL: {actual}")
            print(f"RESULT: {status}")
            print("---")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    base_url = args.base_url
    data_dir = Path(args.data_dir)
    report = Report()
    source_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    source_before = source_path.read_bytes()

    jpeg = make_image("JPEG", (180, 40, 40))
    status, body = post_file(base_url, "receipt.jpg", jpeg, "image/jpeg")
    stored = preserved_path(data_dir, body.get("storage_reference", "missing"))
    jpeg_ok = (
        status == 201
        and body.get("status") == "accepted"
        and bool(body.get("evidence_id"))
        and body.get("original_filename") == "receipt.jpg"
        and body.get("mime_type") == "image/jpeg"
        and body.get("byte_size") == len(jpeg)
        and stored.is_file()
        and stored.read_bytes() == jpeg
    )
    report.add(
        "PASS CASE 1 — VALID JPEG",
        "upload succeeds, evidence is preserved, stable evidence ID exists, metadata is recorded",
        f"status={status} id={body.get('evidence_id')} file={body.get('original_filename')} mime={body.get('mime_type')} bytes={body.get('byte_size')} stored={stored.is_file()}",
        jpeg_ok,
    )

    png = make_image("PNG", (20, 70, 140))
    status, body = post_file(base_url, "receipt.png", png, "image/png")
    stored = preserved_path(data_dir, body.get("storage_reference", "missing"))
    png_ok = (
        status == 201
        and body.get("mime_type") == "image/png"
        and bool(body.get("evidence_id"))
        and stored.is_file()
        and stored.read_bytes() == png
    )
    report.add(
        "PASS CASE 2 — VALID PNG",
        "upload succeeds and PNG evidence is preserved with metadata",
        f"status={status} id={body.get('evidence_id')} mime={body.get('mime_type')} bytes={body.get('byte_size')} stored={stored.is_file()}",
        png_ok,
    )

    before = evidence_count(data_dir)
    status, body = post_file(base_url, "notes.txt", b"not an image", "text/plain")
    after = evidence_count(data_dir)
    report.add(
        "FAIL CASE 1 — UNSUPPORTED FILE",
        "upload rejected, no evidence record created, clear error",
        f"status={status} body={body} records_before={before} records_after={after}",
        status == 400 and body.get("status") == "rejected" and bool(body.get("reason")) and after == before,
    )

    before = evidence_count(data_dir)
    status, body = post_file(base_url, "empty.jpg", b"", "image/jpeg")
    after = evidence_count(data_dir)
    empty_files = [path for path in (data_dir / "files").glob("*") if path.stat().st_size == 0]
    report.add(
        "FAIL CASE 2 — EMPTY FILE",
        "upload rejected and no empty evidence stored",
        f"status={status} body={body} records_before={before} records_after={after} empty_files={len(empty_files)}",
        status == 400 and body.get("reason") == "The file is empty." and after == before and empty_files == [],
    )

    before = evidence_count(data_dir)
    oversized = b"\xff\xd8\xff" + (b"0" * (MAX_UPLOAD_BYTES - 2))
    status, body = post_file(base_url, "huge.jpg", oversized, "image/jpeg")
    after = evidence_count(data_dir)
    report.add(
        "FAIL CASE 3 — OVERSIZED FILE",
        "upload rejected safely and the limit is communicated",
        f"status={status} body={body} records_before={before} records_after={after}",
        status == 400 and "10 MB" in str(body.get("reason")) and after == before,
    )

    outside = data_dir.parent / "pia-escaped.jpg"
    if outside.exists():
        outside.unlink()
    status, body = post_file(base_url, r"..\..\pia-escaped.jpg", jpeg, "image/jpeg")
    stored = preserved_path(data_dir, body.get("storage_reference", "missing"))
    files_outside = outside.exists()
    inside = stored.is_file() and stored.resolve().is_relative_to((data_dir / "files").resolve())
    source_after = source_path.read_bytes()
    report.add(
        "SECURITY CASE — PATH MANIPULATION",
        "storage remains inside receipt evidence and no arbitrary path write occurs",
        f"status={status} stored={stored} inside={inside} outside_exists={files_outside} source_unchanged={source_after == source_before}",
        status == 201 and inside and not files_outside and source_after == source_before and stored.read_bytes() == jpeg,
    )

    status, body = post_file(base_url, "original.jpg", jpeg, "image/jpeg")
    stored = preserved_path(data_dir, body.get("storage_reference", "missing"))
    preserved = stored.read_bytes() if stored.is_file() else b""
    report.add(
        "EVIDENCE INTEGRITY CASE",
        "preserved original evidence matches the uploaded original",
        f"status={status} equal={preserved == jpeg} sha256={hashlib.sha256(preserved).hexdigest()}",
        status == 201 and preserved == jpeg and hashlib.sha256(preserved).digest() == hashlib.sha256(jpeg).digest(),
    )

    report.print()
    print("OVERALL:", "PASS" if report.ok else "FAIL")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

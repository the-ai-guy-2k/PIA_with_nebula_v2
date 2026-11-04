"""ACI-001 receipt intake and original evidence preservation."""

from __future__ import annotations

import hashlib
import io
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import MAX_UPLOAD_BYTES, Settings, size_limit_message
from app.main import create_app
from app.receipt_intake.repository import read_original_bytes, resolve_storage_path
from app.receipt_intake.validation import declared_body_too_large, sanitize_original_filename

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_image(image_format: str, color: tuple[int, int, int] = (20, 90, 70)) -> bytes:
    image = Image.new("RGB", (48, 48), color)
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def evidence_count(settings: Settings) -> int:
    with sqlite3.connect(settings.db_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM receipt_evidence").fetchone()[0]


def stored_files(settings: Settings) -> list[Path]:
    return sorted(path for path in settings.files_dir.iterdir() if path.is_file())


def upload(client: TestClient, filename: str, content: bytes, content_type: str = "application/octet-stream"):
    return client.post(
        "/api/receipts",
        files={"file": (filename, content, content_type)},
    )


def test_valid_jpeg_is_preserved(client: TestClient, settings: Settings):
    original = make_image("JPEG", (180, 40, 40))
    response = upload(client, "Store Receipt.jpg", original, "application/octet-stream")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "accepted"
    assert body["original_filename"] == "Store Receipt.jpg"
    assert body["mime_type"] == "image/jpeg"
    assert body["byte_size"] == len(original)
    assert body["uploaded_at"]
    assert body["storage_reference"].startswith("receipt-evidence/files/")
    assert body["storage_reference"].endswith(".jpg")
    assert "\\" not in body["storage_reference"]
    assert ":" not in body["storage_reference"]

    follow_up = client.get(f"/api/receipts/{body['evidence_id']}")
    assert follow_up.status_code == 200
    assert follow_up.json()["evidence_id"] == body["evidence_id"]
    assert read_original_bytes(settings, body["storage_reference"]) == original


def test_valid_png_is_preserved(client: TestClient, settings: Settings):
    original = make_image("PNG", (20, 70, 140))
    response = upload(client, "receipt.png", original, "image/png")

    assert response.status_code == 201
    body = response.json()
    assert body["mime_type"] == "image/png"
    assert body["original_filename"] == "receipt.png"
    assert body["byte_size"] == len(original)
    assert read_original_bytes(settings, body["storage_reference"]) == original


def test_valid_webp_is_preserved(client: TestClient, settings: Settings):
    original = make_image("WEBP", (40, 40, 40))
    response = upload(client, "receipt.webp", original, "image/webp")

    assert response.status_code == 201
    body = response.json()
    assert body["mime_type"] == "image/webp"
    assert read_original_bytes(settings, body["storage_reference"]) == original


def test_evidence_integrity_matches_uploaded_bytes(client: TestClient, settings: Settings):
    original = make_image("JPEG", (10, 20, 30))
    response = upload(client, "integrity.jpg", original, "image/jpeg")
    body = response.json()
    preserved = read_original_bytes(settings, body["storage_reference"])

    assert preserved == original
    assert hashlib.sha256(preserved).digest() == hashlib.sha256(original).digest()
    assert evidence_count(settings) == 1


def test_unsupported_file_is_rejected(client: TestClient, settings: Settings):
    response = upload(client, "notes.txt", b"this is not a receipt", "text/plain")

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "rejected"
    assert "JPEG, PNG, or WEBP" in body["reason"]
    assert "traceback" not in response.text.lower()
    assert evidence_count(settings) == 0
    assert stored_files(settings) == []


def test_mislabeled_text_as_jpeg_is_rejected(client: TestClient, settings: Settings):
    response = upload(client, "receipt.jpg", b"not really a jpeg", "image/jpeg")

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert evidence_count(settings) == 0
    assert stored_files(settings) == []


def test_gif_is_rejected(client: TestClient, settings: Settings):
    response = upload(client, "receipt.gif", make_image("GIF"), "image/gif")

    assert response.status_code == 400
    assert "not supported" in response.json()["reason"].lower()
    assert evidence_count(settings) == 0
    assert stored_files(settings) == []


def test_empty_file_is_rejected(client: TestClient, settings: Settings):
    response = upload(client, "empty.jpg", b"", "image/jpeg")

    assert response.status_code == 400
    assert response.json() == {"status": "rejected", "reason": "The file is empty."}
    assert evidence_count(settings) == 0
    assert stored_files(settings) == []


def test_oversized_file_is_rejected(client: TestClient, settings: Settings):
    oversized = b"\xff\xd8\xff" + (b"0" * (MAX_UPLOAD_BYTES - 2))
    assert len(oversized) == MAX_UPLOAD_BYTES + 1

    response = upload(client, "huge.jpg", oversized, "image/jpeg")

    assert response.status_code == 400
    assert response.json()["reason"] == size_limit_message()
    assert "10 MB" in response.json()["reason"]
    assert evidence_count(settings) == 0
    assert stored_files(settings) == []


def test_path_traversal_cannot_escape_evidence_store(client: TestClient, settings: Settings, tmp_path: Path):
    source = (PROJECT_ROOT / "app" / "main.py").read_bytes()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "escaped.jpg"
    sentinel.write_bytes(b"sentinel")
    database_before = settings.db_path.read_bytes()
    original = make_image("JPEG", (1, 2, 3))

    malicious_names = [
        r"..\..\..\app\main.py",
        "../../outside/escaped.jpg",
        str(sentinel),
        "..\\evidence.sqlite",
        "receipt.jpg\x00.exe",
    ]
    for name in malicious_names:
        response = upload(client, name, original, "image/jpeg")
        assert response.status_code == 201, name
        body = response.json()
        stored = resolve_storage_path(settings, body["storage_reference"])
        assert stored.is_relative_to(settings.files_dir.resolve())
        assert stored.read_bytes() == original
        assert stored.name != "main.py"
        assert stored.suffix == ".jpg"

    assert (PROJECT_ROOT / "app" / "main.py").read_bytes() == source
    assert sentinel.read_bytes() == b"sentinel"
    assert settings.db_path.read_bytes()[:16] == b"SQLite format 3\x00"
    assert not database_before.startswith(b"\xff\xd8\xff")
    for path in stored_files(settings):
        assert path.parent.resolve() == settings.files_dir.resolve()
        assert path.suffix in {".jpg", ".png", ".webp"}


def test_declared_type_and_extension_do_not_override_bytes(client: TestClient, settings: Settings):
    original = make_image("PNG", (9, 9, 9))
    response = upload(client, "notes.txt", original, "text/plain")

    assert response.status_code == 201
    body = response.json()
    assert body["mime_type"] == "image/png"
    assert body["original_filename"] == "notes.txt"
    assert body["storage_reference"].endswith(".png")
    assert read_original_bytes(settings, body["storage_reference"]) == original


def test_missing_file_is_rejected(client: TestClient, settings: Settings):
    response = client.post("/api/receipts")

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "rejected"
    assert body["reason"]
    assert "traceback" not in response.text.lower()
    assert "sqlite" not in response.text.lower()
    assert evidence_count(settings) == 0


def test_unknown_evidence_id_is_not_found(client: TestClient):
    response = client.get("/api/receipts/not-an-id")

    assert response.status_code == 404
    assert response.json()["status"] == "not_found"
    assert "traceback" not in response.text.lower()


def test_evidence_is_not_served_as_a_static_file(client: TestClient):
    original = make_image("PNG")
    response = upload(client, "receipt.png", original, "image/png")
    reference = response.json()["storage_reference"]

    assert client.get("/" + reference).status_code == 404
    assert client.get("/data/receipt_evidence/files/" + Path(reference).name).status_code == 404


def test_intake_page_preserves_desktop_intake_form(client: TestClient):
    response = client.get("/intake")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Receipt intake" in response.text
    assert "Preserve receipt" in response.text
    assert "Maximum 10 MB" in response.text
    assert "script-src 'self'" in response.headers["content-security-policy"]
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "Upload accepted" in script.text
    assert "innerHTML" not in script.text


def test_filename_sanitization():
    assert sanitize_original_filename(r"..\..\..\receipt.jpg") == "receipt.jpg"
    assert sanitize_original_filename("../../etc/passwd") == "passwd"
    assert sanitize_original_filename("..") == "receipt"
    assert sanitize_original_filename("  café receipt.jpg  ") == "café receipt.jpg"
    assert "\x00" not in sanitize_original_filename("a\x00b.jpg")
    assert declared_body_too_large(str(MAX_UPLOAD_BYTES + (256 * 1024) + 1), MAX_UPLOAD_BYTES)
    assert not declared_body_too_large(str(MAX_UPLOAD_BYTES), MAX_UPLOAD_BYTES)


def test_storage_reference_rejects_escape(settings: Settings):
    import pytest

    with pytest.raises(ValueError):
        resolve_storage_path(settings, "receipt-evidence/files/../../app/main.py")
    with pytest.raises(ValueError):
        resolve_storage_path(settings, r"receipt-evidence/files/..\..\evidence.sqlite")

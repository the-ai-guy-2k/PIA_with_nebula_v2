"""Store original receipt bytes and the minimum evidence record."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.receipt_intake.models import EvidenceRecord
from app.receipt_intake.validation import MIME_TO_EXTENSION

_SCHEMA = """
CREATE TABLE IF NOT EXISTS receipt_evidence (
    evidence_id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    storage_reference TEXT NOT NULL,
    mime_type TEXT NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    uploaded_at TEXT NOT NULL
);
"""

_STORED_NAME = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|webp)\Z"
)
_PARTIAL_NAME = re.compile(
    r"\A\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|webp)\.partial\Z"
)


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(_SCHEMA)
        connection.commit()


def save_original(
    settings: Settings,
    content: bytes,
    original_filename: str,
    mime_type: str,
) -> EvidenceRecord:
    """Write the original bytes first, then the evidence record that points at them."""
    extension = MIME_TO_EXTENSION[mime_type]
    evidence_id = str(uuid.uuid4())
    stored_name = f"{evidence_id}{extension}"
    if _STORED_NAME.fullmatch(stored_name) is None:
        raise RuntimeError("refusing to write an unsafe storage name")

    settings.files_dir.mkdir(parents=True, exist_ok=True)
    destination = _guarded_file(settings.files_dir, stored_name)
    partial = _guarded_file(settings.files_dir, f".{stored_name}.partial")
    record = EvidenceRecord(
        evidence_id=evidence_id,
        original_filename=original_filename,
        storage_reference=f"receipt-evidence/files/{stored_name}",
        mime_type=mime_type,
        byte_size=len(content),
        uploaded_at=datetime.now(timezone.utc).isoformat(),
    )

    inserted = False
    try:
        with partial.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, destination)
        _insert_evidence(settings.db_path, record)
        inserted = True
    except Exception:
        partial.unlink(missing_ok=True)
        if not inserted:
            destination.unlink(missing_ok=True)
        raise
    return record


def get_evidence(settings: Settings, evidence_id: str) -> EvidenceRecord | None:
    with sqlite3.connect(settings.db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT evidence_id, original_filename, storage_reference, mime_type, byte_size, uploaded_at
            FROM receipt_evidence
            WHERE evidence_id = ?
            """,
            (evidence_id,),
        ).fetchone()
    if row is None:
        return None
    return EvidenceRecord(
        evidence_id=row["evidence_id"],
        original_filename=row["original_filename"],
        storage_reference=row["storage_reference"],
        mime_type=row["mime_type"],
        byte_size=row["byte_size"],
        uploaded_at=row["uploaded_at"],
    )


def read_original_bytes(settings: Settings, storage_reference: str) -> bytes:
    """Read preserved bytes through the storage reference, never a caller-supplied path."""
    path = resolve_storage_path(settings, storage_reference)
    return path.read_bytes()


def resolve_storage_path(settings: Settings, storage_reference: str) -> Path:
    prefix = "receipt-evidence/files/"
    if not storage_reference.startswith(prefix):
        raise ValueError("invalid storage reference")
    stored_name = storage_reference[len(prefix) :]
    if _STORED_NAME.fullmatch(stored_name) is None:
        raise ValueError("invalid storage reference")
    return _guarded_file(settings.files_dir, stored_name)


def _insert_evidence(db_path: Path, record: EvidenceRecord) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO receipt_evidence (
                evidence_id,
                original_filename,
                storage_reference,
                mime_type,
                byte_size,
                uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.evidence_id,
                record.original_filename,
                record.storage_reference,
                record.mime_type,
                record.byte_size,
                record.uploaded_at,
            ),
        )
        connection.commit()


def _guarded_file(files_dir: Path, name: str) -> Path:
    allowed = _STORED_NAME.fullmatch(name) or _PARTIAL_NAME.fullmatch(name)
    if allowed is None or Path(name).name != name:
        raise RuntimeError("refusing to write an unsafe storage name")
    root = files_dir.resolve()
    candidate = (files_dir / name).resolve()
    if not candidate.is_relative_to(root):
        raise RuntimeError("storage path escaped the evidence directory")
    return candidate

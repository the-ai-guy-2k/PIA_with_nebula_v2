"""Orchestrate validation and original-evidence preservation."""

from __future__ import annotations

from app.config import Settings
from app.receipt_intake.models import EvidenceRecord
from app.receipt_intake.repository import save_original
from app.receipt_intake.validation import sanitize_original_filename, validate_receipt_bytes


def preserve_upload(
    content: bytes,
    original_filename: str | None,
    settings: Settings,
) -> EvidenceRecord:
    mime_type = validate_receipt_bytes(content, settings.max_upload_bytes)
    safe_name = sanitize_original_filename(original_filename)
    return save_original(
        settings=settings,
        content=content,
        original_filename=safe_name,
        mime_type=mime_type,
    )

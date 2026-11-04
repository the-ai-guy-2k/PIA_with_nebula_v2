"""Extract a candidate reading from preserved receipt evidence.

Re-running extraction for the same evidence id replaces the previous
unconfirmed extraction. The original image and evidence record stay as they were.
"""

from __future__ import annotations

from app.config import Settings
from app.receipt_extraction.errors import EvidenceNotFound, UnreadableReceipt
from app.receipt_extraction.models import ExtractionRecord
from app.receipt_extraction.ocr import recognize_lines
from app.receipt_extraction.parser import ParsedReceipt, parse_receipt_text
from app.receipt_extraction.repository import get_extraction, replace_extraction
from app.receipt_intake.models import parse_evidence_id
from app.receipt_intake.repository import get_evidence, read_original_bytes

_MISSING_FILE = "The preserved receipt file is missing."
_UNREADABLE = "The preserved receipt image could not be read."


async def extract_preserved_receipt(settings: Settings, evidence_id: str) -> ExtractionRecord:
    canonical = _require_evidence(settings, evidence_id)
    try:
        image_bytes = read_original_bytes(settings, _storage_reference(settings, canonical))
    except FileNotFoundError:
        return _failed(settings, canonical, _MISSING_FILE)
    except (OSError, ValueError):
        return _failed(settings, canonical, _UNREADABLE)

    try:
        lines = await recognize_lines(image_bytes)
    except UnreadableReceipt as exc:
        return _failed(settings, canonical, exc.reason)
    parsed = parse_receipt_text(lines)
    return replace_extraction(settings, canonical, parsed)


def read_extraction(settings: Settings, evidence_id: str) -> ExtractionRecord | None:
    canonical = _require_evidence(settings, evidence_id)
    return get_extraction(settings, canonical)


def _require_evidence(settings: Settings, evidence_id: str) -> str:
    canonical = parse_evidence_id(evidence_id)
    if canonical is None or get_evidence(settings, canonical) is None:
        raise EvidenceNotFound()
    return canonical


def _storage_reference(settings: Settings, evidence_id: str) -> str:
    record = get_evidence(settings, evidence_id)
    if record is None:
        raise EvidenceNotFound()
    return record.storage_reference


def _failed(settings: Settings, evidence_id: str, reason: str) -> ExtractionRecord:
    parsed = ParsedReceipt(
        merchant_raw=None,
        merchant_normalized_candidate=None,
        purchase_date_candidate=None,
        purchase_time_candidate=None,
        subtotal_candidate=None,
        tax_candidate=None,
        total_candidate=None,
        raw_text="",
        extraction_status="failed",
        lines=(),
    )
    return replace_extraction(settings, evidence_id, parsed, failure_reason=reason)

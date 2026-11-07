"""Muse AI loop: queue a receipt, ingest a Muse extraction.

Ingest converts a validated Muse extraction into the existing
ParsedReceipt shape and stores it with replace_extraction() — so it becomes
the receipt's current UNCONFIRMED extraction, exactly like the deterministic
OCR path, and the Review screen shows it with no UI change. A Muse
extraction never confirms a purchase and never touches the pantry.
"""

from __future__ import annotations

from app.config import Settings
from app.muse_ai import queue as queue_mod
from app.muse_ai.models import MuseAudit, QueueRecord
from app.muse_ai.repository import init_muse_ai_db, record_audit
from app.muse_ai.validation import MusePayloadError, validate_muse_payload
from app.receipt_extraction.errors import EvidenceNotFound
from app.receipt_extraction.models import ExtractionRecord
from app.receipt_extraction.parser import ParsedLine, ParsedReceipt
from app.receipt_extraction.repository import replace_extraction
from app.receipt_extraction.service import read_extraction
from app.receipt_intake.repository import get_evidence


def queue_receipt(settings: Settings, evidence_id: str) -> QueueRecord:
    if get_evidence(settings, evidence_id) is None:
        raise EvidenceNotFound()
    existing = read_extraction(settings, evidence_id)
    ocr_text = existing.raw_text if existing is not None else ""
    return queue_mod.queue_record(settings, evidence_id, ocr_text=ocr_text)


def queue_status(settings: Settings, evidence_id: str) -> QueueRecord | None:
    return queue_mod.read_record(settings, evidence_id)


def ingest_muse_extraction(
    settings: Settings, evidence_id: str, payload: object
) -> tuple[ExtractionRecord, MuseAudit]:
    """Validate a Muse JSON payload and store it as the unconfirmed extraction."""
    if get_evidence(settings, evidence_id) is None:
        raise EvidenceNotFound()
    validated = validate_muse_payload(payload)
    parsed = ParsedReceipt(
        merchant_raw=validated.merchant,
        merchant_normalized_candidate=validated.merchant,
        purchase_date_candidate=validated.purchase_date,
        purchase_time_candidate=validated.purchase_time,
        subtotal_candidate=validated.subtotal,
        tax_candidate=validated.tax,
        total_candidate=validated.total,
        raw_text="\n".join(line.raw_text for line in validated.lines),
        extraction_status="extracted" if validated.lines else "insufficient_data",
        lines=tuple(
            ParsedLine(
                raw_text=line.raw_text,
                normalized_name_candidate=line.name,
                quantity_candidate=line.quantity,
                unit_price_candidate=line.unit_price,
                line_total_candidate=line.line_total,
            )
            for line in validated.lines
        ),
    )
    record = replace_extraction(settings, evidence_id, parsed)
    audit = record_audit(
        settings,
        MuseAudit(
            extraction_id=record.extraction_id,
            evidence_id=evidence_id,
            totals_reconciled=validated.totals_reconciled,
            lines_sum=validated.lines_sum,
            total_mismatch=validated.total_mismatch,
            confidence={str(i + 1): line.confidence for i, line in enumerate(validated.lines)},
        ),
    )
    status = "done_with_mismatch" if validated.total_mismatch else "done"
    try:
        queue_mod.set_status(settings, evidence_id, status, extraction_id=record.extraction_id)
    except KeyError:
        pass
    return record, audit


def fail_queue(settings: Settings, evidence_id: str, reason: str) -> None:
    try:
        queue_mod.set_status(settings, evidence_id, "failed", error=reason)
    except KeyError:
        pass

"""Muse AI loop: queue a receipt, ingest a Muse extraction.

Ingest converts a validated Muse extraction into the existing
ParsedReceipt shape and stores it with replace_extraction() — so it becomes
the receipt's current extraction, exactly like the deterministic
OCR path.

Auto-confirm (Tee, Nov 16, 2026 — Review & Confirm removed): when a Muse
extraction reconciles — lines sum to the subtotal, subtotal + tax equals
the total (±$0.02), and every line's qty x unit price matches its line
total — the receipt auto-confirms on ingest, using the SAME validation
as the manual confirm (confirm_purchase), then the same memory + pantry
steps. A mismatch, a bad line, or a failed validation holds the receipt
unconfirmed: reconcile-or-hold is the safety net now that no human
confirms it.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.muse_ai import queue as queue_mod
from app.muse_ai.models import MuseAudit, MuseExtraction, QueueRecord
from app.muse_ai.repository import init_muse_ai_db, record_audit
from app.muse_ai.validation import MusePayloadError, validate_muse_payload
from app.pantry.service import add_from_purchase
from app.purchase_confirmation.errors import AlreadyConfirmed, ConfirmationRejected
from app.purchase_confirmation.repository import get_purchase_for_evidence, get_purchase_for_extraction
from app.purchase_confirmation.service import confirm_purchase
from app.purchase_memory.service import remember_purchase
from app.receipt_extraction.errors import EvidenceNotFound
from app.receipt_extraction.models import ExtractionRecord
from app.receipt_extraction.parser import ParsedLine, ParsedReceipt
from app.receipt_extraction.repository import replace_extraction
from app.receipt_extraction.service import read_extraction
from app.receipt_intake.repository import get_evidence

logger = logging.getLogger("purchase_intelligence.muse_ai")


def auto_confirm_reconciled(
    settings: Settings, record: ExtractionRecord, validated: MuseExtraction
) -> dict[str, object]:
    """Auto-confirm a reconciled Muse extraction. Returns an outcome dict.

    Never raises for a held receipt: problems come back as held + reason.
    Already-confirmed is idempotent: the existing purchase is returned.
    The confirm itself runs confirm_purchase(), the same validation the
    manual Review & Confirm screen ran — nothing is silently fixed.
    """
    if not validated.totals_reconciled:
        return {"status": "held", "reason": "Totals did not reconcile."}
    if any(not line.line_total_ok for line in validated.lines):
        reason = "; ".join(validated.flags) or "A receipt line does not add up."
        return {"status": "held", "reason": reason}
    if not record.lines or record.extraction_status in {"failed", "no_text"}:
        return {"status": "held", "reason": "This extraction has no item lines to confirm."}
    existing_for_receipt = get_purchase_for_evidence(settings, record.evidence_id)
    if existing_for_receipt is not None:
        # Re-ingest after a correction must never log the receipt twice:
        # extractions are replaced (new id each time), so per-extraction
        # uniqueness alone cannot catch it. One receipt, one purchase.
        return {"status": "already_confirmed", "purchase_id": existing_for_receipt.purchase_id}
    payload = {
        "evidence_id": record.evidence_id,
        "extraction_id": record.extraction_id,
        "merchant": record.merchant_normalized_candidate,
        "purchase_date": record.purchase_date_candidate,
        "purchase_time": record.purchase_time_candidate,
        "subtotal": record.subtotal_candidate,
        "tax": record.tax_candidate,
        "total": record.total_candidate,
        "items": [
            {
                "source_line_id": line.line_id,
                "item_name": line.normalized_name_candidate,
                "quantity": line.quantity_candidate,
                "unit_price": line.unit_price_candidate,
                "line_total": line.line_total_candidate,
            }
            for line in record.lines
        ],
    }
    try:
        purchase = confirm_purchase(settings, payload)
    except AlreadyConfirmed as exc:
        return {"status": "already_confirmed", "purchase_id": exc.purchase_id}
    except ConfirmationRejected as exc:
        return {"status": "held", "reason": str(exc)}
    warnings: list[str] = []
    memory = None
    try:
        memory, _created = remember_purchase(settings, purchase.purchase_id)
    except Exception as exc:  # purchase is already written; report, don't lose it
        warnings.append(f"purchase history was not saved: {exc}")
    pantry_items: list = []
    try:
        pantry_items = add_from_purchase(settings, purchase)
    except Exception as exc:  # purchase is already written; report, don't lose it
        warnings.append(f"pantry could not be updated: {exc}")
    outcome: dict[str, object] = {
        "status": "confirmed",
        "purchase_id": purchase.purchase_id,
        "memory_id": memory.memory_id if memory is not None else None,
        "pantry_items": len(pantry_items),
    }
    if warnings:
        outcome["warnings"] = warnings
    return outcome


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
) -> tuple[ExtractionRecord, MuseAudit, dict[str, object]]:
    """Validate a Muse JSON payload, store it, and auto-confirm if it reconciles.

    Returns (record, audit, auto_confirm outcome). A held receipt is still
    stored — it just never becomes a purchase.
    """
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
    outcome = auto_confirm_reconciled(settings, record, validated)
    if validated.total_mismatch:
        status = "done_with_mismatch"
    elif outcome["status"] == "held":
        status = "held"
    else:
        status = "done"
    try:
        queue_mod.set_status(settings, evidence_id, status, extraction_id=record.extraction_id)
    except KeyError:
        pass
    logger.info(
        "muse-ai auto-confirm evidence_id=%s extraction_id=%s status=%s",
        evidence_id,
        record.extraction_id,
        outcome["status"],
    )
    return record, audit, outcome


def fail_queue(settings: Settings, evidence_id: str, reason: str) -> None:
    try:
        queue_mod.set_status(settings, evidence_id, "failed", error=reason)
    except KeyError:
        pass

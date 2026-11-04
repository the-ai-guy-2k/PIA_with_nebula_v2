"""Confirm a reviewed extraction without changing the receipt or raw text.

One extraction has one confirmed purchase. A second confirmation is rejected.
The confirmed record is read-only in this capability.
"""

from __future__ import annotations

from app.config import Settings
from app.purchase_confirmation.errors import AlreadyConfirmed, ConfirmationRejected, ExtractionNotFound
from app.purchase_confirmation.models import ConfirmedItem, ConfirmedPurchase
from app.purchase_confirmation.repository import (
    confirmation_timestamp,
    get_purchase,
    get_purchase_for_extraction,
    insert_purchase,
    new_item_id,
    new_purchase_id,
)
from app.purchase_confirmation.validation import (
    clean_optional_label,
    parse_date,
    parse_money,
    parse_quantity,
    parse_time,
    require_item_name,
)
from app.receipt_extraction.errors import EvidenceNotFound
from app.receipt_extraction.repository import get_extraction_by_id
from app.receipt_intake.models import parse_evidence_id
from app.receipt_intake.repository import get_evidence, read_original_bytes

_NO_ITEMS = "This extraction has no item lines to confirm."
_MISSING_FILE = "The preserved receipt file is missing."
_FOREIGN_LINE = "That line does not belong to this extraction."
_ALL_LINES = "Every extracted line must be included."
_UNRELATED = "The extraction does not belong to this receipt."
_MALFORMED = "The confirmation could not be read."


def confirm_purchase(settings: Settings, payload: object) -> ConfirmedPurchase:
    if not isinstance(payload, dict):
        raise ConfirmationRejected(_MALFORMED)
    evidence_id = _canonical_id(payload.get("evidence_id"))
    extraction_id = _canonical_id(payload.get("extraction_id"))
    if evidence_id is None or get_evidence(settings, evidence_id) is None:
        raise EvidenceNotFound()
    if extraction_id is None:
        raise ExtractionNotFound()
    extraction = get_extraction_by_id(settings, extraction_id)
    if extraction is None:
        raise ExtractionNotFound()
    if extraction.evidence_id != evidence_id:
        raise ConfirmationRejected(_UNRELATED)
    evidence = get_evidence(settings, evidence_id)
    if evidence is None:
        raise EvidenceNotFound()
    try:
        read_original_bytes(settings, evidence.storage_reference)
    except FileNotFoundError:
        raise ConfirmationRejected(_MISSING_FILE) from None

    existing = get_purchase_for_extraction(settings, extraction.extraction_id)
    if existing is not None:
        raise AlreadyConfirmed(existing.purchase_id)
    if not extraction.lines or extraction.extraction_status in {"failed", "no_text"}:
        raise ConfirmationRejected(_NO_ITEMS)

    submitted = _submitted_items(payload.get("items"), extraction.lines)
    purchase_id = new_purchase_id()
    items = []
    for line in extraction.lines:
        incoming = submitted[line.line_id]
        items.append(
            ConfirmedItem(
                purchase_item_id=new_item_id(),
                purchase_id=purchase_id,
                source_line_id=line.line_id,
                item_name=require_item_name(incoming.get("item_name")),
                quantity=parse_quantity(incoming.get("quantity")),
                unit_price=parse_money(incoming.get("unit_price"), "unit price"),
                line_total=parse_money(incoming.get("line_total"), "line total"),
                raw_line_text=line.raw_text,
                line_order=line.line_order,
            )
        )
    purchase = ConfirmedPurchase(
        purchase_id=purchase_id,
        evidence_id=evidence_id,
        extraction_id=extraction.extraction_id,
        merchant=clean_optional_label(payload.get("merchant"), "merchant", 120),
        purchase_date=parse_date(payload.get("purchase_date")),
        purchase_time=parse_time(payload.get("purchase_time")),
        subtotal=parse_money(payload.get("subtotal"), "subtotal"),
        tax=parse_money(payload.get("tax"), "tax"),
        total=parse_money(payload.get("total"), "total"),
        confirmed_at=confirmation_timestamp(),
        items=tuple(items),
    )
    return insert_purchase(settings, purchase)


def read_purchase(settings: Settings, purchase_id: str) -> ConfirmedPurchase | None:
    canonical = parse_evidence_id(purchase_id) if isinstance(purchase_id, str) else None
    if canonical is None:
        return None
    return get_purchase(settings, canonical)


def _canonical_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return parse_evidence_id(value)


def _submitted_items(value: object, lines) -> dict[str, dict]:
    if not isinstance(value, list):
        raise ConfirmationRejected(_MALFORMED)
    expected = {line.line_id for line in lines}
    submitted: dict[str, dict] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ConfirmationRejected(_MALFORMED)
        source_line_id = item.get("source_line_id")
        if not isinstance(source_line_id, str) or source_line_id not in expected:
            raise ConfirmationRejected(_FOREIGN_LINE)
        if source_line_id in submitted:
            raise ConfirmationRejected(_ALL_LINES)
        submitted[source_line_id] = item
    if set(submitted) != expected:
        raise ConfirmationRejected(_ALL_LINES)
    return submitted

"""Correction rules: record, never overwrite, suggest, never auto-apply."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.corrections.models import FIELDS, Correction, pattern_key_for
from app.corrections.repository import (
    insert_correction,
    latest_for_pattern,
    list_corrections,
)
from app.receipt_extraction.repository import get_extraction_by_id


class CorrectionNotFound(Exception):
    pass


class CorrectionRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _original_for(extraction, field: str, item_id: str | None) -> str | None:
    if field == "store":
        return extraction.merchant_normalized_candidate or extraction.merchant_raw
    if field == "date":
        return extraction.purchase_date_candidate
    if field == "total":
        return extraction.total_candidate
    if item_id is None:
        return None
    line = next((line for line in extraction.lines if line.line_id == item_id), None)
    if line is None:
        return None
    return {
        "name": line.normalized_name_candidate or line.raw_text,
        "qty": line.quantity_candidate,
        "price": line.unit_price_candidate or line.line_total_candidate,
    }.get(field)


def record_correction(settings: Settings, extraction_id: str, payload: object) -> Correction:
    if not isinstance(payload, dict):
        raise CorrectionRejected("The correction could not be read.")
    field = payload.get("field")
    if field not in FIELDS:
        raise CorrectionRejected("Choose name, qty, price, store, date, or total.")
    corrected = payload.get("corrected_value")
    if not isinstance(corrected, str) or not corrected.strip():
        raise CorrectionRejected("A corrected value is required.")
    extraction = get_extraction_by_id(settings, extraction_id)
    if extraction is None:
        raise CorrectionNotFound()
    item_id = payload.get("item_id")
    if item_id is not None and not isinstance(item_id, str):
        raise CorrectionRejected("The item could not be read.")
    if field in ("name", "qty", "price") and item_id is None:
        raise CorrectionRejected("An item is required for this field.")
    original = _original_for(extraction, field, item_id)
    if field in ("name", "qty", "price") and original is None and not any(
        line.line_id == item_id for line in extraction.lines
    ):
        raise CorrectionNotFound()
    return insert_correction(
        settings,
        Correction(
            correction_id=str(uuid.uuid4()),
            receipt_id=extraction.evidence_id,
            extraction_id=extraction.extraction_id,
            item_id=item_id,
            field=field,
            original_value=original,
            corrected_value=corrected.strip(),
            corrected_by="user",
            corrected_at=_timestamp(),
            pattern_key=pattern_key_for(field, original),
        ),
    )


def suggestions_for_extraction(settings: Settings, extraction) -> dict[str, object]:
    """Pattern suggestions only. Flagged, unconfirmed, never auto-applied."""
    suggestions: dict[str, object] = {}
    for field, original in (
        ("store", extraction.merchant_normalized_candidate or extraction.merchant_raw),
        ("date", extraction.purchase_date_candidate),
        ("total", extraction.total_candidate),
    ):
        prior = latest_for_pattern(settings, pattern_key_for(field, original))
        if prior is not None and prior.extraction_id != extraction.extraction_id:
            suggestions[field] = {
                "suggested_value": prior.corrected_value,
                "from_your_correction": True,
                "pattern_key": prior.pattern_key,
                "status": "suggestion_only_unconfirmed",
            }
    line_suggestions = []
    for line in extraction.lines:
        for field, original in (
            ("name", line.normalized_name_candidate or line.raw_text),
            ("qty", line.quantity_candidate),
            ("price", line.unit_price_candidate or line.line_total_candidate),
        ):
            prior = latest_for_pattern(settings, pattern_key_for(field, original))
            if prior is not None and prior.extraction_id != extraction.extraction_id:
                line_suggestions.append({
                    "line_id": line.line_id,
                    "field": field,
                    "suggested_value": prior.corrected_value,
                    "from_your_correction": True,
                    "pattern_key": prior.pattern_key,
                    "status": "suggestion_only_unconfirmed",
                })
    if line_suggestions:
        suggestions["lines"] = line_suggestions
    return suggestions


def corrections_for_extraction(settings: Settings, extraction_id: str) -> list[Correction]:
    return list_corrections(settings, extraction_id=extraction_id)


def corrections_for_pattern(settings: Settings, pattern_key: str) -> list[Correction]:
    return list_corrections(settings, pattern_key=pattern_key)

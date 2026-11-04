"""Deterministic review hints. These are not measured model probabilities."""

from __future__ import annotations

import re

from app.receipt_extraction.models import ExtractionRecord, LineCandidate

_AMBIGUOUS_AMOUNT = re.compile(
    r"(?<![\w])\$?(?:\d+[A-Za-z]\d*\.[\dA-Za-z]+|\d+\.[A-Za-z]\d*|[A-Za-z]\.\s*\d{2})(?![\w])"
)
_TIME_TOKEN = re.compile(r"\b\d{1,2}:\d{2}\b")


def assess_extraction(record: ExtractionRecord) -> dict[str, object]:
    raw_text = record.raw_text or ""
    return {
        "merchant": "medium" if record.merchant_normalized_candidate else "low",
        "purchase_date": "high" if record.purchase_date_candidate else "low",
        "purchase_time": _time_level(record.purchase_time_candidate, raw_text),
        "subtotal": _keyword_level(record.subtotal_candidate, raw_text, "subtotal"),
        "tax": _keyword_level(record.tax_candidate, raw_text, "tax"),
        "total": _keyword_level(record.total_candidate, raw_text, "total"),
        "lines": [_line_levels(line) for line in record.lines],
    }


def _keyword_level(value: str | None, raw_text: str, keyword: str) -> str:
    if value:
        return "high"
    if re.search(rf"\b{keyword}\b", raw_text, re.IGNORECASE):
        return "low"
    return "absent"


def _time_level(value: str | None, raw_text: str) -> str:
    if value:
        return "high"
    if _TIME_TOKEN.search(raw_text):
        return "low"
    return "absent"


def _line_levels(line: LineCandidate) -> dict[str, str]:
    raw = line.raw_text or ""
    ambiguous = _AMBIGUOUS_AMOUNT.search(raw) is not None
    return {
        "line_id": line.line_id,
        "item_name": "medium" if line.normalized_name_candidate else "low",
        "quantity": _quantity_level(line.quantity_candidate, raw),
        "unit_price": "high" if line.unit_price_candidate else ("low" if ambiguous else "absent"),
        "line_total": "high" if line.line_total_candidate else ("low" if ambiguous else "absent"),
    }


def _quantity_level(value: str | None, raw_text: str) -> str:
    if value:
        return "high"
    if "@" in raw_text:
        return "low"
    return "absent"

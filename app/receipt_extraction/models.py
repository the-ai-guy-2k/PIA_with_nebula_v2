"""Unconfirmed receipt-extraction records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineCandidate:
    line_id: str
    extraction_id: str
    raw_text: str
    normalized_name_candidate: str | None
    quantity_candidate: str | None
    unit_price_candidate: str | None
    line_total_candidate: str | None
    line_order: int

    def to_public_dict(self) -> dict[str, object]:
        return {
            "line_id": self.line_id,
            "extraction_id": self.extraction_id,
            "raw_text": self.raw_text,
            "normalized_name_candidate": self.normalized_name_candidate,
            "quantity_candidate": self.quantity_candidate,
            "unit_price_candidate": self.unit_price_candidate,
            "line_total_candidate": self.line_total_candidate,
            "line_order": self.line_order,
        }


@dataclass(frozen=True)
class ExtractionRecord:
    extraction_id: str
    evidence_id: str
    merchant_raw: str | None
    merchant_normalized_candidate: str | None
    purchase_date_candidate: str | None
    purchase_time_candidate: str | None
    subtotal_candidate: str | None
    tax_candidate: str | None
    total_candidate: str | None
    raw_text: str
    extraction_status: str
    failure_reason: str | None
    created_at: str
    lines: tuple[LineCandidate, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "extraction_id": self.extraction_id,
            "evidence_id": self.evidence_id,
            "merchant_raw": self.merchant_raw,
            "merchant_normalized_candidate": self.merchant_normalized_candidate,
            "purchase_date_candidate": self.purchase_date_candidate,
            "purchase_time_candidate": self.purchase_time_candidate,
            "subtotal_candidate": self.subtotal_candidate,
            "tax_candidate": self.tax_candidate,
            "total_candidate": self.total_candidate,
            "raw_text": self.raw_text,
            "extraction_status": self.extraction_status,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "lines": [line.to_public_dict() for line in self.lines],
        }

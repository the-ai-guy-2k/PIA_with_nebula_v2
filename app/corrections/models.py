"""Correction records. The original extraction is never overwritten.

A correction sits alongside the extraction, auditable, and feeds only
deterministic pattern suggestions. No correction data is sent to any
AI service in this layer.
"""

from __future__ import annotations

from dataclasses import dataclass


FIELDS = ("name", "qty", "price", "store", "date", "total")


@dataclass(frozen=True)
class Correction:
    correction_id: str
    receipt_id: str
    extraction_id: str
    item_id: str | None
    field: str
    original_value: str | None
    corrected_value: str
    corrected_by: str
    corrected_at: str
    pattern_key: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "correction_id": self.correction_id,
            "receipt_id": self.receipt_id,
            "extraction_id": self.extraction_id,
            "item_id": self.item_id,
            "field": self.field,
            "original_value": self.original_value,
            "corrected_value": self.corrected_value,
            "corrected_by": self.corrected_by,
            "corrected_at": self.corrected_at,
            "pattern_key": self.pattern_key,
        }


def pattern_key_for(field: str, original_value: str | None) -> str:
    normalized = (original_value or "").strip().lower()
    return f"{field}:{normalized}"

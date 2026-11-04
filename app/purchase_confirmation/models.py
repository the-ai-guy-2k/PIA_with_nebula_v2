"""Confirmed purchase records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfirmedItem:
    purchase_item_id: str
    purchase_id: str
    source_line_id: str
    item_name: str
    quantity: str | None
    unit_price: str | None
    line_total: str | None
    raw_line_text: str
    line_order: int

    def to_public_dict(self) -> dict[str, object]:
        return {
            "purchase_item_id": self.purchase_item_id,
            "purchase_id": self.purchase_id,
            "source_line_id": self.source_line_id,
            "item_name": self.item_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "line_total": self.line_total,
            "raw_line_text": self.raw_line_text,
            "line_order": self.line_order,
        }


@dataclass(frozen=True)
class ConfirmedPurchase:
    purchase_id: str
    evidence_id: str
    extraction_id: str
    merchant: str | None
    purchase_date: str | None
    purchase_time: str | None
    subtotal: str | None
    tax: str | None
    total: str | None
    confirmed_at: str
    items: tuple[ConfirmedItem, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": "confirmed",
            "purchase_id": self.purchase_id,
            "evidence_id": self.evidence_id,
            "extraction_id": self.extraction_id,
            "merchant": self.merchant,
            "purchase_date": self.purchase_date,
            "purchase_time": self.purchase_time,
            "subtotal": self.subtotal,
            "tax": self.tax,
            "total": self.total,
            "confirmed_at": self.confirmed_at,
            "items": [item.to_public_dict() for item in self.items],
        }

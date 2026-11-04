"""Remembered purchases. These copy confirmed facts and add classification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryItem:
    memory_item_id: str
    memory_id: str
    purchase_item_id: str
    item_name: str
    quantity: str | None
    unit_price: str | None
    line_total: str | None
    line_order: int
    food_classification: str
    need_want_classification: str
    durability_classification: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "memory_item_id": self.memory_item_id,
            "memory_id": self.memory_id,
            "purchase_item_id": self.purchase_item_id,
            "item_name": self.item_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "line_total": self.line_total,
            "line_order": self.line_order,
            "food_classification": self.food_classification,
            "need_want_classification": self.need_want_classification,
            "durability_classification": self.durability_classification,
        }


@dataclass(frozen=True)
class MemoryEntry:
    memory_id: str
    purchase_id: str
    evidence_id: str
    merchant: str | None
    purchase_date: str | None
    purchase_time: str | None
    created_at: str
    items: tuple[MemoryItem, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": "remembered",
            "memory_id": self.memory_id,
            "purchase_id": self.purchase_id,
            "evidence_id": self.evidence_id,
            "merchant": self.merchant,
            "purchase_date": self.purchase_date,
            "purchase_time": self.purchase_time,
            "created_at": self.created_at,
            "items": [item.to_public_dict() for item in self.items],
        }

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "purchase_id": self.purchase_id,
            "evidence_id": self.evidence_id,
            "merchant": self.merchant,
            "purchase_date": self.purchase_date,
            "purchase_time": self.purchase_time,
            "created_at": self.created_at,
            "item_count": len(self.items),
        }

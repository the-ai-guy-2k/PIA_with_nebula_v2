"""What's in the house: pantry items for the single user.

Status is a state, not a deletion. Used/gone items stay in history.
Low is computed, never stored as truth: in_stock or used with
qty_on_hand at or below 1 (and above 0) is low.
"""

from __future__ import annotations

from dataclasses import dataclass


STATUSES = ("in_stock", "used", "gone")
LOW_THRESHOLD = 1


@dataclass(frozen=True)
class PantryItem:
    pantry_item_id: str
    purchase_id: str | None
    purchase_item_id: str | None
    item_name: str
    quantity: str | None
    unit: str | None
    qty_on_hand: float
    status: str
    created_at: str
    updated_at: str

    @property
    def low(self) -> bool:
        return self.status in ("in_stock", "used") and 0 < self.qty_on_hand <= LOW_THRESHOLD

    def to_public_dict(self) -> dict[str, object]:
        return {
            "pantry_item_id": self.pantry_item_id,
            "purchase_id": self.purchase_id,
            "purchase_item_id": self.purchase_item_id,
            "item_name": self.item_name,
            "quantity": self.quantity,
            "unit": self.unit,
            "qty_on_hand": self.qty_on_hand,
            "status": self.status,
            "low": self.low,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PantryHistory:
    pantry_item_id: str
    from_status: str | None
    to_status: str
    qty_change: float
    changed_at: str
    note: str | None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "pantry_item_id": self.pantry_item_id,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "qty_change": self.qty_change,
            "changed_at": self.changed_at,
            "note": self.note,
        }

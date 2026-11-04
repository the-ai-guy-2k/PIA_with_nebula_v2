"""Pantry business rules, deterministic only.

- Confirming a purchase adds its items to the pantry (in_stock).
- Tapping Used marks the item used and reduces qty_on_hand by
  quantity_used (default 1); it never deletes the item.
- Tapping Gone marks the item gone and sets qty_on_hand to 0.
- Tapping In stock restores the state only; it does not invent qty.
- History is kept for every change.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from app.config import Settings
from app.pantry.models import STATUSES, PantryItem
from app.pantry.repository import (
    get_item,
    insert_item,
    list_history,
    list_items,
    new_pantry_item_id,
    update_item,
)
from app.purchase_confirmation.models import ConfirmedPurchase


class PantryNotFound(Exception):
    pass


class PantryRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _qty(value: object) -> float:
    try:
        qty = float(str(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    return qty if qty > 0 else 1.0


def add_from_purchase(settings: Settings, purchase: ConfirmedPurchase) -> list[PantryItem]:
    """Idempotent per purchase item: one pantry row per confirmed item."""
    created: list[PantryItem] = []
    existing = {(item.purchase_item_id, item.item_name) for item in list_items(settings)}
    for item in purchase.items:
        if (item.purchase_item_id, item.item_name) in existing:
            continue
        now = _timestamp()
        created.append(
            insert_item(
                settings,
                PantryItem(
                    pantry_item_id=new_pantry_item_id(),
                    purchase_id=purchase.purchase_id,
                    purchase_item_id=item.purchase_item_id,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    unit=None,
                    qty_on_hand=_qty(item.quantity),
                    status="in_stock",
                    created_at=now,
                    updated_at=now,
                ),
            )
        )
    return created


def add_manual_item(settings: Settings, payload: object) -> PantryItem:
    if not isinstance(payload, dict):
        raise PantryRejected("The item could not be read.")
    name = payload.get("item_name")
    if not isinstance(name, str) or not name.strip():
        raise PantryRejected("An item name is required.")
    now = _timestamp()
    return insert_item(
        settings,
        PantryItem(
            pantry_item_id=new_pantry_item_id(),
            purchase_id=None,
            purchase_item_id=None,
            item_name=name.strip(),
            quantity=str(payload.get("quantity")) if payload.get("quantity") is not None else None,
            unit=payload.get("unit") if isinstance(payload.get("unit"), str) else None,
            qty_on_hand=_qty(payload.get("quantity", 1)),
            status="in_stock",
            created_at=now,
            updated_at=now,
        ),
    )


def set_status(settings: Settings, pantry_item_id: str, payload: object) -> PantryItem:
    if not isinstance(payload, dict):
        raise PantryRejected("The status could not be read.")
    status = payload.get("status")
    if status not in STATUSES:
        raise PantryRejected("Choose in_stock, used, or gone.")
    current = get_item(settings, pantry_item_id)
    if current is None:
        raise PantryNotFound()
    if status == "gone":
        new_qty, change = 0.0, -current.qty_on_hand
    elif status == "used":
        used = _qty(payload.get("quantity_used", 1))
        new_qty, change = max(0.0, current.qty_on_hand - used), -min(used, current.qty_on_hand)
    else:
        new_qty, change = current.qty_on_hand, 0.0
        if payload.get("quantity") is not None:
            new_qty = _qty(payload.get("quantity"))
            change = new_qty - current.qty_on_hand
    updated = replace(current, qty_on_hand=new_qty, status=status, updated_at=_timestamp())
    return update_item(settings, updated, change, note=f"status set to {status} by user")


def read_pantry(settings: Settings, status: str | None = None) -> list[PantryItem]:
    if status is not None and status not in STATUSES:
        raise PantryRejected("Choose in_stock, used, or gone.")
    return list_items(settings, status)


def read_item_with_history(settings: Settings, pantry_item_id: str) -> dict[str, object] | None:
    item = get_item(settings, pantry_item_id)
    if item is None:
        return None
    payload = item.to_public_dict()
    payload["history"] = [entry.to_public_dict() for entry in list_history(settings, pantry_item_id)]
    return payload

"""Build purchase history from a confirmed purchase without changing it."""

from __future__ import annotations

from app.config import Settings
from app.purchase_confirmation.repository import get_purchase
from app.purchase_memory.classification import (
    DURABILITY_VALUES,
    FOOD_VALUES,
    NEED_VALUES,
    classify_item_name,
)
from app.purchase_memory.errors import MemoryNotFound, MemoryRejected, PurchaseNotFound
from app.purchase_memory.models import MemoryEntry, MemoryItem
from app.purchase_memory.repository import (
    get_memory,
    get_memory_for_purchase,
    insert_memory,
    list_memories,
    memory_timestamp,
    new_memory_id,
    new_memory_item_id,
    update_classifications,
)
from app.receipt_intake.models import parse_evidence_id
from app.receipt_intake.repository import get_evidence

_UNREADABLE = "The memory request could not be read."
_CLASSIFICATION_UNREADABLE = "The classification could not be read."
_EVIDENCE_UNAVAILABLE = "The receipt evidence for this purchase is unavailable."
_FOOD_CHOICE = "Choose food, non-food, or unknown."
_NEED_CHOICE = "Choose need, want, or unknown."
_DURABILITY_CHOICE = "Choose consumable, long-term, or unknown."
_FILTER = "That purchase history filter is not supported."


def remember_purchase(settings: Settings, purchase_id: str) -> tuple[MemoryEntry, bool]:
    canonical = parse_evidence_id(purchase_id) if isinstance(purchase_id, str) else None
    if canonical is None:
        raise PurchaseNotFound()
    purchase = get_purchase(settings, canonical)
    if purchase is None:
        raise PurchaseNotFound()
    if get_evidence(settings, purchase.evidence_id) is None:
        raise MemoryRejected(_EVIDENCE_UNAVAILABLE)
    existing = get_memory_for_purchase(settings, purchase.purchase_id)
    if existing is not None:
        return existing, False
    memory_id = new_memory_id()
    items = []
    for item in purchase.items:
        food, need_want, durability = classify_item_name(item.item_name)
        items.append(
            MemoryItem(
                memory_item_id=new_memory_item_id(),
                memory_id=memory_id,
                purchase_item_id=item.purchase_item_id,
                item_name=item.item_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
                line_order=item.line_order,
                food_classification=food,
                need_want_classification=need_want,
                durability_classification=durability,
            )
        )
    entry = MemoryEntry(
        memory_id=memory_id,
        purchase_id=purchase.purchase_id,
        evidence_id=purchase.evidence_id,
        merchant=purchase.merchant,
        purchase_date=purchase.purchase_date,
        purchase_time=purchase.purchase_time,
        created_at=memory_timestamp(),
        items=tuple(items),
    )
    stored = insert_memory(settings, entry)
    created = stored.memory_id == entry.memory_id
    return stored, created


def remember_from_request(settings: Settings, payload: object) -> tuple[MemoryEntry, bool]:
    if not isinstance(payload, dict):
        raise MemoryRejected(_UNREADABLE)
    purchase_id = payload.get("purchase_id")
    if not isinstance(purchase_id, str):
        raise MemoryRejected(_UNREADABLE)
    return remember_purchase(settings, purchase_id)


def read_memory(settings: Settings, memory_id: str) -> MemoryEntry | None:
    canonical = parse_evidence_id(memory_id) if isinstance(memory_id, str) else None
    if canonical is None:
        return None
    return get_memory(settings, canonical)


def read_memory_list(settings: Settings, memory_filter: str | None) -> list[MemoryEntry]:
    if memory_filter is not None and not isinstance(memory_filter, str):
        raise MemoryRejected(_FILTER)
    try:
        return list_memories(settings, memory_filter or None)
    except ValueError:
        raise MemoryRejected(_FILTER) from None


def correct_classification(
    settings: Settings,
    memory_id: str,
    memory_item_id: str,
    payload: object,
) -> MemoryEntry:
    canonical_memory = parse_evidence_id(memory_id) if isinstance(memory_id, str) else None
    canonical_item = parse_evidence_id(memory_item_id) if isinstance(memory_item_id, str) else None
    if canonical_memory is None or canonical_item is None:
        raise MemoryNotFound()
    current = get_memory(settings, canonical_memory)
    if current is None:
        raise MemoryNotFound()
    item = next((entry for entry in current.items if entry.memory_item_id == canonical_item), None)
    if item is None:
        raise MemoryNotFound()
    if not isinstance(payload, dict):
        raise MemoryRejected(_CLASSIFICATION_UNREADABLE)
    food = _choice(payload, "food_classification", item.food_classification, FOOD_VALUES, _FOOD_CHOICE)
    need_want = _choice(
        payload,
        "need_want_classification",
        item.need_want_classification,
        NEED_VALUES,
        _NEED_CHOICE,
    )
    durability = _choice(
        payload,
        "durability_classification",
        item.durability_classification,
        DURABILITY_VALUES,
        _DURABILITY_CHOICE,
    )
    changed = update_classifications(
        settings,
        current.memory_id,
        item.memory_item_id,
        food,
        need_want,
        durability,
    )
    if not changed:
        raise MemoryNotFound()
    updated = get_memory(settings, current.memory_id)
    if updated is None:
        raise MemoryNotFound()
    return updated


def _choice(
    payload: dict,
    key: str,
    current: str,
    allowed: frozenset[str],
    message: str,
) -> str:
    if key not in payload:
        return current
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        raise MemoryRejected(message)
    return value

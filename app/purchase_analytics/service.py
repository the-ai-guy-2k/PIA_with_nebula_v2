"""Read purchase history and return the same counts for the same records."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from app.config import Settings
from app.purchase_analytics.identity import analytics_key
from app.purchase_memory.models import MemoryEntry, MemoryItem
from app.purchase_memory.repository import list_memories

_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_FOOD = ("food", "non-food", "unknown")
_NEED = ("need", "want", "unknown")
_DURABILITY = ("consumable", "long-term", "unknown")


def build_analytics(settings: Settings) -> dict[str, object]:
    return summarize_memory(list_memories(settings, None))


def summarize_memory(entries: list[MemoryEntry]) -> dict[str, object]:
    if not entries:
        return _empty_report()
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    food_counts = {label: 0 for label in _FOOD}
    need_counts = {label: 0 for label in _NEED}
    durability_counts = {label: 0 for label in _DURABILITY}
    dated_purchases: list[date] = []
    merchant_purchases: dict[str | None, set[str]] = defaultdict(set)

    for entry in entries:
        purchase_day = _parse_date(entry.purchase_date)
        if purchase_day is not None:
            dated_purchases.append(purchase_day)
        merchant_purchases[entry.merchant].add(entry.purchase_id)
        for item in entry.items:
            _count(food_counts, item.food_classification, "unknown")
            _count(need_counts, item.need_want_classification, "unknown")
            _count(durability_counts, item.durability_classification, "unknown")
            key = analytics_key(item.item_name)
            if not key:
                continue
            groups[key].append(_source(entry, item, purchase_day))

    repeat_items = [_repeat_item(key, sources) for key, sources in groups.items()]
    repeat_items.sort(key=lambda item: (-int(item["occurrence_count"]), str(item["analytics_key"])))
    merchants = [
        {"merchant": merchant, "purchase_count": len(purchase_ids)}
        for merchant, purchase_ids in merchant_purchases.items()
    ]
    merchants.sort(
        key=lambda row: (
            -int(row["purchase_count"]),
            row["merchant"] is None,
            str(row["merchant"] or "").casefold(),
        )
    )
    return {
        "status": "ready",
        "summary": {
            "remembered_purchases": len(entries),
            "remembered_items": sum(len(entry.items) for entry in entries),
            "unique_items": len(repeat_items),
            "repeating_items": sum(1 for item in repeat_items if item["repeating"]),
            "earliest_purchase_date": min(dated_purchases).isoformat() if dated_purchases else None,
            "latest_purchase_date": max(dated_purchases).isoformat() if dated_purchases else None,
        },
        "repeat_items": repeat_items,
        "merchants": merchants,
        "classifications": {
            "food": food_counts,
            "need_want": need_counts,
            "durability": durability_counts,
        },
    }


def _repeat_item(key: str, sources: list[dict[str, object]]) -> dict[str, object]:
    by_purchase: dict[str, list[dict[str, object]]] = defaultdict(list)
    for source in sources:
        by_purchase[str(source["purchase_id"])].append(source)
    purchases = []
    for lines in by_purchase.values():
        lines.sort(key=lambda line: (int(line["line_order"]), str(line["memory_item_id"])))
        purchases.append(lines[0])
    purchases.sort(
        key=lambda purchase: (
            purchase["purchase_day"] is None,
            str(purchase["purchase_date"] or ""),
            str(purchase["created_at"]),
            str(purchase["purchase_id"]),
        )
    )
    dated = [purchase for purchase in purchases if purchase["purchase_day"] is not None]
    intervals = [
        (dated[index]["purchase_day"] - dated[index - 1]["purchase_day"]).days
        for index in range(1, len(dated))
    ]
    known_quantities = [
        quantity for source in sources if (quantity := _quantity(source["quantity"])) is not None
    ]
    display = max(
        sources,
        key=lambda source: (
            source["purchase_date"] is not None,
            str(source["purchase_date"] or ""),
            str(source["created_at"]),
            str(source["memory_item_id"]),
        ),
    )
    calculated = len(dated) >= 2
    return {
        "analytics_key": key,
        "item_name": display["item_name"],
        "occurrence_count": len(by_purchase),
        "repeating": len(by_purchase) > 1,
        "known_quantity": _plain(sum(known_quantities, Decimal("0"))) if known_quantities else None,
        "quantity_records_known": len(known_quantities),
        "quantity_records_unknown": len(sources) - len(known_quantities),
        "first_purchase_date": dated[0]["purchase_date"] if dated else None,
        "latest_purchase_date": dated[-1]["purchase_date"] if dated else None,
        "frequency_status": "calculated" if calculated else "insufficient_history",
        "average_interval_days": (
            _plain(Decimal(sum(intervals)) / Decimal(len(intervals))) if calculated else None
        ),
        "latest_interval_days": intervals[-1] if calculated else None,
        "merchants": _unique([purchase["merchant"] for purchase in purchases]),
        "classifications_seen": _labels(sources),
        "sources": [_public_source(source) for source in _sorted_sources(sources)],
    }


def _source(entry: MemoryEntry, item: MemoryItem, purchase_day: date | None) -> dict[str, object]:
    return {
        "memory_id": entry.memory_id,
        "purchase_id": entry.purchase_id,
        "memory_item_id": item.memory_item_id,
        "purchase_date": purchase_day.isoformat() if purchase_day is not None else None,
        "purchase_day": purchase_day,
        "created_at": entry.created_at,
        "merchant": entry.merchant,
        "item_name": item.item_name,
        "quantity": item.quantity,
        "line_total": item.line_total,
        "line_order": item.line_order,
        "food_classification": item.food_classification,
        "need_want_classification": item.need_want_classification,
        "durability_classification": item.durability_classification,
    }


def _public_source(source: dict[str, object]) -> dict[str, object]:
    return {
        "memory_id": source["memory_id"],
        "purchase_id": source["purchase_id"],
        "memory_item_id": source["memory_item_id"],
        "purchase_date": source["purchase_date"],
        "merchant": source["merchant"],
        "item_name": source["item_name"],
        "quantity": source["quantity"],
        "line_total": source["line_total"],
        "line_order": source["line_order"],
        "food_classification": source["food_classification"],
        "need_want_classification": source["need_want_classification"],
        "durability_classification": source["durability_classification"],
    }


def _sorted_sources(sources: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        sources,
        key=lambda source: (
            source["purchase_date"] is None,
            str(source["purchase_date"] or ""),
            str(source["purchase_id"]),
            int(source["line_order"]),
            str(source["memory_item_id"]),
        ),
    )


def _labels(sources: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: list[dict[str, object]] = []
    found: set[tuple[object, object, object]] = set()
    ordered = sorted(
        sources,
        key=lambda source: (
            str(source["food_classification"]),
            str(source["need_want_classification"]),
            str(source["durability_classification"]),
        ),
    )
    for source in ordered:
        labels = (
            source["food_classification"],
            source["need_want_classification"],
            source["durability_classification"],
        )
        if labels in found:
            continue
        found.add(labels)
        seen.append(
            {
                "food_classification": labels[0],
                "need_want_classification": labels[1],
                "durability_classification": labels[2],
            }
        )
    return seen


def _unique(values: list[object]) -> list[object]:
    found: list[object] = []
    for value in values:
        if value not in found:
            found.append(value)
    return found


def _empty_report() -> dict[str, object]:
    return {
        "status": "empty",
        "reason": "No remembered purchases yet.",
        "summary": {
            "remembered_purchases": 0,
            "remembered_items": 0,
            "unique_items": 0,
            "repeating_items": 0,
            "earliest_purchase_date": None,
            "latest_purchase_date": None,
        },
        "repeat_items": [],
        "merchants": [],
        "classifications": {
            "food": {label: 0 for label in _FOOD},
            "need_want": {label: 0 for label in _NEED},
            "durability": {label: 0 for label in _DURABILITY},
        },
    }


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _quantity(value: object) -> Decimal | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number


def _plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _count(bucket: dict[str, int], label: str, fallback: str) -> None:
    if label in bucket:
        bucket[label] += 1
    else:
        bucket[fallback] += 1

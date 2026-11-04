"""Minimal, read-only projections of existing Memory and Analytics results."""

from __future__ import annotations

import re

from app.ai_intelligence.models import GroundedInsight, QueryContext, SupportingFact
from app.ai_intelligence.routing import QueryRoute
from app.config import Settings
from app.purchase_analytics.identity import analytics_key
from app.purchase_analytics.service import summarize_memory
from app.purchase_memory.models import MemoryEntry, MemoryItem
from app.purchase_memory.repository import list_memories
from app.visual_recall.walmart import is_walmart_merchant

MAX_FACTS = 24
RECENT_PURCHASE_LIMIT = 5
_PRIVATE_TEXT = re.compile(
    r"[a-z]:[\\/]|(?:^|\s)~?/[^\s]+|\.\.[\\/]|https?://|file://"
    r"|\b[\w.-]+[\\/][\w./\\-]+\.(?:png|jpe?g|webp|gif|pdf|sqlite|db|txt|csv|env|pem)\b"
    r"|sk-[a-z0-9_-]{12,}|(?:password|secret|token|api[_ -]?key)\s*[:=]",
    re.IGNORECASE,
)
_RECALL_SCOPE = (
    "Latest five relevant remembered purchases, ordered by stored purchase date; "
    "undated purchases come last, ordered by memory creation. Up to 24 relevant item records. "
    "Missing purchase dates remain unknown; recent does not imply a freshness window."
)
_ANALYTICS_SCOPE = (
    "Selected deterministic analytics over confirmed purchases saved in Purchase Memory. "
    "Original case/spacing-only item identity and merchant grouping are preserved. "
    "Up to 24 relevant facts; no receipt images, OCR, identifiers, or unrelated line-item history."
)


def safe_label(value: str | None) -> bool:
    return value is None or (
        len(value) <= 180
        and not _PRIVATE_TEXT.search(value)
        and not any(ord(char) < 32 for char in value)
    )


def build_context(settings: Settings, route: QueryRoute) -> QueryContext:
    if route.kind == "unsupported":
        return QueryContext("unsupported", "unsupported", route.reason or "", "No context sent.")
    entries = list_memories(settings, None)
    if not entries:
        return QueryContext(
            route.kind, "empty", "There isn't enough confirmed purchase data yet. "
            "Confirm a receipt and save it in Purchase Memory before asking for recall.",
            "No remembered purchases; no context sent.",
        )
    if route.kind in {"recent", "food", "food_availability", "merchant_recall", "classification"}:
        return _recall(entries, route)
    report = summarize_memory(entries)
    if route.kind == "repeats":
        return _repeats(report, route)
    if route.kind == "merchants":
        facts = _merchant_facts(report)
        return _finish(route, "Your recorded merchant purchase counts:", facts, [
            "These counts describe stored purchase history, not every place you shop."
        ], _ANALYTICS_SCOPE)
    return _patterns(report, route)


def _matching_merchant(entry: MemoryEntry, subject: str | None) -> bool:
    if not subject:
        return True
    actual = analytics_key(entry.merchant or "")
    wanted = analytics_key(subject)
    # This selection does not merge or change the analytics merchant grouping.
    if wanted in {"walmart", "wal-mart", "wal mart"}:
        return is_walmart_merchant(entry.merchant)
    return actual == wanted


def _classification_matches(item: MemoryItem, label: str | None) -> bool:
    if label in {"need", "want"}:
        return item.need_want_classification == label
    if label in {"consumable", "long-term"}:
        return item.durability_classification == label
    return item.food_classification == label


def _recall(entries: list[MemoryEntry], route: QueryRoute) -> QueryContext:
    matching = [entry for entry in entries if _matching_merchant(entry, route.subject)]
    facts: list[tuple[str, str]] = []
    insights = ["These are confirmed purchase records, not a current household inventory."]
    scope = _RECALL_SCOPE
    if route.kind == "classification":
        report = summarize_memory(matching)
        group = (
            "need_want" if route.classification in {"need", "want"}
            else "durability" if route.classification in {"consumable", "long-term"} else "food"
        )
        count = report["classifications"][group][route.classification]
        facts.append(("classification", f"{route.classification}: {count} remembered item records."))
        scope = "Classification count across all matching stored purchases; examples from " + scope
        insights = ["These are current Purchase Memory classifications. Unknown labels are not inferred."]
        if count == 0:
            return _finish(
                route, f"No remembered item records are currently classified as {route.classification}.",
                facts, [], scope, status="empty",
            )
    relevant: list[tuple[MemoryEntry, list[MemoryItem]]] = []
    for entry in matching:
        if not safe_label(entry.merchant):
            continue
        items = [
            item for item in entry.items
            if safe_label(item.item_name)
            and (
                item.food_classification == "food" if route.kind in {"food", "food_availability"}
                else _classification_matches(item, route.classification) if route.kind == "classification"
                else True
            )
        ]
        if items:
            relevant.append((entry, items))
    for entry, items in relevant[:RECENT_PURCHASE_LIMIT]:
        for item in items:
            quantity = item.quantity if item.quantity and re.fullmatch(r"\d+(?:\.\d+)?", item.quantity) else "not recorded"
            label = (
                " Classification: food." if route.kind in {"food", "food_availability"}
                else f" Classification: {route.classification}." if route.kind == "classification" else ""
            )
            facts.append((
                "purchase",
                f"{item.item_name} — purchase date: {entry.purchase_date or 'unknown'}; "
                f"merchant: {entry.merchant or 'not recorded'}; quantity: {quantity}.{label}",
            ))
            if len(facts) >= MAX_FACTS:
                break
        if len(facts) >= MAX_FACTS:
            break
    header = "Your latest relevant stored purchase records:"
    if route.kind == "food_availability":
        header = (
            "Based on recent purchases, these items may still be available. "
            "Purchased does not mean still available. Consumption, expiry, and remaining "
            "quantities are unknown; these are purchased quantities, not amounts left."
        )
        insights = ["Only food-classified purchase records are shown. Current availability cannot be established."]
    elif route.kind == "food":
        header = "Your latest stored food-classified purchase records:"
    if not facts:
        header = "There are no matching remembered item records available for this question. " \
                 "Path-like or credential-like stored labels are excluded from AI context."
    return _finish(route, header, facts, insights, scope)


def _repeats(report: dict, route: QueryRoute) -> QueryContext:
    candidates = report["repeat_items"]
    if route.subject:
        wanted = analytics_key(route.subject)
        candidates = [item for item in candidates if analytics_key(item["item_name"]) == wanted]
    candidates = [item for item in candidates if item["repeating"] and safe_label(item["item_name"])]
    if not candidates:
        return QueryContext(
            route.kind, "insufficient_history",
            "There isn't enough repeat history for this question. No matching item occurs "
            "on more than one remembered purchase; a recurring pattern cannot be inferred.",
            _ANALYTICS_SCOPE,
        )
    facts = [_repeat_fact(item) for item in candidates[:12]]
    return _finish(route, "Repeated items in your stored purchase history:", facts, [
        "These repeats use the existing case/spacing-only item identity, not inferred product equivalence.",
        "Recorded recurrence is not a prediction of future need or a recommended shopping list.",
    ], _ANALYTICS_SCOPE)


def _repeat_fact(item: dict) -> tuple[str, str]:
    frequency = (
        f" Average interval across recorded dated purchases: {item['average_interval_days']} days."
        if item["frequency_status"] == "calculated"
        else " There is insufficient dated history to calculate an interval."
    )
    text = (
        f"{item['item_name']}: {item['occurrence_count']} remembered purchases. "
        f"First recorded purchase date: {item['first_purchase_date'] or 'unknown'}; "
        f"latest recorded purchase date: {item['latest_purchase_date'] or 'unknown'}.{frequency}"
    )
    if item["known_quantity"] is not None:
        text += (
            f" Known purchased quantity: {item['known_quantity']}; "
            f"quantity unknown on {item['quantity_records_unknown']} item records. "
            "Purchased quantity is not quantity remaining."
        )
    return "repeat", text


def _merchant_facts(report: dict) -> list[tuple[str, str]]:
    return [
        ("merchant", f"{row['merchant'] or 'Merchant not recorded'}: {row['purchase_count']} remembered purchases.")
        for row in report["merchants"][:12] if safe_label(row["merchant"])
    ]


def _patterns(report: dict, route: QueryRoute) -> QueryContext:
    summary = report["summary"]
    if summary["remembered_purchases"] < 2:
        return QueryContext(
            route.kind, "insufficient_history",
            "There isn't enough purchase history to interpret a pattern. At least two "
            "remembered purchases are needed; one purchase is not an established trend.",
            _ANALYTICS_SCOPE,
        )
    facts = [(
        "summary", f"Stored history: {summary['remembered_purchases']} remembered purchases; "
        f"{summary['remembered_items']} item records; {summary['unique_items']} normalized "
        f"item identities; {summary['repeating_items']} repeating item identities."
    )]
    facts.extend(_repeat_fact(item) for item in report["repeat_items"][:6] if item["repeating"] and safe_label(item["item_name"]))
    facts.extend(_merchant_facts(report)[:5])
    for group, counts in report["classifications"].items():
        facts.append(("classification", f"{group.replace('_', '/')} item records: " + "; ".join(
            f"{label}: {count}" for label, count in counts.items()
        ) + "."))
    insights = [
        "These observations describe confirmed stored purchases, not future needs or current inventory.",
        "Unknown classifications limit what can be inferred; no unknown label is filled in by AI.",
    ]
    if summary["repeating_items"]:
        insights.append("Some normalized items recur across stored purchases; different product names are not merged.")
    if summary["remembered_purchases"] < 5:
        insights.append("This is a small stored history. Observations are tentative rather than established long-term trends.")
    return _finish(route, "Patterns supported by your stored deterministic analytics:", facts, insights, _ANALYTICS_SCOPE)


def _finish(
    route: QueryRoute, header: str, facts: list[tuple[str, str]], insights: list[str],
    scope: str, status: str = "ready",
) -> QueryContext:
    supported = tuple(
        SupportingFact(f"F{index}", kind, text)
        for index, (kind, text) in enumerate(facts[:MAX_FACTS], 1)
    )
    allowed = tuple(GroundedInsight(f"I{index}", text) for index, text in enumerate(insights, 1))
    return QueryContext(
        route.kind, status if supported else "empty", header, scope, supported, allowed,
        tuple(fact.fact_id for fact in supported[:3]),
    )
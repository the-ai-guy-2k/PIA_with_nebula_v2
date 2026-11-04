"""Attach pictures to Walmart food history without changing that history."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.purchase_memory.repository import list_memories
from app.visual_recall.models import VisualEnrichment
from app.visual_recall.provider import CatalogImageProvider, ProviderMatch
from app.visual_recall.repository import (
    enrichment_timestamp,
    get_enrichment,
    get_enrichment_for_item,
    new_enrichment_id,
    save_enrichment,
)
from app.visual_recall.walmart import is_walmart_merchant

_VIEWS = {"all", "exact", "representative", "none"}
_FILTER_EMPTY = {
    "exact": "No exact product image is in this Walmart food history.",
    "representative": "No representative image is in this Walmart food history.",
    "none": "No text-only Walmart food item is in this purchase history.",
}
_STORED_TYPES = {"exact": "exact", "representative": "representative", "none": "none", "ambiguous": "none"}


def default_provider() -> CatalogImageProvider:
    return CatalogImageProvider(Path(__file__).resolve().parent / "catalog")


def build_visual_recall(settings: Settings, provider: object, view: str | None) -> dict[str, object]:
    selected = view or "all"
    if selected not in _VIEWS:
        raise ValueError(selected)
    items = []
    for entry in list_memories(settings, None):
        if not is_walmart_merchant(entry.merchant):
            continue
        for item in entry.items:
            if item.food_classification != "food":
                continue
            enrichment = _current_enrichment(settings, provider, entry.memory_id, entry.purchase_id, entry.merchant, item)
            image_available = _image_available(provider, enrichment)
            display = enrichment.match_type if enrichment.match_type in {"exact", "representative"} and image_available else "text-only"
            items.append(
                {
                    "enrichment_id": enrichment.enrichment_id,
                    "memory_item_id": item.memory_item_id,
                    "memory_id": entry.memory_id,
                    "purchase_id": entry.purchase_id,
                    "merchant": entry.merchant,
                    "confirmed_item_name": item.item_name,
                    "purchase_date": entry.purchase_date,
                    "match_type": enrichment.match_type,
                    "display": display,
                    "image_available": image_available,
                    "provider": enrichment.provider,
                    "source_reference": enrichment.source_reference,
                }
            )
    dated = [item for item in items if item["purchase_date"]]
    undated = [item for item in items if not item["purchase_date"]]
    dated.sort(key=lambda item: str(item["confirmed_item_name"]).casefold())
    dated.sort(key=lambda item: str(item["purchase_date"]), reverse=True)
    undated.sort(key=lambda item: str(item["confirmed_item_name"]).casefold())
    items = dated + undated
    if selected == "none":
        visible = [item for item in items if item["display"] == "text-only"]
    elif selected == "all":
        visible = items
    else:
        visible = [item for item in items if item["display"] == selected]
    if not items:
        return {
            "status": "empty",
            "reason": "No Walmart food purchases are in purchase history.",
            "items": [],
        }
    if not visible:
        return {"status": "ready", "reason": _FILTER_EMPTY[selected], "items": []}
    return {"status": "ready", "reason": None, "items": visible}


def read_enrichment_image(settings: Settings, provider: object, enrichment_id: str) -> bytes | None:
    from app.receipt_intake.models import parse_evidence_id

    canonical = parse_evidence_id(enrichment_id) if isinstance(enrichment_id, str) else None
    if canonical is None:
        return None
    enrichment = get_enrichment(settings, canonical)
    if enrichment is None or enrichment.match_type not in {"exact", "representative"}:
        return None
    resolver = getattr(provider, "resolve", None)
    if resolver is None:
        return None
    path = resolver(enrichment.image_reference)
    if path is None:
        return None
    return path.read_bytes()


def _current_enrichment(settings: Settings, provider: object, memory_id: str, purchase_id: str, merchant: str | None, item) -> VisualEnrichment:
    existing = get_enrichment_for_item(settings, item.memory_item_id)
    if existing is not None and existing.match_type != "error":
        return existing
    match = _lookup(provider, item.item_name)
    now = enrichment_timestamp()
    enrichment = VisualEnrichment(
        enrichment_id=existing.enrichment_id if existing is not None else new_enrichment_id(),
        memory_item_id=item.memory_item_id,
        memory_id=memory_id,
        purchase_id=purchase_id,
        merchant=merchant,
        confirmed_item_name=item.item_name,
        match_type=match.match_type if match.match_type in {"exact", "representative", "none", "error"} else "none",
        image_reference=match.image_file if match.match_type in {"exact", "representative"} else None,
        source_reference=match.source_reference if match.match_type in {"exact", "representative"} else None,
        provider=match.provider_name,
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
    )
    return save_enrichment(settings, enrichment)


def _lookup(provider: object, item_name: str) -> ProviderMatch:
    try:
        match = provider.lookup(item_name)
    except Exception:
        return ProviderMatch("error", None, None, getattr(provider, "name", "provider"))
    if not isinstance(match, ProviderMatch):
        return ProviderMatch("error", None, None, getattr(provider, "name", "provider"))
    if match.match_type == "ambiguous":
        return ProviderMatch("none", None, None, match.provider_name)
    if match.match_type not in _STORED_TYPES and match.match_type != "error":
        return ProviderMatch("none", None, None, match.provider_name)
    stored = _STORED_TYPES.get(match.match_type, match.match_type)
    if stored not in {"exact", "representative"}:
        return ProviderMatch(stored, None, None, match.provider_name)
    return ProviderMatch(stored, match.image_file, match.source_reference, match.provider_name)


def _image_available(provider: object, enrichment: VisualEnrichment) -> bool:
    if enrichment.match_type not in {"exact", "representative"} or not enrichment.image_reference:
        return False
    resolver = getattr(provider, "resolve", None)
    if resolver is None:
        return False
    return resolver(enrichment.image_reference) is not None

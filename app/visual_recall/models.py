"""Image association metadata. This is not purchase truth."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisualEnrichment:
    enrichment_id: str
    memory_item_id: str
    memory_id: str
    purchase_id: str
    merchant: str | None
    confirmed_item_name: str
    match_type: str
    image_reference: str | None
    source_reference: str | None
    provider: str
    created_at: str
    updated_at: str

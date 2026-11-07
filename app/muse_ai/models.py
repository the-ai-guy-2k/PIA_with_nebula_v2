"""Data shapes for the Muse AI extraction loop."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MuseLine:
    """One receipt line as Muse read it."""

    name: str
    quantity: str  # "1" when the receipt shows no quantity
    unit_price: str | None  # "6.97" — None when the receipt shows no unit price
    line_total: str  # "6.97"
    raw_text: str  # the receipt line as printed, for audit
    confidence: str  # "high" | "medium" | "low"
    line_total_ok: bool = True  # False when qty x price != line_total (flagged, not fixed)


@dataclass(frozen=True)
class MuseExtraction:
    """A validated Muse extraction, ready to become an unconfirmed candidate."""

    merchant: str | None
    purchase_date: str | None  # ISO YYYY-MM-DD when the receipt shows a date
    purchase_time: str | None
    subtotal: str | None
    tax: str | None
    total: str | None
    lines: tuple[MuseLine, ...]
    lines_sum: str  # sum of line_total values, "0.00" when no lines
    totals_reconciled: bool  # lines sum vs subtotal, subtotal+tax vs total
    total_mismatch: bool  # True when a stated total disagrees with the arithmetic
    flags: tuple[str, ...] = ()  # plain-language flags for Review, e.g. total mismatch


@dataclass(frozen=True)
class QueueRecord:
    evidence_id: str
    status: str  # queued | processing | done | done_with_mismatch | failed
    queued_at: str
    ocr_text: str = ""
    error: str | None = None
    extraction_id: str | None = None
    updated_at: str = ""

    def to_public_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "status": self.status,
            "queued_at": self.queued_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "extraction_id": self.extraction_id,
            "source": "muse_ai",
        }


@dataclass(frozen=True)
class MuseAudit:
    extraction_id: str
    evidence_id: str
    source: str = "muse_ai"
    model: str = "muse"
    totals_reconciled: bool = False
    lines_sum: str = "0.00"
    total_mismatch: bool = False
    confidence: dict[str, str] = field(default_factory=dict)  # line order -> confidence
    created_at: str = ""

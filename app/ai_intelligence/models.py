"""Small derived query result. No persistence and no purchase-schema changes."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SupportingFact:
    fact_id: str
    kind: str
    text: str


@dataclass(frozen=True)
class GroundedInsight:
    insight_id: str
    text: str


@dataclass(frozen=True)
class QueryContext:
    query_type: str
    status: str
    header: str
    scope: str
    facts: tuple[SupportingFact, ...] = ()
    insights: tuple[GroundedInsight, ...] = ()
    required_refs: tuple[str, ...] = ()

    def for_provider(self) -> dict[str, object]:
        # Deliberate projection: no original question, DB IDs, paths, or OCR.
        return {
            "intent": self.query_type,
            "scope": self.scope,
            "facts": [asdict(fact) for fact in self.facts],
            "allowed_interpretations": [asdict(insight) for insight in self.insights],
        }


@dataclass(frozen=True)
class AIQueryResult:
    query_id: str
    question: str
    query_type: str
    status: str
    answer: str
    answer_source: str
    generated_at: str
    provider: str | None
    model: str | None
    supporting_facts: tuple[SupportingFact, ...]
    grounded_fact_count: int
    degraded: bool
    degraded_reason: str | None
    context_scope: str

    def to_public_dict(self) -> dict[str, object]:
        return asdict(self)
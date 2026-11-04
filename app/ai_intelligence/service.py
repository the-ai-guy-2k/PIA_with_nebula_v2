"""Read-only intelligence: deterministic context, one AI selection, safe rendering."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from app.ai_intelligence.context import build_context
from app.ai_intelligence.models import AIQueryResult, QueryContext, SupportingFact
from app.ai_intelligence.provider import AIProvider, ProviderOutputError, ProviderUnavailable
from app.ai_intelligence.routing import route_question
from app.config import Settings

logger = logging.getLogger("purchase_intelligence.ai")
PROVIDER_TIMEOUT_SECONDS = 60
MAX_CONTEXT_BYTES = 16_384


async def ask_history(settings: Settings, question: str, provider: AIProvider) -> AIQueryResult:
    context = await asyncio.to_thread(build_context, settings, route_question(question))
    if context.status != "ready":
        return _result(question, context, context.header, context.facts, status=context.status)
    projected = context.for_provider()
    if len(json.dumps(projected, ensure_ascii=False).encode("utf-8")) > MAX_CONTEXT_BYTES:
        return _fallback(question, context, provider, "context_limit")
    try:
        selection = await asyncio.wait_for(
            provider.interpret(projected), timeout=PROVIDER_TIMEOUT_SECONDS
        )
        facts, insights = _validate_selection(context, selection)
    except (TimeoutError, asyncio.TimeoutError):
        return _fallback(question, context, provider, "timeout")
    except ProviderUnavailable:
        return _fallback(question, context, provider, "provider_unavailable")
    except ProviderOutputError:
        return _fallback(question, context, provider, "unusable_output")
    except Exception:
        # Never return/log exception text: providers can embed URLs or credentials.
        return _fallback(question, context, provider, "provider_failed")
    answer = _render(context.header, facts, insights)
    logger.info("ai finished intent=%s facts=%s degraded=false", context.query_type, len(facts))
    return _result(
        question, context, answer, facts, status="ready", source="ai_grounded",
        provider=provider.name, model=provider.model,
    )


def _validate_selection(
    context: QueryContext, selection: object,
) -> tuple[tuple[SupportingFact, ...], tuple[str, ...]]:
    if not isinstance(selection, dict) or set(selection) != {"fact_refs", "insight_refs"}:
        raise ProviderOutputError("Unexpected response fields.")
    fact_refs, insight_refs = selection["fact_refs"], selection["insight_refs"]
    if (
        not isinstance(fact_refs, list) or not 1 <= len(fact_refs) <= 12
        or not isinstance(insight_refs, list) or len(insight_refs) > 3
        or any(not isinstance(ref, str) for ref in fact_refs + insight_refs)
        or len(set(fact_refs)) != len(fact_refs) or len(set(insight_refs)) != len(insight_refs)
    ):
        raise ProviderOutputError("Invalid response references.")
    known_facts = {fact.fact_id: fact for fact in context.facts}
    known_insights = {insight.insight_id: insight.text for insight in context.insights}
    if any(ref not in known_facts for ref in fact_refs) or any(ref not in known_insights for ref in insight_refs):
        raise ProviderOutputError("An unsupported factual claim was attempted.")
    # Preserve essential context regardless of model selection.
    chosen = list(dict.fromkeys([*context.required_refs, *fact_refs]))[:12]
    return tuple(known_facts[ref] for ref in chosen), tuple(known_insights[ref] for ref in insight_refs)


def _render(header: str, facts: tuple[SupportingFact, ...], insights: tuple[str, ...] = ()) -> str:
    parts = [header]
    if insights:
        parts.append(" ".join(insights))
    if facts:
        parts.append("\n".join(f"- {fact.text}" for fact in facts))
    return "\n\n".join(parts)


def _fallback(
    question: str, context: QueryContext, provider: AIProvider, reason: str,
) -> AIQueryResult:
    facts = context.facts[:12]
    message = "AI interpretation is unavailable. Showing deterministic stored purchase facts instead."
    logger.warning("ai degraded intent=%s reason=%s facts=%s", context.query_type, reason, len(facts))
    return _result(
        question, context, _render(message + "\n\n" + context.header, facts), facts,
        status="degraded", source="deterministic_fallback", provider=provider.name,
        model=provider.model, degraded=True, degraded_reason=reason,
    )


def _result(
    question: str, context: QueryContext, answer: str, facts: tuple[SupportingFact, ...],
    *, status: str, source: str = "deterministic", provider: str | None = None,
    model: str | None = None, degraded: bool = False, degraded_reason: str | None = None,
) -> AIQueryResult:
    return AIQueryResult(
        str(uuid.uuid4()), question, context.query_type, status, answer, source,
        datetime.now(timezone.utc).isoformat(), provider, model, facts, len(facts),
        degraded, degraded_reason, context.scope,
    )
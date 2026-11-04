"""Bounded deterministic intent routing; never ask an LLM to route raw input."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_QUESTION_CHARS = 500


class QuestionRejected(ValueError):
    pass


@dataclass(frozen=True)
class QueryRoute:
    kind: str
    subject: str | None = None
    classification: str | None = None
    reason: str | None = None


def parse_question(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"question"}:
        raise QuestionRejected("Provide a JSON object containing only a question.")
    question = payload["question"]
    if not isinstance(question, str) or not question.strip():
        raise QuestionRejected("Enter a question about your confirmed purchase history.")
    if len(question) > MAX_QUESTION_CHARS:
        raise QuestionRejected(f"Keep your question within {MAX_QUESTION_CHARS} characters.")
    if any(ord(char) < 32 and char not in "\n\t\r" for char in question):
        raise QuestionRejected("The question contains unsupported characters.")
    return question.strip()


def route_question(question: str) -> QueryRoute:
    text = " ".join(question.casefold().split()).rstrip("?.!")
    if re.search(r"\b(delete|erase|edit|modify|update|reclassify|confirm|send|order)\b", text) or re.match(
        r"^(?:please |can you |could you )?(?:add|create|buy|purchase|change|remove)\b", text
    ):
        return QueryRoute(
            "unsupported", reason="Ask history is read-only. It cannot change purchases, "
            "classifications, or memory, make shopping lists, buy products, or send messages."
        )
    if re.search(r"\b(expir\w*|spoiled|freshness|pantry|fridge|freezer|inventory|in stock)\b", text):
        return QueryRoute(
            "unsupported", reason="Current inventory, consumption, and expiry are not tracked. "
            "Ask what food you purchased or what might still be available instead."
        )
    if re.search(r"\b(recipe|calories|nutrition|medical|predict|prediction|will i|should i buy|need to buy|next week)\b", text):
        return QueryRoute("unsupported", reason="This version recalls stored purchases and "
                          "interprets recorded patterns; it cannot predict needs or give dietary advice.")
    if re.search(r"\b(last week|last month|last year|this month|today|yesterday|last \d+ days?)\b|\d{4}-\d{2}-\d{2}", text):
        return QueryRoute("unsupported", reason="Custom calendar/date-range queries are not "
                          "supported here. Recent recall shows the latest five relevant stored purchases.")
    merchant = re.search(r"\b(?:at|from)\s+(.+?)(?:\s+recently)?$", text)
    merchant_subject = merchant.group(1) if merchant else None
    if re.search(r"\b(food|eat|grocer\w*)\b", text) and re.search(
        r"\b(might|available|have to eat|do i have|can i eat)\b", text
    ):
        return QueryRoute("food_availability", subject=merchant_subject)
    if re.search(r"\b(need|needs|want|wants|consumable|consumables|long-term|non-food)\b", text):
        match = re.search(r"\b(needs?|wants?|consumables?|long-term|non-food)\b", text)
        label = match.group(1)
        label = {"needs": "need", "wants": "want", "consumables": "consumable"}.get(label, label)
        return QueryRoute("classification", subject=merchant_subject, classification=label)
    if re.search(r"\b(food|grocer\w*)\b", text):
        return QueryRoute("food", subject=merchant_subject)
    if re.search(r"\b(often|repeat\w*|frequen\w*|how many times|how often)\b", text):
        if merchant_subject:
            return QueryRoute("unsupported", reason="Merchant-filtered repeat queries are not "
                              "supported here. Ask what you bought at that merchant instead.")
        item = re.search(r"\b(?:how often do i buy|how many times (?:have i bought|did i buy))\s+(.+)$", text)
        return QueryRoute("repeats", subject=item.group(1) if item else None)
    if re.search(r"\b(pattern\w*|trend\w*|insight\w*|interpret\w*|habits)\b", text):
        if merchant_subject:
            return QueryRoute("unsupported", reason="Merchant-filtered pattern queries are not "
                              "supported here. Ask what you bought at that merchant instead.")
        return QueryRoute("patterns")
    if re.search(r"\b(where|which)\b.*\b(shop|store|merchant)", text) or text in {
        "merchant intelligence", "merchant patterns", "where do i shop most"
    }:
        return QueryRoute("merchants")
    if merchant_subject and re.search(r"\b(buy|bought|purchase\w*)\b", text):
        return QueryRoute("merchant_recall", subject=merchant_subject)
    if re.fullmatch(
        r"what (?:did i (?:buy|purchase)|have i (?:bought|purchased))(?: recently)?"
        r"|(?:show (?:my )?)?(?:recent|latest) (?:purchases|purchase history)"
        r"|what are my recent purchases", text,
    ):
        return QueryRoute("recent")
    return QueryRoute("unsupported", reason="Ask about recent purchases, food purchases, "
                      "repeated items, merchants, needs/wants/consumables, or recorded patterns.")
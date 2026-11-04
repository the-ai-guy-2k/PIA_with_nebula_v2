"""ACI-007: grounded queries, privacy, read-only behavior, cost, and degradation."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai_intelligence.provider import (
    MAX_COMPLETION_TOKENS, ProviderOutputError, ProviderUnavailable, ReplitAIProvider,
)
from app.main import create_app
from app.ai_intelligence.routing import route_question
from app.ai_intelligence.context import safe_label
from tests.test_purchase_analytics import remember
from tests.test_receipt_extraction import blank_png, upload_png


class RecordingProvider:
    name = "test-grounded-provider"
    model = "test-only"

    def __init__(self):
        self.calls = []
        self.error = None
        self.selection = None
        self.mutate = False

    async def interpret(self, context):
        self.calls.append(copy.deepcopy(context))
        if self.error:
            raise self.error
        if self.mutate:
            context["facts"][0]["text"] = "Invented inventory: 99 dragonfruit remaining."
        if self.selection is not None:
            return self.selection
        return {
            "fact_refs": [fact["fact_id"] for fact in context["facts"][:8]],
            "insight_refs": [context["allowed_interpretations"][0]["insight_id"]],
        }


@pytest.fixture
def ai_pair(settings):
    provider = RecordingProvider()
    return TestClient(create_app(settings, ai_provider=provider)), provider


@pytest.fixture
def seeded(ai_pair, settings):
    client, provider = ai_pair
    evidence = upload_png(client, blank_png())
    for merchant, day, items in [
        ("Walmart", "2026-10-01", [
            {"name": "Milk Gallon", "quantity": "2"}, {"name": "Bread Loaf"},
            {"name": "HDMI Cable"},
        ]),
        ("Walmart Supercenter", "2026-09-20", [
            {"name": "Milk Gallon"}, {"name": "Eggs Large", "quantity": "1"},
        ]),
        ("Corner Shop", "2026-09-10", [{"name": "Notebook"}]),
    ]:
        entry = remember(client, settings, evidence["evidence_id"], merchant, day, items)
        for item in entry["items"]:
            food = item["item_name"] not in {"HDMI Cable", "Notebook"}
            response = client.patch(
                f"/api/memory/{entry['memory_id']}/items/{item['memory_item_id']}",
                json={
                    "food_classification": "food" if food else "non-food",
                    "need_want_classification": "need" if food else "want",
                    "durability_classification": "consumable" if food else "long-term",
                },
            )
            assert response.status_code == 200
    assert provider.calls == []
    return client, provider


REQUIRED_QUERIES = [
    ("What did I buy recently?", "recent", "Milk Gallon"),
    ("What food did I buy recently?", "food", "Bread Loaf"),
    ("What do I buy often?", "repeats", "2 remembered purchases"),
    ("What items repeat?", "repeats", "11 days"),
    ("Where do I shop most?", "merchants", "Walmart"),
    ("What have I bought at Walmart?", "merchant_recall", "Milk Gallon"),
    ("What needs have I bought?", "classification", "need: 4"),
    ("What wants have I bought?", "classification", "want: 2"),
    ("What consumables do I buy?", "classification", "consumable: 4"),
    ("What patterns are showing up?", "patterns", "3 remembered purchases"),
    ("What food might I have to eat?", "food_availability", "may still be available"),
    ("What food do I have?", "food_availability", "Purchased does not mean still available"),
]


@pytest.mark.parametrize("question,kind,expected", REQUIRED_QUERIES)
def test_required_grounded_queries(seeded, question, kind, expected):
    client, provider = seeded
    response = client.post("/api/ask", json={"question": question})
    body = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "ready", body
    assert body["query_type"] == kind
    assert body["answer_source"] == "ai_grounded"
    assert expected in body["answer"]
    assert len(provider.calls) == 1
    allowed = {fact["fact_id"]: fact for fact in provider.calls[0]["facts"]}
    assert all(fact == allowed[fact["fact_id"]] for fact in body["supporting_facts"])
    assert body["grounded_fact_count"] == len(body["supporting_facts"])
    assert body["query_id"] and body["generated_at"]


def test_food_and_merchant_context_exclude_unrelated_history(seeded):
    client, provider = seeded
    for question in ["What food did I buy recently?", "What have I bought at Walmart?"]:
        body = client.post("/api/ask", json={"question": question}).json()
        sent = json.dumps(provider.calls[-1])
        assert "Notebook" not in sent
        assert "Corner Shop" not in sent
        if body["query_type"] == "food":
            assert "HDMI Cable" not in sent
        for forbidden in ["evidence_id", "purchase_id", "memory_id", "raw_line_text",
                          "storage_reference", "original_filename", "receipt-evidence/files",
                          "/home/", "image", "ocr"]:
            assert forbidden not in sent.lower()
        assert not re.search(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", sent)


def test_raw_question_and_private_labels_are_not_sent(seeded, settings):
    client, provider = seeded
    evidence = upload_png(client, blank_png())
    entry = remember(client, settings, evidence["evidence_id"], "Walmart", None, [
        {"name": r"C:\private\food.txt"}, {"name": "secret=fixture-only-value"},
    ])
    for item in entry["items"]:
        client.patch(f"/api/memory/{entry['memory_id']}/items/{item['memory_item_id']}", json={
            "food_classification": "food", "need_want_classification": "unknown",
            "durability_classification": "unknown",
        })
    question = "What food did I buy recently? SECRET=question-fixture-value"
    response = client.post("/api/ask", json={"question": question})
    assert response.status_code == 200
    sent = json.dumps(provider.calls[-1])
    assert "question-fixture-value" not in sent
    assert "fixture-only-value" not in sent
    assert "private" not in sent
    assert "question" not in provider.calls[-1]

@pytest.mark.parametrize("label", [
    "/root/.ssh/id_rsa", "~/private/photo.png", "folder/receipt.jpg",
    r"C:\Users\private\receipt.png", "https://example.test/receipt.png",
])
def test_path_like_stored_labels_are_excluded(label):
    assert not safe_label(label)
    assert safe_label("Milk Gallon") and safe_label("50/50 Blend")


def _snapshot(settings):
    return {
        str(path.relative_to(settings.data_dir.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in settings.data_dir.parent.rglob("*") if path.is_file()
    }


def test_ai_never_changes_truth_analytics_or_visual_associations(seeded, settings):
    client, provider = seeded
    client.get("/api/visual-recall")
    analytics_before = client.get("/api/analytics").json()
    before = _snapshot(settings)
    for question, _, _ in REQUIRED_QUERIES:
        assert client.post("/api/ask", json={"question": question}).json()["status"] == "ready"
    assert _snapshot(settings) == before
    assert client.get("/api/analytics").json() == analytics_before
    assert len(provider.calls) == len(REQUIRED_QUERIES)


def test_no_ai_on_startup_loads_or_existing_operations(seeded):
    client, provider = seeded
    for route in ["/", "/ask", "/memory", "/analytics", "/food-recall",
                  "/api/memory", "/api/analytics", "/api/visual-recall"]:
        assert client.get(route).status_code == 200
    assert client.get("/api/ask").status_code == 405
    assert provider.calls == []


@pytest.mark.parametrize("payload", [
    {"question": ""}, {"question": "   "}, {"question": None}, {"question": 1},
    {"question": "x" * 501}, {"question": "test", "provider": "other"},
    [], {}, {"question": "bad\x00value"},
])
def test_invalid_questions_never_call_ai(ai_pair, payload):
    client, provider = ai_pair
    assert client.post("/api/ask", json=payload).status_code == 400
    assert provider.calls == []


def test_malformed_and_oversized_requests_never_call_ai(ai_pair):
    client, provider = ai_pair
    for payload in [b"{", b"\xff", b" " * 4097]:
        response = client.post("/api/ask", content=payload, headers={"content-type": "application/json"})
        assert response.status_code == 400
    assert client.post("/api/ask?model=other", json={"question": "What did I buy recently?"}).status_code == 400
    assert provider.calls == []


@pytest.mark.parametrize("question", [
    "Delete all purchases", "Update my classifications", "Create a shopping list",
    "Send a message", "Buy milk", "What is in my fridge?", "Is my food expired?",
    "Give me a recipe", "What will I buy next week?", "What did I buy last month?",
    "Who won the football game?",
    "How often do I buy things at Walmart?",
    "What patterns are showing up at Walmart?",
    "What kind of tea did I buy?",
])
def test_unsupported_questions_are_honest_and_free(seeded, question):
    client, provider = seeded
    body = client.post("/api/ask", json={"question": question}).json()
    assert body["status"] == "unsupported"
    assert body["answer_source"] == "deterministic"
    assert body["supporting_facts"] == []
    assert provider.calls == []


def test_no_history_no_matching_data_and_insufficient_history_avoid_ai(ai_pair, settings):
    client, provider = ai_pair
    assert client.post("/api/ask", json={"question": "What did I buy recently?"}).json()["status"] == "empty"
    evidence = upload_png(client, blank_png())
    remember(client, settings, evidence["evidence_id"], None, None, [
        {"name": "HDMI Cable"},
    ])
    for question in ["What patterns are showing up?", "What items repeat?"]:
        assert client.post("/api/ask", json={"question": question}).json()["status"] == "insufficient_history"
    for question in ["What food did I buy recently?", "What have I bought at Walmart?", "What needs have I bought?"]:
        assert client.post("/api/ask", json={"question": question}).json()["status"] == "empty"
    assert provider.calls == []


def test_unknown_dates_and_quantity_are_not_inferred(ai_pair, settings):
    client, provider = ai_pair
    evidence = upload_png(client, blank_png())
    for _ in range(2):
        remember(client, settings, evidence["evidence_id"], None, None, [{"name": "Milk Gallon"}])
    body = client.post("/api/ask", json={"question": "What items repeat?"}).json()
    assert "2 remembered purchases" in body["answer"]
    assert "insufficient dated history" in body["answer"]
    assert "unknown" in body["answer"]
    assert "Average interval" not in body["answer"]
    recalled = client.post("/api/ask", json={"question": "What did I buy recently?"}).json()
    assert "purchase date: unknown" in recalled["answer"]
    assert "quantity: not recorded" in recalled["answer"]


@pytest.mark.parametrize("error,reason", [
    (TimeoutError("private exception fixture"), "timeout"),
    (ProviderUnavailable("private exception fixture"), "provider_unavailable"),
    (ProviderOutputError("private exception fixture"), "unusable_output"),
    (RuntimeError("private exception fixture"), "provider_failed"),
])
def test_provider_failure_returns_safe_deterministic_fallback(seeded, error, reason, caplog):
    client, provider = seeded
    provider.error = error
    body = client.post("/api/ask", json={"question": "What items repeat?"}).json()
    assert body["status"] == "degraded"
    assert body["answer_source"] == "deterministic_fallback"
    assert body["degraded"] and body["degraded_reason"] == reason
    assert "Milk Gallon: 2 remembered purchases" in body["answer"]
    assert "private exception fixture" not in json.dumps(body) + caplog.text
    assert len(provider.calls) == 1
    assert client.get("/api/analytics").status_code == 200
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("selection", [
    {}, {"fact_refs": [], "insight_refs": []},
    {"fact_refs": ["F999"], "insight_refs": []},
    {"fact_refs": ["F1"], "insight_refs": ["I999"]},
    {"fact_refs": ["F1", "F1"], "insight_refs": []},
    {"fact_refs": [1], "insight_refs": []},
    {"fact_refs": ["F1"], "insight_refs": [], "answer": "99 invented dragonfruit in stock"},
])
def test_unsupported_model_claims_are_not_rendered(seeded, selection):
    client, provider = seeded
    provider.selection = selection
    body = client.post("/api/ask", json={"question": "What did I buy recently?"}).json()
    assert body["status"] == "degraded"
    assert body["degraded_reason"] == "unusable_output"
    assert "dragonfruit" not in body["answer"]
    assert "F999" not in json.dumps(body)


def test_provider_cannot_mutate_fact_text(seeded):
    client, provider = seeded
    provider.mutate = True
    body = client.post("/api/ask", json={"question": "What did I buy recently?"}).json()
    assert body["status"] == "ready"
    assert "Invented inventory" not in body["answer"]
    assert "dragonfruit" not in json.dumps(body)


def test_context_is_bounded_and_recent_selection_is_explicit(ai_pair, settings):
    client, provider = ai_pair
    evidence = upload_png(client, blank_png())
    for day in range(1, 9):
        remember(client, settings, evidence["evidence_id"], "Walmart", f"2026-09-{day:02d}", [
            {"name": f"Milk product {day}-{index}", "quantity": "1"} for index in range(10)
        ])
    body = client.post("/api/ask", json={"question": "What did I buy recently?"}).json()
    sent = provider.calls[0]
    assert len(sent["facts"]) == 24
    assert len(json.dumps(sent).encode()) < 16_384
    assert "2026-09-01" not in json.dumps(sent)
    assert "Latest five" in body["context_scope"]


def test_walmart_variant_selection_uses_existing_semantics(ai_pair, settings):
    client, provider = ai_pair
    evidence = upload_png(client, blank_png())
    for merchant in ["WAL-MART #123", "Super Walmart", "Not Walmart"]:
        remember(client, settings, evidence["evidence_id"], merchant, None, [{"name": merchant + " item"}])
    body = client.post("/api/ask", json={"question": "What have I bought at Walmart?"}).json()
    assert "WAL-MART #123 item" in body["answer"]
    assert "Super Walmart" not in body["answer"]
    assert "Not Walmart" not in body["answer"]


def test_additive_page_and_safe_client_rendering(ai_pair):
    client, _ = ai_pair
    page = client.get("/ask")
    assert page.status_code == 200 and 'id="ask-form"' in page.text
    starters = re.findall(r'data-question="([^"]+)"', page.text)
    assert len(starters) == 6
    assert all(route_question(question).kind != "unsupported" for question in starters)
    script = client.get("/static/ask.js").text
    assert "innerHTML" not in script and "textContent" in script
    assert "localStorage" not in script and "setInterval" not in script
    assert "submit" in script and 'fetch("/api/ask"' in script
    for route in ["/", "/memory", "/analytics", "/food-recall"]:
        assert 'href="/ask"' in client.get(route).text


def test_managed_adapter_one_request_no_retry_and_fixed_model(monkeypatch):
    import openai
    captured = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0 and kwargs["timeout"] == 55
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def create(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{"fact_refs":["F1"],"insight_refs":["I1"]}'),
            )])

    monkeypatch.setattr(openai, "AsyncOpenAI", Client)
    monkeypatch.setenv("AI_INTEGRATIONS_OPENAI_BASE_URL", "http://test.invalid")
    monkeypatch.setenv("AI_INTEGRATIONS_OPENAI_API_KEY", "test-only")
    context = {
        "intent": "recent", "scope": "test",
        "facts": [{"fact_id": "F1", "kind": "purchase", "text": "Milk"}],
        "allowed_interpretations": [{"insight_id": "I1", "text": "Not current inventory"}],
    }
    result = asyncio.run(ReplitAIProvider().interpret(context))
    assert result["fact_refs"] == ["F1"] and len(captured) == 1
    assert captured[0]["model"] == "gpt-5-nano"
    assert captured[0]["max_completion_tokens"] == MAX_COMPLETION_TOKENS == 8192
    assert captured[0]["response_format"]["json_schema"]["strict"] is True
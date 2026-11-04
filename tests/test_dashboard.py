"""ACI-008 integration contracts; existing services remain authoritative."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_ai_intelligence import RecordingProvider
from tests.test_purchase_analytics import remember
from tests.test_receipt_extraction import blank_png, upload_png


class NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


@pytest.mark.parametrize("route", ["/", "/memory", "/analytics", "/food-recall", "/ask", "/intake"])
def test_shared_navigation_and_active_page(client, route):
    response = client.get(route)
    assert response.status_code == 200
    assert "__NAV__" not in response.text and "__ACTIVE_" not in response.text
    parser = NavigationParser()
    parser.feed(response.text)
    hrefs = {link.get("href") for link in parser.links}
    assert {"/", "/memory", "/analytics", "/food-recall", "/ask", "/intake"} <= hrefs
    current = [link["href"] for link in parser.links if link.get("aria-current") == "page"]
    assert current == [route]
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]


def test_overview_is_default_and_intake_is_preserved(client):
    overview = client.get("/").text.lower()
    assert "overview" in overview and "recent purchases" in overview
    assert "repeat" in overview and "food" in overview and "ai" in overview
    intake = client.get("/intake").text
    assert 'id="intake-form"' in intake and "Maximum 10 MB" in intake
    assert "__MAX_MB__" not in intake


def test_status_without_configuration_is_honest_and_no_ai(settings, monkeypatch):
    monkeypatch.delenv("AI_INTEGRATIONS_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_INTEGRATIONS_OPENAI_API_KEY", raising=False)
    provider = RecordingProvider()
    client = TestClient(create_app(settings, ai_provider=provider))
    body = client.get("/api/ai-status").json()
    assert body["status"] == "unavailable" and body["health_verified"] is False
    assert provider.calls == []


def test_status_with_configuration_is_not_a_health_claim(settings, monkeypatch):
    monkeypatch.setenv("AI_INTEGRATIONS_OPENAI_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("AI_INTEGRATIONS_OPENAI_API_KEY", "synthetic-presence-only")
    provider = RecordingProvider()
    client = TestClient(create_app(settings, ai_provider=provider))
    response = client.get("/api/ai-status")
    assert response.json()["status"] == "configured"
    assert response.json()["health_verified"] is False
    assert "example.invalid" not in response.text and "synthetic-presence-only" not in response.text
    assert provider.calls == []


def test_missing_sdk_is_unavailable_without_importing_or_calling_ai(settings, monkeypatch):
    monkeypatch.setenv("AI_INTEGRATIONS_OPENAI_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("AI_INTEGRATIONS_OPENAI_API_KEY", "synthetic-presence-only")
    monkeypatch.setattr("app.main.find_spec", lambda name: None)
    provider = RecordingProvider()
    client = TestClient(create_app(settings, ai_provider=provider))
    assert client.get("/api/ai-status").json()["status"] == "unavailable"
    assert provider.calls == []


def test_page_loads_make_no_ai_calls_even_if_provider_fails(settings):
    provider = RecordingProvider()
    provider.error = RuntimeError("synthetic unavailable")
    client = TestClient(create_app(settings, ai_provider=provider))
    for route in ["/", "/intake", "/memory", "/analytics", "/food-recall", "/ask", "/api/ai-status"]:
        assert client.get(route).status_code == 200
    assert provider.calls == []


def test_existing_filters_and_classification_controls_retained(client):
    history = client.get("/memory").text
    recall = client.get("/food-recall").text
    assert 'aria-label="Purchase history filters"' in history
    assert 'id="memory-detail"' in history and 'id="memory-items"' in history
    assert 'aria-label="Food recall filters"' in recall
    for name in ["food_classification", "need_want_classification", "durability_classification"]:
        assert name in client.get("/static/memory.js").text


def test_reads_retain_unknowns_no_totals_and_no_write_authority(settings):
    provider = RecordingProvider()
    client = TestClient(create_app(settings, ai_provider=provider))
    evidence = upload_png(client, blank_png())
    memory = remember(client, settings, evidence["evidence_id"], None, None, [{"name": "Unmapped Item"}])
    analytics = client.get("/api/analytics").json()
    assert analytics["classifications"]["need_want"]["unknown"] == 1
    summary = client.get("/api/memory").json()["purchases"][0]
    assert summary["merchant"] is None and summary["purchase_date"] is None
    assert "total" not in summary
    before = _snapshot(settings.data_dir.parent)
    for route in ["/", "/intake", "/memory", "/analytics", "/food-recall", "/ask", "/api/ai-status"]:
        assert client.get(route).status_code == 200
    assert client.get(f"/api/memory/{memory['memory_id']}").status_code == 200
    assert client.get("/api/analytics").json() == analytics
    assert _snapshot(settings.data_dir.parent) == before
    assert provider.calls == []


def test_overview_sources_are_existing_apis_not_raw_ocr(client):
    script = client.get("/static/overview.js").text
    for endpoint in ["/api/memory", "/api/analytics", "/api/visual-recall", "/api/ai-status"]:
        assert endpoint in script
    assert "/api/receipts" not in script and "/api/purchases" not in script
    assert 'fetch("/api/ask"' not in script and "innerHTML" not in script
    assert "setInterval" not in script and "localStorage" not in script


def _snapshot(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }
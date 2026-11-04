"""ACI-006 Walmart food pictures on purchase history."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.visual_recall.provider import CatalogImageProvider, ProviderMatch
from app.visual_recall.walmart import is_walmart_merchant
from app.receipt_intake.repository import read_original_bytes
from tests.test_purchase_analytics import history, remember
from tests.test_receipt_extraction import blank_png, upload_png


def test_walmart_detection_is_conservative():
    assert is_walmart_merchant("Walmart")
    assert is_walmart_merchant("Walmart Supercenter")
    assert is_walmart_merchant("Wal-Mart")
    assert is_walmart_merchant("Wal Mart Neighborhood Market")
    assert not is_walmart_merchant("North Market")
    assert not is_walmart_merchant("Super Walmart")
    assert not is_walmart_merchant("Wally World")
    assert not is_walmart_merchant(None)


def test_walmart_food_recall_uses_representative_or_text(client: TestClient, settings):
    original = blank_png()
    evidence = upload_png(client, original, "blank.png")
    before = read_original_bytes(settings, evidence["storage_reference"])
    evidence_id = evidence["evidence_id"]
    purchase = remember(
        client,
        settings,
        evidence_id,
        "Walmart Supercenter",
        "2026-03-20",
        [
            {"name": "Banana", "quantity": "1", "line_total": "1.24"},
            {"name": "Milk", "quantity": None, "line_total": "3.42"},
            {"name": "Great Value Whole Milk 1 Gallon", "quantity": "1", "line_total": "3.18"},
            {"name": "Milk Bread", "quantity": "1", "line_total": "2.00"},
            {"name": "ZXQ-17", "quantity": None, "line_total": "1.00"},
            {"name": "HDMI Cable", "quantity": "1", "line_total": "12.00"},
        ],
    )
    remember(
        client,
        settings,
        evidence_id,
        "North Market",
        "2026-03-21",
        [{"name": "Banana", "quantity": "1", "line_total": "1.24"}],
    )
    analytics_before = client.get("/api/analytics").json()
    memory_before = history(client)

    report = client.get("/api/visual-recall").json()
    again = client.get("/api/visual-recall").json()

    assert report["status"] == "ready"
    by_name = {item["confirmed_item_name"]: item for item in report["items"]}
    assert set(by_name) == {"Banana", "Milk", "Great Value Whole Milk 1 Gallon", "Milk Bread"}
    bananas = by_name["Banana"]
    milk = by_name["Milk"]
    specific = by_name["Great Value Whole Milk 1 Gallon"]
    mixed = by_name["Milk Bread"]
    assert bananas["display"] == "representative"
    assert bananas["match_type"] == "representative"
    assert bananas["provider"] == "local-catalog"
    assert bananas["source_reference"] == "Purchase Intelligence original illustration"
    assert bananas["memory_item_id"]
    assert bananas["purchase_id"] == purchase["purchase_id"]
    assert milk["display"] == "representative"
    assert milk["match_type"] == "representative"
    assert specific["match_type"] == "representative"
    assert specific["display"] == "representative"
    assert mixed["match_type"] == "none"
    assert mixed["display"] == "text-only"
    assert mixed["image_available"] is False
    image = client.get(f"/api/visual-recall/enrichments/{bananas['enrichment_id']}/image")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in image.content
    assert again == report
    assert enrichment_count(settings) == 4
    assert history(client) == memory_before
    assert client.get("/api/analytics").json() == analytics_before
    assert read_original_bytes(settings, evidence["storage_reference"]) == before
    assert client.get(f"/api/purchases/{purchase['purchase_id']}").json()["merchant"] == "Walmart Supercenter"
    exact_view = client.get("/api/visual-recall?view=exact").json()
    assert exact_view["items"] == []
    assert exact_view["reason"] == "No exact product image is in this Walmart food history."

    stored = client.get(f"/api/memory/{bananas['memory_id']}").json()
    target = next(item for item in stored["items"] if item["memory_item_id"] == bananas["memory_item_id"])
    patched = client.patch(
        f"/api/memory/{bananas['memory_id']}/items/{bananas['memory_item_id']}",
        json={
            "food_classification": "non-food",
            "need_want_classification": "want",
            "durability_classification": "long-term",
        },
    )
    hidden = client.get("/api/visual-recall").json()

    assert patched.status_code == 200
    assert all(item["memory_item_id"] != bananas["memory_item_id"] for item in hidden["items"])
    reread = client.get(f"/api/memory/{bananas['memory_id']}").json()
    changed = next(item for item in reread["items"] if item["memory_item_id"] == target["memory_item_id"])
    assert changed["item_name"] == "Banana"
    assert changed["food_classification"] == "non-food"
    assert client.get(f"/api/purchases/{purchase['purchase_id']}").json()["items"][0]["item_name"] == "Banana"


def test_explicit_catalog_identity_can_be_exact(settings, tmp_path):
    catalog = tmp_path / "catalog"
    pictures = catalog / "representative"
    pictures.mkdir(parents=True)
    exact = catalog / "exact"
    exact.mkdir()
    (pictures / "milk.svg").write_text(_svg("milk"), encoding="utf-8")
    (exact / "milk.svg").write_text(_svg("exact-milk"), encoding="utf-8")
    (catalog / "catalog.json").write_text(
        json.dumps(
            {
                "exact": [
                    {
                        "name": "Great Value Whole Milk 1 Gallon",
                        "file": "exact/milk.svg",
                        "source": "Explicit catalog identity",
                    }
                ],
                "representative": [
                    {
                        "tokens": ["milk"],
                        "file": "representative/milk.svg",
                        "source": "Purchase Intelligence original illustration",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    local = TestClient(create_app(settings, image_provider=CatalogImageProvider(catalog)))
    evidence_id = upload_png(local, blank_png(), "blank.png")["evidence_id"]
    remember(
        local,
        settings,
        evidence_id,
        "Walmart",
        "2026-04-01",
        [{"name": "Great Value Whole Milk 1 Gallon", "quantity": "1", "line_total": "3.18"}],
    )
    item = local.get("/api/visual-recall").json()["items"][0]
    page = local.get("/food-recall")

    assert item["match_type"] == "exact"
    assert item["display"] == "exact"
    assert item["source_reference"] == "Explicit catalog identity"
    assert local.get(f"/api/visual-recall/enrichments/{item['enrichment_id']}/image").status_code == 200
    assert "Exact image" in page.text
    assert "Representative image" in page.text
    assert "still in the household" in page.text


def test_provider_failure_keeps_purchase_history(settings):
    local = TestClient(create_app(settings, image_provider=FailingProvider()))
    evidence_id = upload_png(local, blank_png(), "blank.png")["evidence_id"]
    purchase = remember(
        local,
        settings,
        evidence_id,
        "Walmart",
        "2026-04-02",
        [{"name": "Banana", "quantity": "1", "line_total": "1.24"}],
    )
    before = local.get(f"/api/memory/{purchase['memory_id']}").json()
    first = local.get("/api/visual-recall").json()
    second = local.get("/api/visual-recall").json()

    assert first["items"][0]["match_type"] == "error"
    assert first["items"][0]["display"] == "text-only"
    assert first["items"][0]["image_available"] is False
    assert second["items"][0]["enrichment_id"] == first["items"][0]["enrichment_id"]
    assert enrichment_count(settings) == 1
    assert local.get(f"/api/memory/{purchase['memory_id']}").json() == before
    assert local.get(f"/api/purchases/{purchase['purchase_id']}").status_code == 200
    assert local.get(f"/api/visual-recall/enrichments/{first['items'][0]['enrichment_id']}/image").status_code == 404


def test_missing_image_file_degrades_to_text(settings):
    local = TestClient(create_app(settings, image_provider=MissingImageProvider()))
    evidence_id = upload_png(local, blank_png(), "blank.png")["evidence_id"]
    remember(
        local,
        settings,
        evidence_id,
        "Walmart",
        None,
        [{"name": "Banana", "quantity": "1", "line_total": "1.24"}],
    )
    item = local.get("/api/visual-recall").json()["items"][0]

    assert item["match_type"] == "representative"
    assert item["display"] == "text-only"
    assert item["image_available"] is False
    assert local.get(f"/api/visual-recall/enrichments/{item['enrichment_id']}/image").status_code == 404


def test_empty_and_filtered_recall(client: TestClient):
    empty = client.get("/api/visual-recall")
    rejected = client.get("/api/visual-recall?view=inventory")
    page = client.get("/food-recall")
    script = client.get("/static/food-recall.js")
    combined = f"{page.text} {script.text}".lower()

    assert empty.status_code == 200
    assert empty.json()["status"] == "empty"
    assert empty.json()["reason"] == "No Walmart food purchases are in purchase history."
    assert rejected.status_code == 400
    assert "Food you purchased" in page.text
    assert "Representative image" in script.text
    assert "in stock" not in combined
    assert "pantry" not in combined
    assert "you still have" not in combined
    assert "available now" not in combined
    assert "innerHTML" not in script.text


class FailingProvider:
    name = "failing-provider"

    def lookup(self, item_name: str) -> ProviderMatch:
        raise TimeoutError("timed out")

    def resolve(self, reference: str | None) -> Path | None:
        return None


class MissingImageProvider:
    name = "missing-provider"

    def lookup(self, item_name: str) -> ProviderMatch:
        return ProviderMatch("representative", "representative/missing.svg", "Missing illustration", self.name)

    def resolve(self, reference: str | None) -> Path | None:
        return None


def enrichment_count(settings) -> int:
    with sqlite3.connect(settings.visual_db_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM visual_enrichment").fetchone()[0]


def _svg(label: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
        f"<rect width=\"40\" height=\"40\" fill=\"#fff\"/><text x=\"4\" y=\"24\">{label}</text></svg>"
    )

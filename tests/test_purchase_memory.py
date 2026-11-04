"""ACI-004 purchase history and conservative classification."""

from __future__ import annotations

import sqlite3
import uuid

from fastapi.testclient import TestClient

from app.purchase_confirmation.models import ConfirmedItem, ConfirmedPurchase
from app.purchase_confirmation.repository import insert_purchase
from app.purchase_memory.classification import classify_item_name
from app.receipt_intake.repository import read_original_bytes
from tests.test_receipt_extraction import RECEIPT_LINES, blank_png, receipt_png, upload_png
from tests.test_purchase_confirmation import confirmation_body, extract


def memory_count(settings) -> int:
    with sqlite3.connect(settings.memory_db_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM purchase_memory").fetchone()[0]


def test_classifier_stays_conservative():
    assert classify_item_name("Milk Gallon") == ("food", "unknown", "consumable")
    assert classify_item_name("HDMI Cable") == ("non-food", "unknown", "long-term")
    assert classify_item_name("Paper Towels") == ("non-food", "unknown", "consumable")
    assert classify_item_name("ZXQ-17") == ("unknown", "unknown", "unknown")


def test_confirmed_purchase_becomes_recallable_history(client: TestClient, settings):
    original = receipt_png(RECEIPT_LINES)
    evidence = upload_png(client, original)
    before = read_original_bytes(settings, evidence["storage_reference"])
    extraction = extract(client, evidence["evidence_id"])
    assert client.get("/api/memory").json()["purchases"] == []

    body = confirmation_body(extraction)
    body["items"][1]["item_name"] = "ZXQ-17"
    confirmed_response = client.post("/api/purchases", json=body)
    confirmed = confirmed_response.json()
    memory_id = confirmed.pop("memory_id")
    stored_purchase = client.get(f"/api/purchases/{confirmed['purchase_id']}").json()

    assert confirmed_response.status_code == 201
    assert stored_purchase == confirmed
    assert memory_count(settings) == 1

    memory = client.get(f"/api/memory/{memory_id}").json()
    assert memory["status"] == "remembered"
    assert memory["purchase_id"] == stored_purchase["purchase_id"]
    assert memory["evidence_id"] == evidence["evidence_id"]
    assert memory["merchant"] == "North Market"
    assert memory["purchase_date"] == "2026-03-15"
    assert [item["item_name"] for item in memory["items"]] == ["Milk Gallon", "ZXQ-17", "Eggs Large"]
    assert [item["line_order"] for item in memory["items"]] == [1, 2, 3]
    assert [item["purchase_item_id"] for item in memory["items"]] == [
        item["purchase_item_id"] for item in stored_purchase["items"]
    ]
    assert memory["items"][0]["line_total"] == stored_purchase["items"][0]["line_total"]
    assert memory["items"][0]["food_classification"] == "food"
    assert memory["items"][0]["need_want_classification"] == "unknown"
    assert memory["items"][0]["durability_classification"] == "consumable"
    assert memory["items"][1]["food_classification"] == "unknown"
    assert memory["items"][1]["need_want_classification"] == "unknown"
    assert memory["items"][1]["durability_classification"] == "unknown"

    history = client.get("/api/memory").json()
    assert history["purchases"][0]["memory_id"] == memory_id
    assert history["purchases"][0]["merchant"] == "North Market"

    duplicate = client.post(
        "/api/memory",
        json={"purchase_id": stored_purchase["purchase_id"], "evidence_id": "not-the-receipt"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["memory_id"] == memory_id
    assert duplicate.json()["evidence_id"] == evidence["evidence_id"]
    assert memory_count(settings) == 1

    ambiguous = memory["items"][1]
    rejected = client.patch(
        f"/api/memory/{memory_id}/items/{ambiguous['memory_item_id']}",
        json={"food_classification": "grocery"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["reason"] == "Choose food, non-food, or unknown."
    unchanged = client.get(f"/api/memory/{memory_id}").json()
    assert unchanged["items"][1]["food_classification"] == "unknown"

    corrected = client.patch(
        f"/api/memory/{memory_id}/items/{ambiguous['memory_item_id']}",
        json={
            "food_classification": "non-food",
            "need_want_classification": "want",
            "durability_classification": "long-term",
        },
    )
    assert corrected.status_code == 200
    reloaded = client.get(f"/api/memory/{memory_id}").json()
    assert reloaded["items"][1]["food_classification"] == "non-food"
    assert reloaded["items"][1]["need_want_classification"] == "want"
    assert reloaded["items"][1]["durability_classification"] == "long-term"
    assert reloaded["items"][1]["item_name"] == "ZXQ-17"
    assert client.get(f"/api/purchases/{stored_purchase['purchase_id']}").json() == stored_purchase
    assert read_original_bytes(settings, evidence["storage_reference"]) == before == original

    assert client.get("/api/memory?filter=food").json()["purchases"][0]["memory_id"] == memory_id
    assert client.get("/api/memory?filter=want").json()["purchases"][0]["memory_id"] == memory_id
    assert client.get("/api/memory?filter=long-term").json()["purchases"][0]["memory_id"] == memory_id
    assert client.get("/api/memory?filter=need").json()["purchases"] == []


def test_obvious_non_food_classifications_persist(client: TestClient, settings):
    evidence = upload_png(client, blank_png(), "blank.png")
    purchase = _seed_purchase(
        evidence["evidence_id"],
        [("HDMI Cable", "12.00"), ("Paper Towels", "4.50")],
    )
    insert_purchase(settings, purchase)

    response = client.post("/api/memory", json={"purchase_id": purchase.purchase_id})
    body = response.json()

    assert response.status_code == 201
    assert [item["item_name"] for item in body["items"]] == ["HDMI Cable", "Paper Towels"]
    assert body["items"][0]["food_classification"] == "non-food"
    assert body["items"][0]["durability_classification"] == "long-term"
    assert body["items"][0]["need_want_classification"] == "unknown"
    assert body["items"][1]["food_classification"] == "non-food"
    assert body["items"][1]["durability_classification"] == "consumable"
    saved = client.get(f"/api/memory/{body['memory_id']}").json()
    assert saved["items"][0]["food_classification"] == "non-food"
    assert client.get(f"/api/purchases/{purchase.purchase_id}").json()["items"][0]["item_name"] == "HDMI Cable"


def test_unknown_purchase_creates_no_memory(client: TestClient, settings):
    response = client.post(
        "/api/memory",
        json={"purchase_id": "44444444-4444-4444-8444-444444444444"},
    )

    assert response.status_code == 404
    assert response.json()["reason"] == "The confirmed purchase was not found."
    assert memory_count(settings) == 0


def test_missing_evidence_does_not_create_memory(client: TestClient, settings):
    evidence = upload_png(client, blank_png(), "blank.png")
    purchase = _seed_purchase(evidence["evidence_id"], [("Milk Gallon", "3.42")])
    insert_purchase(settings, purchase)
    with sqlite3.connect(settings.db_path) as connection:
        connection.execute("DELETE FROM receipt_evidence WHERE evidence_id = ?", (evidence["evidence_id"],))

    response = client.post("/api/memory", json={"purchase_id": purchase.purchase_id})

    assert response.status_code == 400
    assert response.json()["reason"] == "The receipt evidence for this purchase is unavailable."
    assert memory_count(settings) == 0
    assert client.get(f"/api/purchases/{purchase.purchase_id}").status_code == 200


def test_malformed_memory_requests_are_rejected(client: TestClient, settings):
    assert client.post("/api/memory", json=[]).status_code == 400
    assert client.get("/api/memory?filter=inventory").status_code == 400
    assert client.get(f"/api/memory/{uuid.uuid4()}").status_code == 404
    assert memory_count(settings) == 0


def test_history_page_does_not_claim_current_inventory(client: TestClient):
    page = client.get("/memory")
    script = client.get("/static/memory.js")
    intake = client.get("/")
    combined = " ".join((page.text, script.text, intake.text)).lower()

    assert page.status_code == 200
    assert "Purchase history" in page.text
    assert "Remembered purchase" in page.text
    assert "Save classification" in script.text
    assert "in stock" not in combined
    assert "currently available" not in combined
    assert "pantry" not in combined
    assert "you still have" not in combined
    assert "you currently have" not in combined
    assert "innerHTML" not in script.text


def _seed_purchase(evidence_id: str, items: list[tuple[str, str]]) -> ConfirmedPurchase:
    purchase_id = str(uuid.uuid4())
    return ConfirmedPurchase(
        purchase_id=purchase_id,
        evidence_id=evidence_id,
        extraction_id=str(uuid.uuid4()),
        merchant="North Market",
        purchase_date="2026-03-15",
        purchase_time=None,
        subtotal=None,
        tax=None,
        total=items[-1][1],
        confirmed_at="2026-10-03T00:00:00+00:00",
        items=tuple(
            ConfirmedItem(
                purchase_item_id=str(uuid.uuid4()),
                purchase_id=purchase_id,
                source_line_id=str(uuid.uuid4()),
                item_name=name,
                quantity=None,
                unit_price=None,
                line_total=total,
                raw_line_text=f"{name} {total}",
                line_order=index,
            )
            for index, (name, total) in enumerate(items, start=1)
        ),
    )

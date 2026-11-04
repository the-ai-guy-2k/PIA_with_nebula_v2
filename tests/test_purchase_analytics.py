"""ACI-005 counts calculated from purchase history."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.purchase_analytics.identity import analytics_key
from app.purchase_confirmation.models import ConfirmedItem, ConfirmedPurchase
from app.purchase_confirmation.repository import insert_purchase
from tests.test_purchase_confirmation import extract
from tests.test_receipt_extraction import blank_png, upload_png


def test_analytics_key_changes_only_case_and_spacing():
    assert analytics_key("  Milk   Gallon ") == analytics_key("milk gallon")
    assert analytics_key("Milk Gallon") != analytics_key("Great Value Whole Milk 1 Gal")


def test_empty_history_is_an_explicit_empty_state(client: TestClient):
    report = client.get("/api/analytics")

    assert report.status_code == 200
    body = report.json()
    assert body["status"] == "empty"
    assert body["reason"] == "No remembered purchases yet."
    assert body["summary"]["remembered_purchases"] == 0
    assert body["repeat_items"] == []
    assert body["merchants"] == []


def test_one_purchase_is_not_a_repeat(client: TestClient, settings):
    evidence = upload_png(client, blank_png(), "blank.png")
    remembered = remember(
        client,
        settings,
        evidence["evidence_id"],
        merchant=None,
        purchase_date="2026-04-02",
        items=[{"name": "HDMI Cable", "quantity": "1", "line_total": "12.00"}],
    )
    report = client.get("/api/analytics").json()
    item = report["repeat_items"][0]

    assert report["summary"]["remembered_purchases"] == 1
    assert report["summary"]["remembered_items"] == 1
    assert report["summary"]["unique_items"] == 1
    assert report["summary"]["repeating_items"] == 0
    assert item["occurrence_count"] == 1
    assert item["repeating"] is False
    assert item["frequency_status"] == "insufficient_history"
    assert item["average_interval_days"] is None
    assert item["latest_interval_days"] is None
    assert item["sources"][0]["memory_id"] == remembered["memory_id"]
    assert report["merchants"] == [{"merchant": None, "purchase_count": 1}]
    assert report["classifications"]["food"]["non-food"] == 1
    assert report["classifications"]["need_want"]["unknown"] == 1
    assert report["classifications"]["durability"]["long-term"] == 1


def test_repeated_item_frequency_quantity_and_trace(client: TestClient, settings):
    evidence = upload_png(client, blank_png(), "blank.png")
    evidence_id = evidence["evidence_id"]
    first = remember(client, settings, evidence_id, "North Market", "2026-03-01", [_milk("1")])
    second = remember(client, settings, evidence_id, "North Market", "2026-03-11", [_milk(None)])
    third = remember(client, settings, evidence_id, "Corner Shop", "2026-03-26", [_milk("2")])
    undated = remember(client, settings, evidence_id, "Corner Shop", None, [_milk(None)])
    separate = remember(
        client,
        settings,
        evidence_id,
        "North Market",
        "2026-03-02",
        [{"name": "Great Value Whole Milk 1 Gal", "quantity": "1", "line_total": "3.42"}],
    )
    before = history(client)

    first_report = client.get("/api/analytics").json()
    second_report = client.get("/api/analytics").json()

    assert first_report == second_report
    assert history(client) == before
    milk = _by_key(first_report, "milk gallon")
    other = _by_key(first_report, "great value whole milk 1 gal")
    assert milk["occurrence_count"] == 4
    assert milk["repeating"] is True
    assert milk["known_quantity"] == "3"
    assert milk["quantity_records_known"] == 2
    assert milk["quantity_records_unknown"] == 2
    assert milk["first_purchase_date"] == "2026-03-01"
    assert milk["latest_purchase_date"] == "2026-03-26"
    assert milk["frequency_status"] == "calculated"
    assert milk["average_interval_days"] == "12.5"
    assert milk["latest_interval_days"] == 15
    assert {source["memory_id"] for source in milk["sources"]} == {
        first["memory_id"],
        second["memory_id"],
        third["memory_id"],
        undated["memory_id"],
    }
    assert other["occurrence_count"] == 1
    assert other["repeating"] is False
    assert other["analytics_key"] != milk["analytics_key"]
    assert first_report["summary"]["repeating_items"] == 1
    assert first_report["summary"]["earliest_purchase_date"] == "2026-03-01"
    assert first_report["summary"]["latest_purchase_date"] == "2026-03-26"
    assert {"merchant": "North Market", "purchase_count": 3} in first_report["merchants"]
    assert {"merchant": "Corner Shop", "purchase_count": 2} in first_report["merchants"]
    assert first_report["classifications"]["food"]["food"] == 5
    assert client.get(f"/api/purchases/{separate['purchase_id']}").json()["merchant"] == "North Market"

    target = milk["sources"][0]
    patched = client.patch(
        f"/api/memory/{target['memory_id']}/items/{target['memory_item_id']}",
        json={
            "food_classification": "non-food",
            "need_want_classification": "want",
            "durability_classification": "long-term",
        },
    )
    assert patched.status_code == 200
    after_patch = history(client)
    updated = client.get("/api/analytics").json()

    assert history(client) == after_patch
    assert updated["classifications"]["food"]["food"] == 4
    assert updated["classifications"]["food"]["non-food"] == 1
    assert updated["classifications"]["need_want"]["want"] == 1
    stored = client.get(f"/api/memory/{target['memory_id']}").json()
    stored_item = next(item for item in stored["items"] if item["memory_item_id"] == target["memory_item_id"])
    assert stored_item["item_name"] == "Milk Gallon"
    assert stored_item["food_classification"] == "non-food"


def test_case_and_space_share_an_identity_without_rewriting_names(client: TestClient, settings):
    evidence_id = upload_png(client, blank_png(), "blank.png")["evidence_id"]
    remember(client, settings, evidence_id, "North Market", "2026-05-01", [{"name": "Milk Gallon", "quantity": "1", "line_total": "3.42"}])
    remember(
        client,
        settings,
        evidence_id,
        "North Market",
        "2026-05-08",
        [{"name": "  MILK   gallon ", "quantity": "1", "line_total": "3.42"}],
    )
    report = client.get("/api/analytics").json()
    item = _by_key(report, "milk gallon")
    saved_names = sorted(source["item_name"] for source in item["sources"])

    assert report["summary"]["unique_items"] == 1
    assert item["occurrence_count"] == 2
    assert item["repeating"] is True
    assert saved_names == ["  MILK   gallon ", "Milk Gallon"]
    assert item["average_interval_days"] == "7"
    assert item["latest_interval_days"] == 7


def test_same_day_interval_is_zero(client: TestClient, settings):
    evidence_id = upload_png(client, blank_png(), "blank.png")["evidence_id"]
    remember(client, settings, evidence_id, "North Market", "2026-04-01", [_milk("1")])
    remember(client, settings, evidence_id, "North Market", "2026-04-01", [_milk("1")])
    item = _by_key(client.get("/api/analytics").json(), "milk gallon")

    assert item["occurrence_count"] == 2
    assert item["frequency_status"] == "calculated"
    assert item["average_interval_days"] == "0"
    assert item["latest_interval_days"] == 0


def test_unconfirmed_extraction_is_not_analyzed(client: TestClient, settings):
    evidence = upload_png(client, blank_png(), "blank.png")
    extract(client, evidence["evidence_id"])

    report = client.get("/api/analytics")

    assert report.status_code == 200
    assert report.json()["status"] == "empty"


def test_unsupported_analytics_query_is_rejected(client: TestClient):
    response = client.get("/api/analytics?forecast=1")

    assert response.status_code == 400
    assert response.json()["reason"] == "That analytics request is not supported."


def test_patterns_page_states_what_the_counts_mean(client: TestClient):
    page = client.get("/analytics")
    script = client.get("/static/analytics.js")
    combined = f"{page.text} {script.text}".lower()

    assert page.status_code == 200
    assert "Purchase patterns" in page.text
    assert "Show remembered purchases" in script.text
    assert "Not enough purchase dates" in script.text
    assert "in stock" not in combined
    assert "pantry" not in combined
    assert "you currently have" not in combined
    assert "forecast" not in combined
    assert "recommend" not in combined
    assert "innerHTML" not in script.text


def remember(client, settings, evidence_id, merchant, purchase_date, items):
    purchase_id = str(uuid.uuid4())
    purchase = ConfirmedPurchase(
        purchase_id=purchase_id,
        evidence_id=evidence_id,
        extraction_id=str(uuid.uuid4()),
        merchant=merchant,
        purchase_date=purchase_date,
        purchase_time=None,
        subtotal=None,
        tax=None,
        total="10.00",
        confirmed_at="2026-10-03T00:00:00+00:00",
        items=tuple(
            ConfirmedItem(
                purchase_item_id=str(uuid.uuid4()),
                purchase_id=purchase_id,
                source_line_id=str(uuid.uuid4()),
                item_name=item["name"],
                quantity=item.get("quantity"),
                unit_price=None,
                line_total=item.get("line_total"),
                raw_line_text=item["name"].strip(),
                line_order=index,
            )
            for index, item in enumerate(items, start=1)
        ),
    )
    insert_purchase(settings, purchase)
    response = client.post("/api/memory", json={"purchase_id": purchase_id})
    assert response.status_code == 201, response.text
    return response.json()


def history(client: TestClient) -> list[dict]:
    listing = client.get("/api/memory").json()["purchases"]
    return [client.get(f"/api/memory/{row['memory_id']}").json() for row in listing]


def _milk(quantity: str | None) -> dict:
    return {"name": "Milk Gallon", "quantity": quantity, "line_total": "3.42"}


def _by_key(report: dict, key: str) -> dict:
    return next(item for item in report["repeat_items"] if item["analytics_key"] == key)

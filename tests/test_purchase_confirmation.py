"""ACI-003 review, correction, and explicit confirmation."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.purchase_confirmation.confidence import assess_extraction
from app.receipt_extraction.models import ExtractionRecord, LineCandidate
from app.receipt_intake.repository import get_evidence, read_original_bytes
from tests.test_receipt_extraction import RECEIPT_LINES, blank_png, receipt_png, upload_png


def purchase_count(settings) -> int:
    with sqlite3.connect(settings.confirmed_db_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM confirmed_purchase").fetchone()[0]


def extract(client: TestClient, evidence_id: str) -> dict:
    response = client.post(f"/api/receipts/{evidence_id}/extraction")
    assert response.status_code == 200, response.text
    return response.json()


def confirmation_body(extraction: dict, **overrides) -> dict:
    body = {
        "evidence_id": extraction["evidence_id"],
        "extraction_id": extraction["extraction_id"],
        "merchant": extraction["merchant_normalized_candidate"],
        "purchase_date": extraction["purchase_date_candidate"],
        "purchase_time": extraction["purchase_time_candidate"],
        "subtotal": extraction["subtotal_candidate"],
        "tax": extraction["tax_candidate"],
        "total": extraction["total_candidate"],
        "items": [
            {
                "source_line_id": line["line_id"],
                "item_name": line["normalized_name_candidate"],
                "quantity": line["quantity_candidate"],
                "unit_price": line["unit_price_candidate"],
                "line_total": line["line_total_candidate"],
            }
            for line in extraction["lines"]
        ],
    }
    body.update(overrides)
    return body


def test_confidence_flags_ambiguous_amounts_without_inventing_numbers():
    line = LineCandidate(
        line_id="11111111-1111-4111-8111-111111111111",
        extraction_id="22222222-2222-4222-8222-222222222222",
        raw_text="Milk $3.O9",
        normalized_name_candidate="Milk",
        quantity_candidate=None,
        unit_price_candidate=None,
        line_total_candidate=None,
        line_order=1,
    )
    record = ExtractionRecord(
        extraction_id=line.extraction_id,
        evidence_id="33333333-3333-4333-8333-333333333333",
        merchant_raw=None,
        merchant_normalized_candidate=None,
        purchase_date_candidate=None,
        purchase_time_candidate=None,
        subtotal_candidate=None,
        tax_candidate=None,
        total_candidate=None,
        raw_text="Milk $3.O9\nTotal e. 78",
        extraction_status="extracted",
        failure_reason=None,
        created_at="2026-10-03T00:00:00+00:00",
        lines=(line,),
    )
    confidence = assess_extraction(record)

    assert confidence["merchant"] == "low"
    assert confidence["purchase_date"] == "low"
    assert confidence["total"] == "low"
    assert confidence["lines"][0]["line_total"] == "low"
    assert confidence["lines"][0]["item_name"] == "medium"
    assert record.lines[0].line_total_candidate is None


def test_high_confidence_review_can_be_confirmed(client: TestClient, settings):
    original = receipt_png(RECEIPT_LINES)
    evidence = upload_png(client, original)
    extraction = extract(client, evidence["evidence_id"])
    before = read_original_bytes(settings, evidence["storage_reference"])

    assert extraction["confirmation_state"] == "unconfirmed"
    assert extraction["confidence"]["merchant"] == "medium"
    assert extraction["confidence"]["purchase_date"] == "high"
    assert extraction["confidence"]["total"] == "high"
    assert purchase_count(settings) == 0

    response = client.post("/api/purchases", json=confirmation_body(extraction))
    body = response.json()

    assert response.status_code == 201, body
    assert body["status"] == "confirmed"
    assert body["purchase_id"]
    assert body["evidence_id"] == evidence["evidence_id"]
    assert body["extraction_id"] == extraction["extraction_id"]
    assert body["merchant"] == "North Market"
    assert body["purchase_date"] == "2026-03-15"
    assert body["total"] == "10.47"
    assert [item["item_name"] for item in body["items"]] == ["Milk Gallon", "Bread Loaf", "Eggs Large"]
    assert [item["line_order"] for item in body["items"]] == [1, 2, 3]
    assert read_original_bytes(settings, evidence["storage_reference"]) == before == original

    saved = client.get(f"/api/purchases/{body['purchase_id']}")
    assert saved.status_code == 200
    assert saved.json()["purchase_id"] == body["purchase_id"]
    assert purchase_count(settings) == 1


def test_user_correction_keeps_the_raw_candidate(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    extraction = extract(client, evidence["evidence_id"])
    body = confirmation_body(extraction)
    body["merchant"] = "North Market Downtown"
    body["items"][0]["item_name"] = "Great Value Milk"

    confirmed = client.post("/api/purchases", json=body).json()
    fresh = client.get(f"/api/receipts/{evidence['evidence_id']}/extraction").json()

    assert confirmed["merchant"] == "North Market Downtown"
    assert confirmed["items"][0]["item_name"] == "Great Value Milk"
    assert confirmed["items"][0]["raw_line_text"] == extraction["lines"][0]["raw_text"]
    assert fresh["merchant_normalized_candidate"] == extraction["merchant_normalized_candidate"]
    assert fresh["lines"][0]["raw_text"] == extraction["lines"][0]["raw_text"]
    assert fresh["lines"][0]["normalized_name_candidate"] == "Milk Gallon"
    assert fresh["confirmation_state"] == "confirmed"


def test_missing_optional_values_stay_null(client: TestClient, settings):
    lines = ["NORTH MARKET", "2026-03-15", "Milk Gallon 3.42", "Total 3.42"]
    evidence = upload_png(client, receipt_png(lines))
    extraction = extract(client, evidence["evidence_id"])
    assert extraction["purchase_time_candidate"] is None
    assert extraction["tax_candidate"] is None
    assert extraction["confidence"]["purchase_time"] == "absent"
    assert extraction["confidence"]["tax"] == "absent"

    confirmed = client.post("/api/purchases", json=confirmation_body(extraction)).json()

    assert confirmed["purchase_time"] is None
    assert confirmed["tax"] is None
    assert confirmed["subtotal"] is None
    assert confirmed["merchant"] == "North Market"
    assert confirmed["total"] == "3.42"
    assert confirmed["items"][0]["quantity"] is None


def test_confirmed_items_keep_source_lineage(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    extraction = extract(client, evidence["evidence_id"])
    confirmed = client.post("/api/purchases", json=confirmation_body(extraction)).json()

    assert confirmed["evidence_id"] == extraction["evidence_id"]
    assert confirmed["extraction_id"] == extraction["extraction_id"]
    for confirmed_item, source in zip(confirmed["items"], extraction["lines"], strict=True):
        assert confirmed_item["source_line_id"] == source["line_id"]
        assert confirmed_item["raw_line_text"] == source["raw_text"]
        assert confirmed_item["line_order"] == source["line_order"]
    assert get_evidence(settings, evidence["evidence_id"]) is not None


def test_invalid_numeric_correction_stores_nothing(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    extraction = extract(client, evidence["evidence_id"])
    body = confirmation_body(extraction)
    body["items"][0]["line_total"] = "3.O9"

    response = client.post("/api/purchases", json=body)

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert "line total" in response.json()["reason"]
    assert "traceback" not in response.text.lower()
    assert purchase_count(settings) == 0
    assert client.get(f"/api/receipts/{evidence['evidence_id']}/extraction").json()["confirmation_state"] == "unconfirmed"


def test_empty_item_name_stores_nothing(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    extraction = extract(client, evidence["evidence_id"])
    body = confirmation_body(extraction)
    body["items"][1]["item_name"] = "   "

    response = client.post("/api/purchases", json=body)

    assert response.status_code == 400
    assert response.json()["reason"] == "Each confirmed item needs a name."
    assert purchase_count(settings) == 0


def test_unknown_extraction_creates_no_purchase(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(["NORTH MARKET", "Milk Gallon 3.42", "Total 3.42"]))
    missing = "44444444-4444-4444-8444-444444444444"
    response = client.post(
        "/api/purchases",
        json={
            "evidence_id": evidence["evidence_id"],
            "extraction_id": missing,
            "merchant": "North Market",
            "items": [],
        },
    )

    assert response.status_code == 404
    assert response.json()["reason"] == "The extraction was not found."
    assert purchase_count(settings) == 0


def test_duplicate_confirmation_does_not_change_the_purchase(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    extraction = extract(client, evidence["evidence_id"])
    first = client.post("/api/purchases", json=confirmation_body(extraction))
    original = first.json()
    second_body = confirmation_body(extraction)
    second_body["merchant"] = "A Different Store"
    second = client.post("/api/purchases", json=second_body)
    saved = client.get(f"/api/purchases/{original['purchase_id']}").json()

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["reason"] == "This extraction is already confirmed."
    assert second.json()["purchase_id"] == original["purchase_id"]
    assert purchase_count(settings) == 1
    assert saved["merchant"] == "North Market"
    assert saved["purchase_id"] == original["purchase_id"]


def test_confirmation_does_not_change_receipt_bytes(client: TestClient, settings):
    original = receipt_png(RECEIPT_LINES)
    evidence = upload_png(client, original)
    before = read_original_bytes(settings, evidence["storage_reference"])
    extraction = extract(client, evidence["evidence_id"])
    client.post("/api/purchases", json=confirmation_body(extraction))

    assert read_original_bytes(settings, evidence["storage_reference"]) == before == original


def test_missing_evidence_file_rejects_confirmation(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    extraction = extract(client, evidence["evidence_id"])
    stored = settings.files_dir / evidence["storage_reference"].split("/")[-1]
    stored.unlink()

    response = client.post("/api/purchases", json=confirmation_body(extraction))

    assert response.status_code == 400
    assert response.json()["reason"] == "The preserved receipt file is missing."
    assert purchase_count(settings) == 0
    assert get_evidence(settings, evidence["evidence_id"]) is not None
    assert client.get(f"/api/receipts/{evidence['evidence_id']}/extraction").status_code == 200


def test_extraction_without_items_cannot_be_confirmed(client: TestClient, settings):
    evidence = upload_png(client, blank_png(), "blank.png")
    extraction = extract(client, evidence["evidence_id"])
    response = client.post("/api/purchases", json=confirmation_body(extraction))

    assert response.status_code == 400
    assert response.json()["reason"] == "This extraction has no item lines to confirm."
    assert purchase_count(settings) == 0


def test_unrelated_evidence_and_extraction_are_rejected(client: TestClient, settings):
    first = upload_png(client, receipt_png(RECEIPT_LINES), "first.png")
    second = upload_png(client, receipt_png(RECEIPT_LINES), "second.png")
    extraction = extract(client, first["evidence_id"])
    body = confirmation_body(extraction)
    body["evidence_id"] = second["evidence_id"]

    response = client.post("/api/purchases", json=body)

    assert response.status_code == 400
    assert response.json()["reason"] == "The extraction does not belong to this receipt."
    assert purchase_count(settings) == 0


def test_review_page_offers_explicit_confirmation(client: TestClient):
    page = client.get("/intake")
    script = client.get("/static/app.js")

    assert "Confirm purchase" in page.text
    assert "Unconfirmed extraction" in script.text
    assert "innerHTML" not in script.text

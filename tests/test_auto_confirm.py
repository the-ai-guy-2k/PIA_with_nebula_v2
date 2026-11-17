"""Tests for auto-confirm on reconciled Muse ingest (Tee, Nov 16, 2026).

Review & Confirm is removed: a Muse extraction that reconciles —
lines sum to the subtotal, subtotal + tax equals the total, every line's
qty x unit price matches its line total — auto-confirms on ingest, using
the same validation as the manual confirm, then the same memory + pantry
steps. Anything else holds unconfirmed: reconcile-or-hold.
"""

from __future__ import annotations

import io

from PIL import Image

from app.muse_ai.queue import read_events
from app.muse_ai.service import ingest_muse_extraction, queue_receipt
from app.purchase_confirmation.repository import get_purchase_for_extraction
from app.receipt_intake.service import preserve_upload

RECONCILED = {
    "source": "muse_ai",
    "merchant": "Walmart",
    "purchase_date": "2026-11-06",
    "purchase_time": None,
    "subtotal": "19.41",
    "tax": "4.16",
    "total": "23.57",
    "lines": [
        {
            "name": "Ground Beef 2lb",
            "quantity": 1,
            "unit_price": "11.44",
            "line_total": "11.44",
            "raw_text": "GROUND BEEF 2LB 11.44",
            "confidence": "high",
        },
        {
            "name": "Colored Pencils 50ct",
            "quantity": 1,
            "unit_price": "7.97",
            "line_total": "7.97",
            "raw_text": "CRAYOLA PENCILS 50CT 7.97",
            "confidence": "high",
        },
    ],
}

MISMATCH = {**RECONCILED, "subtotal": "160.38", "total": "164.54"}

BAD_LINE = {
    "source": "muse_ai",
    "merchant": "Walmart",
    "purchase_date": "2026-11-06",
    "purchase_time": None,
    "subtotal": "9.99",
    "tax": "0.00",
    "total": "9.99",
    "lines": [
        {
            "name": "Milk",
            "quantity": 2,
            "unit_price": "3.00",
            "line_total": "9.99",
            "raw_text": "MILK 2 @ 3.00 9.99",
            "confidence": "low",
        }
    ],
}


def _receipt_png() -> bytes:
    image = Image.new("RGB", (200, 100), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _evidence(settings):
    return preserve_upload(_receipt_png(), "test.png", settings)


def _display(evidence_id, extraction_id, lines, status, subtotal, tax, total, reconciled=True):
    return {
        "object": "pia_display",
        "version": 1,
        "kind": "receipt",
        "built_by": "muse_ai",
        "built_at": "2026-11-16T00:00:00+00:00",
        "status": status,
        "left_count": {"shown": len(lines), "total": len(lines)},
        "groups": [
            {
                "group_id": "2026-11-06-evening",
                "heading": "Thursday evening, Nov 6",
                "item_count": len(lines),
                "items": [
                    {
                        "name": line["name"],
                        "line_id": line["line_id"],
                        "raw_text": line["raw_text"],
                        "quantity": line["quantity"],
                        "unit_price": line["unit_price"],
                        "line_total": line["line_total"],
                        "image_url": None,
                        "image_source": None,
                        "image_confidence": None,
                    }
                    for line in lines
                ],
            }
        ],
        "evidence_id": evidence_id,
        "extraction_id": extraction_id,
        "merchant": "Walmart",
        "purchase_date": "2026-11-06",
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "totals_reconciled": reconciled,
    }


def _pantry_names(client):
    body = client.get("/api/pantry")
    assert body.status_code == 200
    return [item["item_name"] for item in body.json()["items"]]


def test_reconciled_ingest_auto_confirms_and_updates_pantry(client, settings):
    evidence = _evidence(settings)
    queue_receipt(settings, evidence.evidence_id)
    record, _audit, outcome = ingest_muse_extraction(settings, evidence.evidence_id, RECONCILED)
    assert outcome["status"] == "confirmed"
    assert outcome["purchase_id"]

    purchase = get_purchase_for_extraction(settings, record.extraction_id)
    assert purchase is not None
    assert purchase.purchase_id == outcome["purchase_id"]
    assert len(purchase.items) == 2

    names = _pantry_names(client)
    assert "Ground Beef 2lb" in names
    assert "Colored Pencils 50ct" in names

    body = client.get(f"/api/receipts/{evidence.evidence_id}/extraction")
    assert body.json()["confirmation_state"] == "confirmed"
    assert body.json()["purchase_id"] == outcome["purchase_id"]

    status = client.get(f"/api/receipts/{evidence.evidence_id}/muse-ai")
    assert status.json()["status"] == "done"

    # The display guard now accepts "confirmed" for this receipt.
    display = _display(
        evidence.evidence_id,
        record.extraction_id,
        [
            {
                "name": line.normalized_name_candidate,
                "line_id": line.line_id,
                "raw_text": line.raw_text,
                "quantity": line.quantity_candidate,
                "unit_price": line.unit_price_candidate,
                "line_total": line.line_total_candidate,
            }
            for line in record.lines
        ],
        "confirmed",
        "19.41",
        "4.16",
        "23.57",
    )
    stored = client.post(f"/api/receipts/{evidence.evidence_id}/muse-ai/display", json=display)
    assert stored.status_code == 200
    assert stored.json()["status"] == "confirmed"


def test_mismatch_ingest_holds_and_counts_nothing(client, settings):
    evidence = _evidence(settings)
    queue_receipt(settings, evidence.evidence_id)
    record, _audit, outcome = ingest_muse_extraction(settings, evidence.evidence_id, MISMATCH)
    assert outcome["status"] == "held"
    assert "reconcile" in outcome["reason"]

    assert get_purchase_for_extraction(settings, record.extraction_id) is None
    assert _pantry_names(client) == []

    body = client.get(f"/api/receipts/{evidence.evidence_id}/extraction")
    assert body.json()["confirmation_state"] == "unconfirmed"

    status = client.get(f"/api/receipts/{evidence.evidence_id}/muse-ai")
    assert status.json()["status"] == "done_with_mismatch"

    # A "confirmed" display is still refused while nothing is confirmed.
    # The payload itself must be valid (totals_reconciled False here),
    # so the refusal comes from the status guard, not the validator.
    display = _display(
        evidence.evidence_id,
        record.extraction_id,
        [
            {
                "name": line.normalized_name_candidate,
                "line_id": line.line_id,
                "raw_text": line.raw_text,
                "quantity": line.quantity_candidate,
                "unit_price": line.unit_price_candidate,
                "line_total": line.line_total_candidate,
            }
            for line in record.lines
        ],
        "confirmed",
        "160.38",
        "4.16",
        "164.54",
        reconciled=False,
    )
    refused = client.post(f"/api/receipts/{evidence.evidence_id}/muse-ai/display", json=display)
    assert refused.status_code == 422


def test_bad_line_holds_even_when_totals_reconcile(client, settings):
    evidence = _evidence(settings)
    queue_receipt(settings, evidence.evidence_id)
    _record, _audit, outcome = ingest_muse_extraction(settings, evidence.evidence_id, BAD_LINE)
    assert outcome["status"] == "held"
    assert _pantry_names(client) == []

    status = client.get(f"/api/receipts/{evidence.evidence_id}/muse-ai")
    assert status.json()["status"] == "held"


def test_double_ingest_confirms_once(client, settings):
    evidence = _evidence(settings)
    queue_receipt(settings, evidence.evidence_id)
    _r1, _a1, first = ingest_muse_extraction(settings, evidence.evidence_id, RECONCILED)
    assert first["status"] == "confirmed"
    _r2, _a2, second = ingest_muse_extraction(settings, evidence.evidence_id, RECONCILED)
    assert second["status"] == "already_confirmed"
    assert second["purchase_id"] == first["purchase_id"]
    assert len(_pantry_names(client)) == 2  # not doubled


def test_held_receipt_can_still_confirm_manually(client, settings):
    evidence = _evidence(settings)
    queue_receipt(settings, evidence.evidence_id)
    record, _audit, outcome = ingest_muse_extraction(settings, evidence.evidence_id, MISMATCH)
    assert outcome["status"] == "held"

    payload = {
        "evidence_id": evidence.evidence_id,
        "extraction_id": record.extraction_id,
        "merchant": "Walmart",
        "purchase_date": "2026-11-06",
        "purchase_time": None,
        "subtotal": "19.41",
        "tax": "4.16",
        "total": "23.57",
        "items": [
            {
                "source_line_id": line.line_id,
                "item_name": line.normalized_name_candidate,
                "quantity": line.quantity_candidate,
                "unit_price": line.unit_price_candidate,
                "line_total": line.line_total_candidate,
            }
            for line in record.lines
        ],
    }
    confirmed = client.post("/api/purchases", json=payload)
    assert confirmed.status_code == 201
    assert len(_pantry_names(client)) == 2


def test_queue_events_log_covers_queue_and_ingest(settings, client):
    evidence = _evidence(settings)
    queue_receipt(settings, evidence.evidence_id)
    ingest_muse_extraction(settings, evidence.evidence_id, RECONCILED)
    events = read_events(settings)
    kinds = [(event["event"], event["evidence_id"], event["status"]) for event in events]
    assert ("receipt_queued", evidence.evidence_id, "queued") in kinds
    assert ("receipt_status", evidence.evidence_id, "done") in kinds
    assert all(event["ts"] for event in events)


def test_ingest_endpoint_reports_auto_confirm(client, settings):
    evidence = _evidence(settings)
    client.post(f"/api/receipts/{evidence.evidence_id}/muse-ai")
    response = client.post(
        f"/api/receipts/{evidence.evidence_id}/muse-ai/ingest", json=RECONCILED
    )
    assert response.status_code == 200
    assert response.json()["auto_confirm"]["status"] == "confirmed"
    assert response.json()["confirmation_state"] == "confirmed"

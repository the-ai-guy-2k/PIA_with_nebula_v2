"""Tests for the Muse AI extraction loop."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.muse_ai.service import ingest_muse_extraction, queue_receipt
from app.muse_ai.validation import MusePayloadError, validate_muse_payload
from app.receipt_intake.service import preserve_upload

GOOD = {
    "source": "muse_ai",
    "merchant": "Walmart",
    "purchase_date": "2026-11-06",
    "purchase_time": None,
    "subtotal": "160.38",
    "tax": "4.16",
    "total": "164.54",
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


def _receipt_png() -> bytes:
    image = Image.new("RGB", (200, 100), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _evidence(settings):
    return preserve_upload(_receipt_png(), "test.png", settings)


def test_good_payload_reconciles():
    result = validate_muse_payload({**GOOD, "subtotal": "19.41", "total": "23.57"})
    assert result.totals_reconciled is True
    assert result.total_mismatch is False
    assert result.lines_sum == "19.41"


def test_line_total_mismatch_is_flagged_not_fixed():
    payload = dict(GOOD)
    payload["lines"] = [
        {
            "name": "Milk",
            "quantity": 2,
            "unit_price": "3.00",
            "line_total": "9.99",
            "raw_text": "MILK 2 @ 3.00 9.99",
            "confidence": "low",
        }
    ]
    result = validate_muse_payload(payload)
    assert result.lines[0].line_total == "9.99"  # kept as read, never fixed
    assert result.lines[0].line_total_ok is False
    assert result.flags, "mismatch must be flagged"


def test_subtotal_mismatch_is_flagged_not_fixed():
    result = validate_muse_payload(GOOD)  # lines sum 19.41 vs subtotal 160.38
    assert result.total_mismatch is True
    assert result.totals_reconciled is False
    assert result.subtotal == "160.38"


def test_unknown_fields_stay_null():
    result = validate_muse_payload({"lines": []})
    assert result.merchant is None
    assert result.total is None
    assert result.lines == ()


def test_bad_money_is_rejected():
    with pytest.raises(MusePayloadError):
        validate_muse_payload({"total": "about tree fiddy", "lines": []})
    with pytest.raises(MusePayloadError):
        validate_muse_payload({"lines": [{"name": "x", "line_total": None}]})
    with pytest.raises(MusePayloadError):
        validate_muse_payload("not an object")


def test_queue_ingest_review_flow(settings, client):
    evidence = _evidence(settings)
    queue_receipt(settings, evidence.evidence_id)
    record, audit = ingest_muse_extraction(settings, evidence.evidence_id, GOOD)
    assert audit.total_mismatch is True  # lines sum 19.41 vs stated 160.38
    assert audit.lines_sum == "19.41"

    response = client.get(f"/api/receipts/{evidence.evidence_id}/extraction")
    assert response.status_code == 200
    body = response.json()
    assert body["confirmation_state"] == "unconfirmed"
    assert body["merchant_normalized_candidate"] == "Walmart"
    assert len(body["lines"]) == 2
    assert body["total_candidate"] == "164.54"

    status = client.get(f"/api/receipts/{evidence.evidence_id}/muse-ai")
    assert status.status_code == 200
    assert status.json()["status"] == "done_with_mismatch"
    assert status.json()["total_mismatch"] is True


def test_muse_ai_endpoints(settings, client):
    evidence = _evidence(settings)
    queued = client.post(f"/api/receipts/{evidence.evidence_id}/muse-ai")
    assert queued.status_code == 202
    assert queued.json()["source"] == "muse_ai"

    bad = client.post(
        f"/api/receipts/{evidence.evidence_id}/muse-ai/ingest",
        json={"total": "nope", "lines": []},
    )
    assert bad.status_code == 422

    good = client.post(
        f"/api/receipts/{evidence.evidence_id}/muse-ai/ingest",
        json={**GOOD, "subtotal": "19.41", "total": "23.57"},
    )
    assert good.status_code == 200
    assert good.json()["muse_ai"]["totals_reconciled"] is True
    assert good.json()["confirmation_state"] == "unconfirmed"

    missing = client.post("/api/receipts/does-not-exist/muse-ai")
    assert missing.status_code == 404

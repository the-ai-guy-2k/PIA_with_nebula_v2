"""Tests for the Muse display object contract (validation + endpoints)."""

from __future__ import annotations

import pytest

from app.muse_ai.display import DisplayPayloadError, validate_display_payload


def _receipt_item(**over):
    item = {
        "line_id": "line-1",
        "name": "Ivory Gentle Body Wash",
        "raw_text": "IVORY BW OR 030772018460 6.97 X",
        "upc": "030772018460",
        "quantity": "1",
        "unit_price": "6.97",
        "line_total": "6.97",
        "image_url": "https://images.openbeautyfacts.org/images/products/003/077/201/8460/front_en.3.400.jpg",
        "image_source": "open_beauty_facts",
        "image_confidence": "high",
    }
    item.update(over)
    return item


def _receipt(**over):
    obj = {
        "object": "pia_display",
        "version": 1,
        "kind": "receipt",
        "evidence_id": "935fac61-bfe6-47e3-a349-505cddb854e4",
        "extraction_id": "3366eb7f-d83c-465e-ae91-e086c19c87ae",
        "merchant": "Walmart",
        "purchase_date": "2026-11-06",
        "purchase_time": None,
        "subtotal": "160.38",
        "tax": "4.16",
        "total": "164.54",
        "totals_reconciled": False,
        "status": "unconfirmed",
        "search_placeholder": "Find something...",
        "left_count": {"shown": 1, "total": 1},
        "groups": [
            {
                "group_id": "2026-11-06-afternoon",
                "heading": "Thursday afternoon, Nov 6",
                "item_count": 1,
                "items": [_receipt_item()],
            }
        ],
        "built_by": "muse_ai",
        "built_at": "2026-11-09T01:55:00+00:00",
    }
    obj.update(over)
    return obj


def test_receipt_totals_must_reconcile_honestly():
    # 1 line of $6.97 does not sum to a $160.38 subtotal, so claiming
    # totals_reconciled=True must be rejected.
    with pytest.raises(DisplayPayloadError, match="totals_reconciled"):
        validate_display_payload(_receipt(totals_reconciled=True))


def test_receipt_valid_when_totals_match():
    obj = _receipt(subtotal="6.97", tax="0.00", total="6.97", totals_reconciled=True)
    out = validate_display_payload(obj)
    assert out["totals_reconciled"] is True
    assert out["groups"][0]["items"][0]["name"] == "Ivory Gentle Body Wash"


def test_line_total_must_equal_qty_x_price():
    with pytest.raises(DisplayPayloadError, match="line_total"):
        validate_display_payload(
            _receipt(
                subtotal="6.97",
                tax="0.00",
                total="6.97",
                totals_reconciled=True,
                groups=[
                    {
                        "group_id": "g",
                        "heading": "Thursday afternoon, Nov 6",
                        "item_count": 1,
                        "items": [_receipt_item(line_total="9.99")],
                    }
                ],
            )
        )


def test_image_url_must_be_plain_https():
    with pytest.raises(DisplayPayloadError, match="image_url"):
        validate_display_payload(
            _receipt(
                subtotal="6.97",
                tax="0.00",
                total="6.97",
                totals_reconciled=True,
                groups=[
                    {
                        "group_id": "g",
                        "heading": "Thursday afternoon, Nov 6",
                        "item_count": 1,
                        "items": [_receipt_item(image_url="http://example.invalid/x.jpg")],
                    }
                ],
            )
        )


def test_image_null_needs_no_source():
    obj = _receipt(
        subtotal="6.97",
        tax="0.00",
        total="6.97",
        totals_reconciled=True,
        groups=[
            {
                "group_id": "g",
                "heading": "Thursday afternoon, Nov 6",
                "item_count": 1,
                "items": [
                    _receipt_item(image_url=None, image_source=None, image_confidence=None)
                ],
            }
        ],
    )
    out = validate_display_payload(obj)
    assert out["groups"][0]["items"][0]["image_url"] is None


def test_pantry_left_count_is_in_stock_count():
    obj = {
        "object": "pia_display",
        "version": 1,
        "kind": "pantry",
        "evidence_id": None,
        "extraction_id": None,
        "merchant": None,
        "purchase_date": None,
        "purchase_time": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "totals_reconciled": None,
        "status": "unconfirmed",
        "search_placeholder": "Find something...",
        "left_count": {"shown": 1, "total": 1},
        "groups": [
            {
                "group_id": "2026-11-04-evening",
                "heading": "Wednesday night, Nov 4",
                "item_count": 2,
                "items": [
                    {
                        "pantry_item_id": "p1",
                        "name": "Bread Loaf",
                        "qty_on_hand": "1",
                        "pantry_status": "in_stock",
                        "image_url": None,
                        "image_source": None,
                        "image_confidence": None,
                    },
                    {
                        "pantry_item_id": "p2",
                        "name": "Milk",
                        "qty_on_hand": "1",
                        "pantry_status": "used",
                        "image_url": None,
                        "image_source": None,
                        "image_confidence": None,
                    },
                ],
            }
        ],
        "built_by": "muse_ai",
        "built_at": "2026-11-09T01:55:00+00:00",
    }
    out = validate_display_payload(obj)
    assert out["left_count"] == {"shown": 1, "total": 1}
    with pytest.raises(DisplayPayloadError, match="left_count"):
        validate_display_payload({**obj, "left_count": {"shown": 2, "total": 2}})


def test_endpoints_store_and_serve(client):
    pantry = {
        "object": "pia_display",
        "version": 1,
        "kind": "pantry",
        "evidence_id": None,
        "extraction_id": None,
        "merchant": None,
        "purchase_date": None,
        "purchase_time": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "totals_reconciled": None,
        "status": "unconfirmed",
        "search_placeholder": "Find something...",
        "left_count": {"shown": 1, "total": 1},
        "groups": [
            {
                "group_id": "2026-11-04-evening",
                "heading": "Wednesday night, Nov 4",
                "item_count": 1,
                "items": [
                    {
                        "pantry_item_id": "p1",
                        "name": "Bread Loaf",
                        "qty_on_hand": "1",
                        "pantry_status": "in_stock",
                        "image_url": None,
                        "image_source": None,
                        "image_confidence": None,
                    }
                ],
            }
        ],
        "built_by": "muse_ai",
        "built_at": "2026-11-09T01:55:00+00:00",
    }
    response = client.post("/api/display/pantry", json=pantry)
    assert response.status_code == 200
    latest = client.get("/api/display/latest", params={"kind": "pantry"})
    assert latest.status_code == 200
    assert latest.json()["groups"][0]["heading"] == "Wednesday night, Nov 4"
    missing = client.get("/api/display/latest", params={"kind": "receipt"})
    assert missing.status_code == 404


def test_receipt_display_needs_extraction(client):
    response = client.post(
        "/api/receipts/nope/muse-ai/display", json=_receipt(subtotal="6.97", tax="0.00", total="6.97", totals_reconciled=True)
    )
    assert response.status_code == 404

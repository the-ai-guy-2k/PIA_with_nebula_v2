"""PIA backend phase 1 (Nov 4, 2026 lock): pantry + correction log + aliases.

Runs against REAL Tesseract OCR (installed in CI and in the Dockerfile):
the test renders a receipt image with DejaVu Bold text, uploads it, and
lets Tesseract read it back. No stubbed OCR, no fake green.
"""

from __future__ import annotations

import io
import subprocess

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.receipt_intake.repository import read_original_bytes

RECEIPT_LINES = [
    "NORTH MARKET",
    "2026-03-15 2:32 PM",
    "Milk Gallon 3.42",
    "Bread Loaf 2.19",
    "Subtotal 5.61",
    "Tax 0.00",
    "Total 5.61",
]


def _png() -> bytes:
    """Render RECEIPT_LINES as a real receipt image for real OCR."""
    font_path = subprocess.check_output(
        ["fc-match", "-f", "%{file}", "DejaVu Sans:style=Bold"], timeout=5
    ).decode("utf-8")
    font = ImageFont.truetype(font_path, 56)
    width = 1200
    line_height = 90
    image = Image.new("RGB", (width, 140 + line_height * len(RECEIPT_LINES)), "white")
    draw = ImageDraw.Draw(image)
    y = 60
    for line in RECEIPT_LINES:
        draw.text((70, y), line, fill="black", font=font)
        y += line_height
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _confirm_payload(extraction: dict) -> dict:
    return {
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


def test_backend_phase1_flow(client: TestClient, settings):
    original = _png()
    intake = client.post("/api/receipts", files={"file": ("receipt.png", original, "image/png")})
    assert intake.status_code == 201, intake.text
    evidence_id = intake.json()["evidence_id"]

    # Analytics must be empty before any confirmation.
    assert client.get("/api/analytics/weekly").json()["weekly_spending"] == {}
    assert client.get("/api/pantry").json()["items"] == []

    # Extract via the locked alias; original image must be unchanged.
    extraction_resp = client.post(f"/api/receipts/{evidence_id}/extract")
    assert extraction_resp.status_code == 200, extraction_resp.text
    extraction = extraction_resp.json()
    assert extraction["extraction_status"] == "extracted"
    assert extraction["confirmation_state"] == "unconfirmed"
    assert len(extraction["lines"]) == 2
    by_id = client.get(f"/api/extractions/{extraction['extraction_id']}")
    assert by_id.status_code == 200

    # Correction: Milk Gallon -> Milk, recorded, extraction untouched.
    milk_line = extraction["lines"][0]
    correction = client.post(
        f"/api/extractions/{extraction['extraction_id']}/correct",
        json={"item_id": milk_line["line_id"], "field": "name", "corrected_value": "Milk"},
    )
    assert correction.status_code == 201, correction.text
    body = correction.json()
    assert body["original_value"] == "Milk Gallon"
    assert body["corrected_value"] == "Milk"
    assert body["pattern_key"] == "name:milk gallon"
    reread = client.get(f"/api/extractions/{extraction['extraction_id']}").json()
    assert reread["lines"][0]["normalized_name_candidate"] == "Milk Gallon"
    assert reread["corrections"][0]["corrected_value"] == "Milk"

    # Confirm with the corrected name: purchase uses corrected truth.
    payload = _confirm_payload(extraction)
    payload["items"][0]["item_name"] = "Milk"
    confirm = client.post("/api/purchases/confirm", json=payload)
    assert confirm.status_code == 201, confirm.text
    purchase = confirm.json()
    assert purchase["items"][0]["item_name"] == "Milk"
    assert len(purchase["pantry_items"]) == 2

    # Purchase read carries applied corrections.
    purchase_read = client.get(f"/api/purchases/{purchase['purchase_id']}").json()
    assert purchase_read["applied_corrections"][0]["corrected_value"] == "Milk"

    # Pantry: in_stock, then Used, then Gone; history kept, never deleted.
    pantry = client.get("/api/pantry").json()["items"]
    assert len(pantry) == 2
    milk = next(item for item in pantry if item["item_name"] == "Milk")
    assert milk["status"] == "in_stock" and milk["low"] is True  # qty 1, in stock => low
    used = client.post(
        f"/api/pantry/{milk['pantry_item_id']}/status", json={"status": "used"}
    ).json()
    assert used["status"] == "used"
    gone = client.post(
        f"/api/pantry/{milk['pantry_item_id']}/status", json={"status": "gone"}
    ).json()
    assert gone["status"] == "gone" and gone["qty_on_hand"] == 0
    history = client.get(f"/api/pantry/{milk['pantry_item_id']}").json()["history"]
    assert [entry["to_status"] for entry in history] == ["in_stock", "used", "gone"]

    # Manual add item.
    added = client.post("/api/pantry", json={"item_name": "Rice", "quantity": "1"})
    assert added.status_code == 201
    assert added.json()["low"] is True  # qty 1, in stock => low

    # Analytics now reflect only the confirmed purchase.
    weekly = client.get("/api/analytics/weekly").json()["weekly_spending"]
    assert weekly == {"2026-W11": 5.61}
    most = client.get("/api/analytics/most-bought").json()["most_bought"]
    assert {item["item_name"] for item in most} == {"Milk", "Bread Loaf"}

    # Second receipt: same raw name proposes the user's correction, unconfirmed.
    intake2 = client.post("/api/receipts", files={"file": ("receipt2.png", original, "image/png")})
    extraction2 = client.post(f"/api/receipts/{intake2.json()['evidence_id']}/extract").json()
    suggestions = extraction2["suggestions"]["lines"]
    assert any(
        s["field"] == "name" and s["suggested_value"] == "Milk" and s["from_your_correction"]
        for s in suggestions
    )
    assert extraction2["confirmation_state"] == "unconfirmed"
    assert read_original_bytes(settings, intake.json()["storage_reference"]) == original

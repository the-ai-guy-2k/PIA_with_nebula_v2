"""ACI-002 extraction candidates from preserved receipt evidence."""

from __future__ import annotations

import io
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.receipt_extraction.parser import parse_receipt_text
from app.receipt_intake.repository import get_evidence, read_original_bytes

RECEIPT_LINES = [
    "NORTH MARKET",
    "2026-03-15 2:32 PM",
    "Milk Gallon 3.42",
    "Bread Loaf 2.19",
    "Eggs Large 2 @ 2.04 4.08",
    "Subtotal 9.69",
    "Tax 0.78",
    "Total 10.47",
]


def test_parser_reads_merchant_items_date_and_total():
    parsed = parse_receipt_text(RECEIPT_LINES)

    assert parsed.extraction_status == "extracted"
    assert parsed.merchant_raw == "NORTH MARKET"
    assert parsed.merchant_normalized_candidate == "North Market"
    assert parsed.purchase_date_candidate == "2026-03-15"
    assert parsed.purchase_time_candidate == "14:32:00"
    assert parsed.subtotal_candidate == "9.69"
    assert parsed.tax_candidate == "0.78"
    assert parsed.total_candidate == "10.47"
    assert [line.normalized_name_candidate for line in parsed.lines] == [
        "Milk Gallon",
        "Bread Loaf",
        "Eggs Large",
    ]
    assert [line.line_total_candidate for line in parsed.lines] == ["3.42", "2.19", "4.08"]
    assert parsed.lines[2].quantity_candidate == "2"
    assert parsed.lines[2].unit_price_candidate == "2.04"
    assert parsed.lines[0].raw_text == "Milk Gallon 3.42"
    assert parsed.lines[0].raw_text != parsed.lines[0].normalized_name_candidate
    assert "Milk Gallon 3.42" in parsed.raw_text


def test_parser_preserves_line_order_and_does_not_invent_values():
    parsed = parse_receipt_text(
        [
            "NORTH MARKET",
            "Milk Gallon 3.42",
            "Bread Loaf 2.19",
            "Eggs Large 2 @ 2.04",
            "Total 10.47",
        ]
    )

    assert [line.raw_text for line in parsed.lines] == [
        "Milk Gallon 3.42",
        "Bread Loaf 2.19",
        "Eggs Large 2 @ 2.04",
    ]
    assert parsed.lines[0].quantity_candidate is None
    assert parsed.lines[2].quantity_candidate == "2"
    assert parsed.lines[2].unit_price_candidate == "2.04"
    assert parsed.lines[2].line_total_candidate is None
    assert parsed.total_candidate == "10.47"
    assert parsed.subtotal_candidate is None


def test_parser_leaves_ambiguous_amounts_unresolved():
    parsed = parse_receipt_text(["NORTH MARKET", "Milk $3.O9", "Total e. 78"])

    assert parsed.lines[0].raw_text == "Milk $3.O9"
    assert parsed.lines[0].normalized_name_candidate == "Milk"
    assert parsed.lines[0].line_total_candidate is None
    assert parsed.total_candidate is None
    assert "Milk $3.O9" in parsed.raw_text


def test_parser_rejects_impossible_dates_and_does_not_invent_items():
    parsed = parse_receipt_text(["@@@", "2026-02-31", "03115/2026"])

    assert parsed.purchase_date_candidate is None
    assert parsed.merchant_raw is None
    assert parsed.lines == ()
    assert parsed.extraction_status == "insufficient_data"


def test_parser_no_text_creates_nothing():
    parsed = parse_receipt_text(["  ", ""])

    assert parsed.extraction_status == "no_text"
    assert parsed.merchant_raw is None
    assert parsed.total_candidate is None
    assert parsed.lines == ()


def test_parser_keeps_path_like_text_as_text():
    parsed = parse_receipt_text(["NORTH MARKET", r"..\..\secret 1.00"])

    assert parsed.lines[0].raw_text == r"..\..\secret 1.00"
    assert parsed.lines[0].line_total_candidate == "1.00"


def receipt_png(lines: list[str]) -> bytes:
    font_path = (
        r"C:\Windows\Fonts\arialbd.ttf" if sys.platform == "win32"
        else subprocess.check_output(
            ["fc-match", "-f", "%{file}", "DejaVu Sans:style=Bold"], timeout=5
        ).decode("utf-8")
    )
    font = ImageFont.truetype(font_path, 56)
    width = 1200
    line_height = 90
    image = Image.new("RGB", (width, 140 + line_height * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    y = 60
    for line in lines:
        draw.text((70, y), line, fill="black", font=font)
        y += line_height
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def blank_png() -> bytes:
    image = Image.new("RGB", (500, 240), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def upload_png(client: TestClient, content: bytes, filename: str = "receipt.png") -> dict:
    response = client.post("/api/receipts", files={"file": (filename, content, "image/png")})
    assert response.status_code == 201, response.text
    return response.json()


def extraction_count(settings) -> int:
    with sqlite3.connect(settings.extraction_db_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM receipt_extraction").fetchone()[0]


def test_readable_receipt_extracts_linked_candidate(client: TestClient, settings):
    original = receipt_png(RECEIPT_LINES)
    evidence = upload_png(client, original)
    before = read_original_bytes(settings, evidence["storage_reference"])

    response = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction")
    body = response.json()

    assert response.status_code == 200, body
    assert body["evidence_id"] == evidence["evidence_id"]
    assert body["extraction_status"] == "extracted"
    assert body["merchant_raw"] and "NORTH" in body["merchant_raw"].upper()
    assert body["merchant_normalized_candidate"]
    assert len(body["lines"]) >= 3
    assert all(line["raw_text"] for line in body["lines"])
    assert read_original_bytes(settings, evidence["storage_reference"]) == before == original
    saved = get_evidence(settings, evidence["evidence_id"])
    assert saved is not None
    assert saved.byte_size == evidence["byte_size"]
    assert saved.original_filename == evidence["original_filename"]


def test_multiple_items_keep_order_and_raw_text(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    body = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction").json()
    names = [line["normalized_name_candidate"] for line in body["lines"]]

    assert names[:3] == ["Milk Gallon", "Bread Loaf", "Eggs Large"]
    assert [line["line_order"] for line in body["lines"]] == list(range(1, len(body["lines"]) + 1))
    for line in body["lines"]:
        assert line["raw_text"]
        assert line["raw_text"] != line["normalized_name_candidate"]
    eggs = body["lines"][2]
    assert eggs["raw_text"].startswith("Eggs Large")
    assert eggs["quantity_candidate"] == "2"
    assert eggs["unit_price_candidate"] == "2.04"
    assert eggs["line_total_candidate"] == "4.08"


def test_date_and_total_are_structured(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    body = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction").json()

    assert body["purchase_date_candidate"] == "2026-03-15"
    assert body["purchase_time_candidate"] == "14:32:00"
    assert body["total_candidate"] == "10.47"
    assert body["subtotal_candidate"] == "9.69"
    assert body["tax_candidate"] == "0.78"
    assert isinstance(body["total_candidate"], str)


def test_unknown_evidence_creates_no_extraction(client: TestClient, settings):
    missing = "11111111-1111-4111-8111-111111111111"
    response = client.post(f"/api/receipts/{missing}/extraction")

    assert response.status_code == 404
    assert response.json()["status"] == "not_found"
    assert "traceback" not in response.text.lower()
    assert extraction_count(settings) == 0


def test_corrupt_evidence_fails_without_changing_the_file(client: TestClient, settings):
    evidence = upload_png(client, receipt_png(RECEIPT_LINES))
    stored = Path(read_path(settings, evidence["storage_reference"]))
    stored.write_bytes(b"this is not a readable image")
    before = stored.read_bytes()

    response = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction")
    body = response.json()

    assert response.status_code == 422
    assert body["extraction_status"] == "failed"
    assert body["failure_reason"] == "The preserved receipt image could not be read."
    assert body["lines"] == []
    assert stored.read_bytes() == before
    assert get_evidence(settings, evidence["evidence_id"]) is not None


def test_blank_receipt_does_not_invent_content(client: TestClient, settings):
    evidence = upload_png(client, blank_png(), "blank.png")
    response = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction")
    body = response.json()

    assert response.status_code == 200, body
    assert body["extraction_status"] in {"no_text", "insufficient_data"}
    assert body["merchant_raw"] is None
    assert body["merchant_normalized_candidate"] is None
    assert body["purchase_date_candidate"] is None
    assert body["total_candidate"] is None
    assert body["lines"] == []


def test_rerun_replaces_the_unconfirmed_extraction(client: TestClient, settings):
    original = receipt_png(RECEIPT_LINES)
    evidence = upload_png(client, original)
    reference = evidence["storage_reference"]
    before = read_original_bytes(settings, reference)

    first = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction").json()
    second = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction").json()
    saved = client.get(f"/api/receipts/{evidence['evidence_id']}/extraction").json()

    assert first["extraction_id"] != second["extraction_id"]
    assert saved["extraction_id"] == second["extraction_id"]
    assert extraction_count(settings) == 1
    assert saved["total_candidate"] == "10.47"
    assert read_original_bytes(settings, reference) == before == original


def test_extraction_page_is_available(client: TestClient):
    page = client.get("/intake")
    script = client.get("/static/app.js")

    assert "Extract receipt" in page.text
    assert "innerHTML" not in script.text
    assert "extractEvidence" in script.text


def read_path(settings, storage_reference: str) -> Path:
    name = storage_reference.split("/")[-1]
    return settings.files_dir / name

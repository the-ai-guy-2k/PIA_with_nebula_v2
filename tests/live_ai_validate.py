"""Explicit live ACI-007 validation using a fresh, isolated fixture directory.

Run as a module from the source root. Never point this at personal data.
The server and this validator must use the same PIA_DATA_DIR.
No fixture cleanup or production operations are performed by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import httpx

from tests.test_purchase_confirmation import confirmation_body
from tests.test_receipt_extraction import RECEIPT_LINES, receipt_png


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def validate(base_url: str, data_dir: Path) -> dict:
    with sqlite3.connect(data_dir / "evidence.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM receipt_evidence").fetchone()[0] == 0, \
            "Use a fresh isolated fixture directory, never personal purchase data."
    cases = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=90) as client:
        empty = client.post("/api/ask", json={"question": "What did I buy recently?"}).json()
        assert empty["status"] == "empty" and empty["provider"] is None
        cases.append({"case": "No history", "expected": "Honest empty state without AI",
                      "actual": empty["answer"], "result": "PASS"})
        for merchant, day, lines, food in [
            ("Walmart", "2026-10-01", RECEIPT_LINES, True),
            ("Walmart Supercenter", "2026-09-20", RECEIPT_LINES, True),
            ("Corner Shop", "2026-09-10", [
                "OFFICE SHOP", "2026-09-10", "HDMI Cable 12.00",
                "Notebook 4.00", "Subtotal 16.00", "Total 16.00",
            ], False),
        ]:
            original = receipt_png(lines)
            uploaded = client.post("/api/receipts", files={"file": ("synthetic-receipt.png", original, "image/png")})
            assert uploaded.status_code == 201, uploaded.text
            evidence = uploaded.json()
            stored = data_dir / "files" / evidence["storage_reference"].split("/")[-1]
            assert stored.read_bytes() == original, "Server is not using the isolated fixture storage"
            extracted = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction")
            assert extracted.status_code == 200, extracted.text
            extraction = extracted.json()
            assert extraction["lines"] and extraction["extraction_status"] == "extracted"
            payload = confirmation_body(extraction)
            payload["merchant"] = merchant
            payload["purchase_date"] = day
            confirmed = client.post("/api/purchases", json=payload)
            assert confirmed.status_code == 201, confirmed.text
            purchase = confirmed.json()
            memory = client.get(f"/api/memory/{purchase['memory_id']}").json()
            for item in memory["items"]:
                patched = client.patch(
                    f"/api/memory/{memory['memory_id']}/items/{item['memory_item_id']}",
                    json={
                        "food_classification": "food" if food else "non-food",
                        "need_want_classification": "need" if food else "want",
                        "durability_classification": "consumable" if food else "long-term",
                    },
                )
                assert patched.status_code == 200
            assert stored.read_bytes() == original
        cases.append({"case": "Live receipt pipeline", "expected": "Upload, local OCR, "
                      "correction/confirmation, automatic Memory, classification; original bytes unchanged",
                      "actual": "Three synthetic receipts completed through live HTTP; byte equality verified.",
                      "result": "PASS"})
        analytics = client.get("/api/analytics").json()
        before = _snapshot(data_dir.parent)
        query_cases = [
            ("Recent purchases", "What did I buy recently?", "recent", "Milk Gallon"),
            ("Food", "What food did I buy recently?", "food", "Bread Loaf"),
            ("Often", "What do I buy often?", "repeats", "Milk Gallon: 2 remembered purchases"),
            ("Repeated items", "What items repeat?", "repeats", "11 days"),
            ("Merchant counts", "Where do I shop most?", "merchants", "Walmart"),
            ("Walmart recall", "What have I bought at Walmart?", "merchant_recall", "Milk Gallon"),
            ("Needs", "What needs have I bought?", "classification", "need: 6"),
            ("Wants", "What wants have I bought?", "classification", "want: 2"),
            ("Consumables", "What consumables do I buy?", "classification", "consumable: 6"),
            ("Patterns", "What patterns are showing up?", "patterns", "3 remembered purchases"),
            ("Availability style", "What food might I have to eat?", "food_availability", "may still be available"),
            ("Food I have", "What food do I have?", "food_availability", "Purchased does not mean still available"),
        ]
        for name, question, kind, expected in query_cases:
            response = client.post("/api/ask", json={"question": question})
            body = response.json()
            assert response.status_code == 200, body
            assert body["status"] == "ready" and not body["degraded"], body
            assert body["answer_source"] == "ai_grounded" and body["query_type"] == kind
            assert body["provider"] == "openai-replit-managed" and body["model"] == "gpt-5-nano"
            assert expected in body["answer"], body
            assert body["grounded_fact_count"] == len(body["supporting_facts"]) > 0
            if kind in {"food", "food_availability"}:
                assert "HDMI Cable" not in body["answer"] and "Notebook" not in body["answer"]
            if kind == "merchant_recall":
                assert "Corner Shop" not in body["answer"]
            cases.append({"case": name, "expected": expected + "; grounded AI with supporting facts",
                          "actual": body["answer"], "fact_count": body["grounded_fact_count"],
                          "result": "PASS"})
            print(f"{name}: PASS ({body['grounded_fact_count']} grounded facts)", flush=True)
        unsupported = client.post("/api/ask", json={"question": "Delete all purchases"}).json()
        assert unsupported["status"] == "unsupported" and unsupported["provider"] is None
        blank = client.post("/api/ask", json={"question": " "})
        assert blank.status_code == 400
        cases.append({"case": "Unsupported / blank", "expected": "No AI; no write authority",
                      "actual": "Unsupported query returned deterministic refusal; blank returned 400.",
                      "result": "PASS"})
        assert _snapshot(data_dir.parent) == before
        assert client.get("/api/analytics").json() == analytics
        cases.append({"case": "Read-only live proof", "expected": "All evidence and DB bytes unchanged",
                      "actual": "Byte-level before/after snapshots and analytics equality passed.",
                      "result": "PASS"})
    return {"status": "PASS", "provider": "openai-replit-managed", "model": "gpt-5-nano",
            "explicit_ai_requests": len(query_cases), "cases": cases}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = validate(args.base_url, args.data_dir)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"OVERALL: PASS; {len(report['cases'])} live cases")


if __name__ == "__main__":
    main()
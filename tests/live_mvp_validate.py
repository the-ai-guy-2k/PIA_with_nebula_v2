"""Bounded ACI-008 fixture preparation: real HTTP/OCR, zero model calls.

Use only with a fresh isolated PIA_DATA_DIR. The focused browser pass completes
the UI journey and exactly two real AI queries after these fixtures are ready.
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


def prepare(base_url: str, data_dir: Path, browser_image: Path) -> dict:
    with sqlite3.connect(data_dir / "evidence.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM receipt_evidence").fetchone()[0] == 0, \
            "Fresh isolated storage is required; never seed personal purchase data."
    proofs = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=90) as client:
        assert client.get("/api/memory").json()["purchases"] == []
        assert client.get("/api/analytics").json()["status"] == "empty"
        empty = client.post("/api/ask", json={"question": "What do I buy often?"}).json()
        assert empty["status"] == "empty" and empty["provider"] is None
        browser_image.parent.mkdir(parents=True, exist_ok=True)
        browser_image.write_bytes(receipt_png(RECEIPT_LINES))
        for day in ["2026-10-01", "2026-09-20"]:
            original = receipt_png(RECEIPT_LINES)
            uploaded = client.post("/api/receipts", files={
                "file": ("synthetic-aci008.png", original, "image/png"),
            })
            assert uploaded.status_code == 201, uploaded.text
            evidence = uploaded.json()
            stored = data_dir / "files" / evidence["storage_reference"].split("/")[-1]
            assert stored.read_bytes() == original, "Runtime isolation mismatch."
            extracted = client.post(f"/api/receipts/{evidence['evidence_id']}/extraction")
            assert extracted.status_code == 200, extracted.text
            body = extracted.json()
            assert body["extraction_status"] == "extracted" and body["lines"]
            correction = confirmation_body(body)
            correction["merchant"] = "Walmart"
            correction["purchase_date"] = day
            confirmed = client.post("/api/purchases", json=correction)
            assert confirmed.status_code == 201, confirmed.text
            purchase = confirmed.json()
            memory = client.get(f"/api/memory/{purchase['memory_id']}").json()
            assert memory["status"] == "remembered"
            for item in memory["items"]:
                response = client.patch(
                    f"/api/memory/{memory['memory_id']}/items/{item['memory_item_id']}",
                    json={
                        "food_classification": "food",
                        "need_want_classification": "need",
                        "durability_classification": "consumable",
                    },
                )
                assert response.status_code == 200
            assert stored.read_bytes() == original
            proofs.append({
                "evidence_id": evidence["evidence_id"],
                "purchase_id": purchase["purchase_id"],
                "memory_id": memory["memory_id"],
                "original_sha256": hashlib.sha256(original).hexdigest(),
                "stored_sha256": hashlib.sha256(stored.read_bytes()).hexdigest(),
            })
        analytics = client.get("/api/analytics").json()
        assert analytics["summary"]["remembered_purchases"] == 2
        assert analytics["summary"]["repeating_items"] == 3
        assert analytics["classifications"]["food"]["food"] == 6
        assert analytics["classifications"]["need_want"]["need"] == 6
        assert all(item["occurrence_count"] == 2 for item in analytics["repeat_items"])
        recall = client.get("/api/visual-recall?view=all").json()
        assert recall["items"]
        assert all(item["display"] in {"exact", "representative", "text-only"} for item in recall["items"])
    return {
        "status": "PASS",
        "real_model_calls": 0,
        "pipeline": "upload/local OCR/correction/confirmation/Memory/classification",
        "purchase_count": 2,
        "repeat_item_identities": 3,
        "food_item_records": 6,
        "evidence_proofs": proofs,
        "browser_image": str(browser_image),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--browser-image", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = prepare(args.base_url, args.data_dir, args.browser_image)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("ACI-008 live fixture preparation: PASS; real model calls: 0")


if __name__ == "__main__":
    main()
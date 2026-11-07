"""CLI for Tim's SSH poll of the Muse AI queue.

Run inside the PIA container (or with PIA_DATA_DIR set):

  python -m app.muse_ai.cli list
  python -m app.muse_ai.cli show <evidence_id>
  python -m app.muse_ai.cli ingest <evidence_id> <extraction.json>

`list` shows queued receipts waiting for Muse to read them.
`ingest` validates a Muse extraction JSON and stores it as the receipt's
current unconfirmed extraction. It never confirms a purchase.
"""

from __future__ import annotations

import json
import sys

from app.config import load_settings
from app.muse_ai import queue as queue_mod
from app.muse_ai.service import ingest_muse_extraction, queue_status
from app.muse_ai.validation import MusePayloadError
from app.receipt_extraction.errors import EvidenceNotFound


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    settings = load_settings()
    command = argv[0]
    if command == "list":
        records = queue_mod.list_records(settings)
        if not records:
            print("queue empty")
            return 0
        for record in records:
            print(f"{record.evidence_id}  {record.status}  queued {record.queued_at}")
        return 0
    if command == "show":
        if len(argv) != 2:
            print("usage: show <evidence_id>")
            return 2
        record = queue_status(settings, argv[1])
        if record is None:
            print("not queued")
            return 1
        print(json.dumps(record.to_public_dict(), indent=2))
        return 0
    if command == "ingest":
        if len(argv) != 3:
            print("usage: ingest <evidence_id> <extraction.json>")
            return 2
        evidence_id, json_path = argv[1], argv[2]
        try:
            payload = json.loads(open(json_path, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"cannot read extraction file: {exc}")
            return 2
        try:
            record, audit = ingest_muse_extraction(settings, evidence_id, payload)
        except EvidenceNotFound:
            print("evidence not found")
            return 1
        except MusePayloadError as exc:
            print(f"extraction rejected: {exc}")
            return 1
        print(f"stored extraction {record.extraction_id} for {evidence_id}")
        print(f"lines={len(record.lines)} totals_reconciled={audit.totals_reconciled} "
              f"total_mismatch={audit.total_mismatch} lines_sum=${audit.lines_sum}")
        return 0
    print(f"unknown command {command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

# PIA — Muse AI Connection ("hood AI")

Muse (Tim) reads a receipt photo and returns a structured extraction.
No OpenAI, no outside AI API bill — Muse is the AI.

## The loop

```
phone snaps receipt
  → POST /api/receipts (image) → evidence id, original preserved unchanged
  → POST /api/receipts/{id}/muse-ai → queued
  → Tim polls the queue over SSH (see below)
  → Tim reads the preserved receipt image with Muse vision
  → Tim writes extraction JSON, ingests it:
      python -m app.muse_ai.cli ingest <evidence_id> <extraction.json>
      (or POST /api/receipts/{id}/muse-ai/ingest)
  → extraction becomes the receipt's current UNCONFIRMED candidate
  → Review & Confirm screen shows it (same screen as OCR extractions)
  → user Confirms → purchase + pantry update. No confirm = nothing counts.
```

## Tim's poll (cron, main chat)

Every 15 minutes while receipts are queued:

1. SSH to the Droplet, `docker exec pia python -m app.muse_ai.cli list`
   (or run the CLI against the container — the queue lives in the pia-data
   volume under `muse_ai_queue/`).
2. For each `queued` receipt, fetch the preserved image from the pia-data
   volume (`files/<evidence file>`) and read it.
3. Write the extraction JSON (schema below) to a temp file and ingest it:
   `docker exec pia python -m app.muse_ai.cli ingest <evidence_id> <file>`
4. Verify: `GET /api/receipts/{id}/extraction` shows the lines, and
   `GET /api/receipts/{id}/muse-ai` shows `done` (or `done_with_mismatch`).
5. If a receipt can't be read, mark it failed with the reason — never invent
   lines, never guess a total.

## Muse extraction JSON schema

```json
{
  "source": "muse_ai",
  "merchant": "Walmart",
  "purchase_date": "2026-11-06",
  "purchase_time": null,
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
      "confidence": "high"
    }
  ]
}
```

- Money is a string with 2 decimals (`"6.97"`), never a bare number.
- `quantity` defaults to 1 when the receipt shows none.
- `confidence` per line: `high` (read cleanly), `medium` (something inferred),
  `low` (guessed or unreadable).
- Unknown fields are `null` — never invented.

## Validation rules (enforced in `app/muse_ai/validation.py`)

- `line_total` must equal `qty x unit_price` (±$0.02) or the line is flagged.
- Lines must sum to the subtotal, and subtotal + tax must equal the total
  (±$0.02), or the extraction is flagged `total_mismatch`.
- A flagged extraction is still stored as an unconfirmed candidate — the
  Review screen is where a human catches it. Nothing is silently fixed.
- Malformed JSON (bad money, missing line name, wrong types) is rejected
  with 422 and stored nowhere.

## Audit

Every ingested Muse extraction gets a row in `muse_ai/muse_ai.sqlite`
(extraction id, evidence id, totals reconciled?, lines sum, mismatch?,
per-line confidence). The extraction itself uses the existing extraction
tables, so Review, corrections, and Confirm all work unchanged — including
correction-pattern suggestions, which are offered as "from your correction"
and never auto-applied.

## Security

- The queue is a mailbox only: JSON files under `muse_ai_queue/`. It never
  executes anything.
- No credentials, API keys, or model access live on the Droplet. Muse runs
  on Tim's side; only the finished extraction JSON crosses over SSH.
- Original receipt images are never modified. Unconfirmed never becomes a
  purchase. The two synthetic test purchases are untouched.

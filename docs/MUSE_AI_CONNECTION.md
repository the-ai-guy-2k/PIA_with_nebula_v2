# PIA — Muse AI Connection ("hood AI")

Muse (Tim) reads a receipt photo and returns a structured extraction.
No OpenAI, no outside AI API bill — Muse is the AI.

## The loop (no-confirm, Tee Nov 16, 2026)

```
phone snaps receipt
  → POST /api/receipts (image) → evidence id, original preserved unchanged
  → app auto-queues it: POST /api/receipts/{id}/muse-ai (best effort)
  → Tim polls the queue over SSH (see below)
  → Tim reads the preserved receipt image with Muse vision
  → Tim writes extraction JSON, ingests it:
      python -m app.muse_ai.cli ingest <evidence_id> <extraction.json>
      (or POST /api/receipts/{id}/muse-ai/ingest)
  → if it reconciles → purchase + memory + pantry, straight in. No confirm step.
  → if it does not reconcile → HELD unconfirmed. Review screen shows it for
    a manual confirm with corrected values. A held receipt never counts.
```

Review & Confirm is REMOVED from this loop (Tee, Nov 16, 7:11 PM).
Accuracy is the only safety net, so the accuracy bar is the gate:
verify every line against the receipt, reconcile lines + tax = total
before logging, product pictures verified only — blank if unverified,
never guess a name or a picture.

## Tim's poll (cron, main chat)

Every 15 minutes while receipts are queued:

1. SSH to the Droplet, `docker exec pia python -m app.muse_ai.cli list`
   (or run the CLI against the container — the queue lives in the pia-data
   volume under `muse_ai_queue/`).
2. For each `queued` receipt, fetch the preserved image from the pia-data
   volume (`files/<evidence file>`) and read it.
3. Write the extraction JSON (schema below) to a temp file and ingest it:
   `docker exec pia python -m app.muse_ai.cli ingest <evidence_id> <file>`
4. Verify: `GET /api/receipts/{id}/extraction` shows the lines and
   `confirmation_state`, and `GET /api/receipts/{id}/muse-ai` shows the
   queue status: `done` (auto-confirmed), `held` (held for review), or
   `done_with_mismatch` (held, totals did not reconcile).
5. If a receipt can't be read, mark it failed with the reason — never invent
   lines, never guess a total.

### Events log (the webhook, Nov 13 design)

Every queue change appends one line to
`<data_dir>/muse_ai_queue/events.jsonl` — timestamped, data-only, never
executed. Read the latest with:

```
docker exec pia python -m app.muse_ai.cli events [n]
```

Events: `receipt_queued` (snap), `receipt_status` (ingest outcome:
`done` / `held` / `done_with_mismatch`). Tim polls this file over SSH —
that is the prompt pickup without touching the accuracy of the read.
No shared token is needed: only the backend writes the file.

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

## Auto-confirm (reconcile-or-hold)

On ingest the backend auto-confirms (`app/muse_ai/service.py`,
`auto_confirm_reconciled`) only when ALL of these hold:

1. Totals reconcile (lines sum = subtotal AND subtotal + tax = total,
   ±$0.02).
2. Every line's `qty x unit_price` matches its `line_total` (±$0.02).
3. The extraction has lines and did not fail / come back with no text.

Otherwise the extraction is HELD: unconfirmed, no purchase, no pantry
rows, queue status `held` (or `done_with_mismatch` when the totals
themselves did not reconcile). The ingest response carries
`auto_confirm: {status, reason?, purchase_id?}` and the CLI prints an
`auto_confirm=...` line.

On confirm the backend runs the same validation as the manual confirm,
then the same memory + pantry steps, in the same order. If memory or
pantry fails, the purchase is KEPT and the failure is a warning on the
outcome — never lost.

One receipt, one purchase: a re-ingest after a correction never logs
the same receipt twice — auto-confirm checks for any purchase already
held for the evidence id first and returns `already_confirmed`.

## Display objects

Muse builds the receipt/pantry display objects; the UI only renders
them. Send `status: "confirmed"` only when the ingest response said
`auto_confirm.status` is `confirmed` or `already_confirmed` — otherwise
`status: "unconfirmed"`. The backend refuses a `"confirmed"` display
for a receipt with no purchase (422), so a display can never claim a
purchase that does not exist.

## Audit

Every ingested Muse extraction gets a row in `muse_ai/muse_ai.sqlite`
(extraction id, evidence id, totals reconciled?, lines sum, mismatch?,
per-line confidence). The extraction itself uses the existing extraction
tables, so Review, corrections, and manual Confirm all work unchanged —
including correction-pattern suggestions, which are offered as "from your
correction" and never auto-applied. A held extraction can still be
confirmed manually from Review with corrected values.

## Security

- The queue is a mailbox only: JSON files under `muse_ai_queue/`. It never
  executes anything. The events log is append-only JSONL, also never
  executed.
- No credentials, API keys, or model access live on the Droplet. Muse runs
  on Tim's side; only the finished extraction JSON crosses over SSH.
- Original receipt images are never modified. A held extraction never
  becomes a purchase. The two synthetic test purchases are untouched.

"""Muse AI receipt extraction — the "hood AI" connection.

Muse (Tim) reads a receipt photo and returns a structured extraction.
The Droplet cannot call Muse directly, so the loop is file-based:

  1. PIA queues a receipt (POST /api/receipts/{id}/muse-ai).
  2. Tim polls the queue over SSH, reads the preserved receipt image,
     and writes a structured extraction JSON.
  3. The extraction is ingested (CLI or POST .../muse-ai/ingest),
     validated here, and stored as the receipt's current UNCONFIRMED
     extraction — the same record the Review screen already shows.
  4. Nothing becomes a purchase or pantry item until the user Confirms.

Rules, same as the deterministic layer:
- Totals are arithmetic and never silently fixed. A mismatch is flagged.
- Unknown fields stay null — never invented.
- The original receipt image is never changed.
- Corrections already recorded are offered as suggestions, never auto-applied.
"""

from __future__ import annotations

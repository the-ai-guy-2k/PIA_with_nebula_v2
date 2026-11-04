# PIA Backend — Phase 1 verified (Nov 4, 2026, backend first, UI NOT started)

Working copy: ~/workspace/pia-backend (clone of the-ai-guy-2k/purchase_intelligence_app at 8cbe60f, plus new code below). NOT pushed to GitHub, NOT deployed to the Droplet — both need Tee's go on that exact action.

## What was built (new, deterministic, no AI)
- app/pantry/: GET /api/pantry, POST /api/pantry (add item), GET /api/pantry/{id} (with history), POST /api/pantry/{id}/status (in_stock/used/gone). Used reduces qty_on_hand, Gone sets qty 0, history kept, nothing deleted. Low = in_stock/used with qty <= 1.
- app/corrections/: POST /api/extractions/{id}/correct (per-field record: receipt/extraction/item, field, original -> corrected, by user, when, pattern_key). Original extraction is never modified. GET /api/corrections?pattern=, suggestions flagged "from_your_correction", still unconfirmed, never auto-applied.
- main.py wiring: confirm (POST /api/purchases and alias POST /api/purchases/confirm) now adds confirmed items to the pantry; GET /api/purchases/{id} includes applied_corrections; extraction reads include suggestions + corrections.
- Locked aliases: POST /api/receipts/{id}/extract, GET /api/extractions/{id}, GET /api/analytics/weekly (Decimal money, ISO week), GET /api/analytics/most-bought.
- Existing routes kept: intake, extraction, confirmation, memory, analytics. AI routes (/api/ask, /api/visual-recall) were NOT wired into this phase and are out of scope for the backend lock.

## Verification (tests/test_pia_backend_phase1.py, PASSED)
One end-to-end flow with a stubbed tesseract (known receipt text; real Tesseract ships in the Dockerfile, it is not installed on this VM):
intake -> extract (alias, unconfirmed, original bytes unchanged) -> correct "Milk Gallon" -> "Milk" (record stored, extraction untouched) -> confirm with corrected name (purchase uses corrected truth, 2 pantry items) -> pantry in_stock -> used -> gone (history in_stock, used, gone) -> manual add Rice qty 1 (low=True) -> weekly 2026-W11 = 5.61, most-bought = Milk + Bread Loaf -> second receipt proposes "Milk" from the correction, still unconfirmed.

## Test suite state (honest)
- Phase 1 test: PASSED.
- Full suite (excluding visual/ai): 58 passed, 9 failed. The 9 failures are pre-existing environment failures (real Tesseract / font tooling missing on this VM) — verified by running 2 of them on the clean tree, where they also fail. They are NOT regressions from this phase.
- Two bugs found and fixed during verification: corrections table name mismatch, and float money in weekly analytics (now Decimal).

## Next phase (UI) — NOT started
Flutter UI, 4 locked screens, only after Tee's UI phase go. No UI code was written in this phase.

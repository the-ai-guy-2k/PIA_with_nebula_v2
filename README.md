# Purchase Intelligence App

Local web application for understanding purchases over time.

ACI-001 preserves the original receipt image as evidence.

ACI-002 reads that preserved evidence and stores an unconfirmed extraction candidate. The candidate can include a merchant, date, time, totals, and line items. Raw recognized text is kept beside any normalized text. Nothing here confirms a purchase, classifies items, or changes the original image.

Extraction uses Windows OCR on Windows and local Tesseract on Linux, behind the same replaceable boundary. No paid OCR service is used. Recognition runs on an in-memory copy and does not rewrite evidence.

Requesting extraction again for the same evidence ID replaces the previous unconfirmed extraction and its line candidates. One current extraction is kept for each evidence ID. The original receipt file and evidence record are not modified.

ACI-003 adds review, correction, and explicit confirmation. Confidence is a deterministic review hint: high for an unambiguous parsed value, medium for a text candidate, low when a value is missing or the raw text shows something the parser refused, and absent when an optional value was not on the receipt. Highlighted fields can be corrected. Blank optional fields stay null.

Confirm purchase is the only action that creates a confirmed purchase. One extraction has one confirmed purchase. Confirming that extraction again is rejected, and the confirmed record is read-only. The raw extraction text and the original receipt are not rewritten. Each confirmed item keeps the source line id and the raw line text.

ACI-004 remembers a confirmed purchase. Purchase history is created only from that confirmed record, one memory record per purchase. Remembering the same purchase again reuses the existing record and does not change classifications. The confirmed purchase and the original receipt stay unchanged.

Classification is conservative and local. Obvious item words can be marked food or non-food, and consumable or long-term. Need versus want stays unknown until you set it. An unrecognized item stays unknown. You can correct any of the three labels. Purchase history shows what was purchased. It does not claim those items are still in the household.

ACI-005 calculates purchase patterns from purchase history when the patterns page is opened. Nothing is stored as a second copy of the purchases. Item comparison trims surrounding space, collapses inner space, and casefolds the name. Different words stay different items. A repeat is the same comparison key on more than one remembered purchase. An interval is calculated only when at least two of those purchases have dates. Missing quantities and dates stay missing. Changing a classification changes the next count. Opening the patterns page does not change purchase history.

ACI-006 adds pictures for food purchased at Walmart. The merchant must be Walmart, Walmart followed by a store type, or Wal-Mart. The item must already be classified as food. Other merchants and other classifications are skipped. Pictures come from a replaceable local catalog of original illustrations. A generic food such as milk or bananas is labeled Representative image. An exact label is used only when the full item name is an explicit catalog identity. If no trustworthy picture exists, the item stays text-only. Opening food recall does not change the confirmed purchase or purchase history. A picture does not mean the food is still in the household.

## Run

Requires Python 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

Receipt evidence is written under `data/receipt_evidence/`. Extraction candidates are written under `data/receipt_extraction/`. Confirmed purchases are written under `data/confirmed_purchases/`. Purchase history is written under `data/purchase_memory/`. Those directories are gitignored. Do not commit uploaded receipts, extractions, confirmed purchases, or purchase history.

### Replit / Linux

Use Python 3.12 and install Tesseract (including English language data).
The OCR tests also require DejaVu fonts and fontconfig. On Replit, these
are installed as Nix packages `tesseract`, `dejavu_fonts`, and `fontconfig`.
Install the existing `requirements-dev.txt` for validation or `requirements.txt`
for runtime; WinRT dependencies are restricted to Windows.

```sh
python run.py
```

`run.py` starts the existing `app.main:app` with host `0.0.0.0`, using
`PORT` when set and port 8000 otherwise. `PIA_DATA_DIR` can select an isolated
evidence directory; sibling SQLite databases follow that directory as before.
In this Replit project, the managed API artifact routes the whole application
at `/` and supplies the port. The pnpm/Express template is not the application.

In development on Replit, embedding is permitted only for the application's
own origin and Replit preview origins. Outside Replit development the original
frame-denial policy remains. Other security headers remain unchanged.

Source recovery does not recover gitignored receipt files or purchase databases.
Do not commit runtime data. No authentication or public publishing has been
added by this continuation.

## Ask history — ACI-007

Open `/ask` for recent purchases, food, repeated items, merchants,
needs/wants/consumables, recorded patterns, and cautious food availability recall.
Starter buttons only fill the question. AI runs only after an explicit Ask.

This uses the operator-approved `gpt-5-nano` through Replit AI Integrations,
with the Python OpenAI SDK. Provision the managed integration in Replit; no
separate provider account or user API key is required. Usage is billed at the
provider's public API prices to Replit credits; it is not unlimited/included
token usage. Managed access was verified through real requests in this project.
The app uses `AI_INTEGRATIONS_OPENAI_BASE_URL` and
`AI_INTEGRATIONS_OPENAI_API_KEY` on the server only. Never commit values.
If integration access is unavailable, the existing app remains usable and Ask
returns a clearly labelled deterministic fallback.

`POST /api/ask` accepts only `{"question": "..."}` (maximum 500 characters).
Results are derived, unpersisted, and never become purchase truth. The provider
interface is replaceable; other modules do not choose a model.

### Grounding, privacy, and limits

- Deterministic routing selects relevant Memory and existing Analytics results.
- The original question is not sent to AI. The provider receives a normalized
  intent, minimal canonical facts, and eligible interpretations.
- AI selects references; the server validates them and renders the original
  canonical wording. It cannot accept arbitrary AI-generated names, counts,
  dates, quantities, classifications, or inventory claims.
- Recent recall means the latest five relevant remembered purchases, not a
  freshness period. Undated records come last and retain unknown dates.
- At most 24 context facts / 16 KiB; responses use at most 12 grounded facts.
- Item and merchant selection does not introduce product-equivalence matching.
  Walmart recall reuses the existing conservative merchant predicate without
  changing analytics' merchant grouping.
- Classification counts are remembered item records, not unique products.
- Purchased quantities are not quantities remaining. Food may still be available;
  consumption, expiration, remaining quantity, and current inventory are unknown.
- No images, raw OCR, filesystem paths, database identifiers, secrets, or
  unrelated line-item history are sent. Path/credential-like labels are excluded.
- AI does not call the visual-recall builder or change enrichment associations.
- One model request per supported, data-backed Ask; SDK retries are disabled.
  There are no startup/load/refresh/background calls, conversation persistence,
  or automatic shopping lists. Blank, unsupported, and insufficient/no-data
  questions use deterministic handling without AI.
- Timeout, failure, unavailable integration, and unusable output return visible,
  deterministic fallback with supporting facts, not a fabricated interpretation.
- The output token ceiling is 8192 (including reasoning), with minimal reasoning;
  the actual structured selection is small. Provider timeout is 55 seconds and
  the service caps the operation at 60 seconds.
- Custom calendar windows, merchant-filtered repeat/pattern queries, expiry,
  nutrition, forecasts, write requests, and arbitrary item-specific recall are
  not supported. They are refused rather than silently dropping those constraints.

### Additional live validation

The existing 67-test regression is preserved. ACI-007 adds query, privacy,
grounding, no-write, no-call, adapter, fallback, and input-boundary tests.

For explicit live validation, use a **fresh isolated** `PIA_DATA_DIR` for the
server and the same directory for the validator; never use personal data:

```sh
python -m tests.live_ai_validate --base-url http://localhost:80 \
  --data-dir /tmp/pia-live/receipt_evidence --report /tmp/pia-live-report.json
```

This deliberately makes 12 real AI requests and creates three synthetic receipts
through live intake, local OCR, review/correction/confirmation, and classification.
It checks original bytes and unchanged database/evidence snapshots across queries.
It refuses to seed a populated evidence directory. See `docs/ACI-007-VALIDATION.md`.

## Desktop dashboard — ACI-008

The default `/` page is Overview. One shared left navigation connects Overview,
Purchase History (`/memory`), Patterns (`/analytics`), Food Recall (`/food-recall`),
and Ask AI (`/ask`). Upload receipt opens the original intake/review/confirmation
workflow at `/intake`; no intake API or evidence semantics changed.

Overview reads the existing Memory, deterministic Analytics, and visual-recall
APIs independently. It shows confirmed remembered purchases, repeating item
identities, current food classifications, recent history, observed repeat
intervals, merchant counts, Need/Want/Unknown counts, and a small Walmart food
preview. Native HTML meters display zero-based occurrence counts; there is no
chart library or frontend analytics reimplementation. Receipt totals are absent
from Memory, so Overview never constructs spending totals from line items.

`GET /api/ai-status` exposes configuration presence and the selected provider/model,
never credentials. It performs no model request and explicitly does not verify
service health. Overview starter links and its compact question form open
`/ask?question=...` and prefill at most 500 characters. The user must still click
Ask; ACI-007 routing, privacy, grounding, fallback and no-write rules are unchanged.

Shared CSS supplies the operator-approved warm-white/green visual direction,
desktop navigation, practical smaller-screen collapse, visible keyboard focus,
labels, skip links and image alt text. Optional status/enrichment failures do not
block remembered purchases or patterns. Empty history shows real zero counts
and useful guidance, never demo data.

See `docs/DASHBOARD-DIRECTION.md` and `docs/ACI-008-VALIDATION.md`.
For bounded fixture preparation, use a fresh isolated server storage directory:

```sh
python -m tests.live_mvp_validate --base-url http://localhost:80 \
  --data-dir /tmp/pia-mvp/receipt_evidence \
  --browser-image /tmp/pia-mvp-receipt.png --report /tmp/pia-mvp-prepare.json
```

This prepares two synthetic receipts through real local OCR and makes **zero**
model calls. Complete browser integration validation with no more than two
explicit real queries when AI logic is unchanged. The older 12-query ACI-007
validator above is not the normal dashboard validation path.

## Checks

```powershell
pip install -r requirements-dev.txt
pytest
```

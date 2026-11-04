# ACI-007 — Replit continuation validation

## ACI status

**PASS — recovery, ACI-001–006 regression, and ACI-007 implemented and validated.**
The branch commit/push result and exact SHA are supplied in the operator handoff.
ACI-008 is not implemented.

## Start forecast recap

- Recover the existing FastAPI modular monolith, not a replacement application.
- Verify baseline `feature/aci-006-walmart-food-visual-recall` at
  `5f05a164bf128f875e5d28d4d7a307ee8b5596b0`.
- Continue only on `feature/aci-007-ai-intelligence-query-recall`.
- Existing entrypoint: `app.main:app`; Python, SQLite, static HTML/JS.
- Expected portability work: Windows-only WinRT dependencies/OCR and Windows
  test font; retain the recognizer boundary and original evidence.
- Forecast scope: minimal Linux/Replit restoration, a focused additive AI
  module/provider boundary, one `/ask` page, tests/documentation, commit/push.
  No architecture replacement, truth migration, broad UI redesign, or dashboard.
- Replit-managed OpenAI was proposed; the initial, unapproved legacy
  `gpt-4.1-nano` proposal was replaced by the explicitly approved `gpt-5-nano`.
  No legacy model or unapproved external account was used.
- Credentials: managed server environment, provisioned by Replit.
- Expected cost: bounded text context, at most one model request per data-backed
  Ask, no background calls; usage charged to Replit credits at public API prices.
- Expected changed areas: runtime/config/dependencies, OCR boundary and portable
  OCR test fixture, additive AI modules/routes/page/nav links, validation/docs.
- Validation plan: complete existing suite before AI; complete expanded suite,
  live receipt/AI checks, byte-level no-write proof, interactive browser checks.
- Assumptions/risks: gitignored historical data was not recoverable from source;
  OCR engines can differ; managed model access/schema must work; provider
  failures must degrade; purchases must never imply inventory. These were
  handled by isolation, real OCR/model checks, explicit approval and fallbacks.

## Replit recovery and compatibility

- Baseline branch/commit: verified locally and through GitHub.
- Runtime: Python 3.12.12 / FastAPI 0.142.2 / Uvicorn 0.54.0 / SQLite.
- Source start command: `python run.py`.
- Managed command: `python purchase_intelligence_app/run.py`, from the API
  artifact directory. Host `0.0.0.0`, managed `PORT=8080`, preview `/`.
- Linux OCR: local Tesseract 5.5.0, English, bounded subprocess timeout; no paid
  OCR. Windows keeps its original WinRT recognizer.
- Original bytes stay unchanged; OCR reads/scales only an in-memory copy.
- WinRT dependencies have Windows platform markers. OCR tests use a portable
  DejaVu font/fontconfig path on Linux.
- Replit preview frame origins are narrowly allowed in development. Default
  frame denial and other security headers are preserved.
- No purchase/classification/analytics/visual-recall schema changes.
- Added runtime dependency: `openai==3.24.0`. Playwright/Chromium are verification
  tooling in the Replit host, not product runtime requirements.
- Replit host Git history is separate from the recovered product history.
  Explicit product Git metadata/work-tree selection prevents accidental template
  ancestry. Recovery did not overwrite the validated source.

## Automated regression

| Capability | Result |
|---|---:|
| ACI-001 Receipt intake | PASS — 17 tests |
| ACI-002 Extraction / local OCR | PASS — 14 |
| ACI-003 Review / confirmation | PASS — 14 |
| ACI-004 Purchase Memory / classification | PASS — 7 |
| ACI-005 Deterministic analytics | PASS — 9 |
| ACI-006 Walmart food visual recall | PASS — 6 |
| ACI-007 AI intelligence | PASS — 63 |
| **Complete suite** | **130 passed, 0 failed** |

Command: `python -m pytest -q`.
The final starter-page contract also passed its focused test; `node --check
app/static/ask.js` passed.

The existing live ACI-001 validator passed all seven HTTP acceptance/rejection,
path-containment, and evidence-integrity cases after the server and validator
were configured to use the same isolated storage.

## AI implementation

- **Provider/model:** explicitly approved Replit-managed OpenAI `gpt-5-nano`;
  real requests verified access in this project. No separate provider account/key.
- **Boundary:** async `AIProvider` protocol; managed adapter is replaceable.
  Purchase Memory and confirmed schemas do not depend on it.
- **Routing:** deterministic supported-intent selection; unsupported constraints
  are refused rather than silently ignored.
- **Context:** minimal read-only Memory/Analytics projection. Recent = latest five
  relevant stored purchases, up to 24 item facts; undated purchases stay unknown.
- **Deterministic integration:** original `summarize_memory` results are used for
  repeat counts, dates/intervals, quantities, merchants and classification counts.
  No alternative normalization or model-side counting.
- **Grounding:** AI selects supplied fact and eligible interpretation references.
  Server checks shape, references, duplication and limits, then renders canonical
  facts/interpretations. Arbitrary AI factual prose is never accepted.
- **Traceability:** visible “Based on” facts, counts, scope, generated time,
  query ID, source, provider/model, and degraded reason. Results are unpersisted
  derived data, never purchase truth or conversational memory.
- **Privacy:** original questions, receipt images, OCR transcripts, filesystem
  paths, credentials, DB IDs and unrelated item history are not transmitted.
  Path/credential-like stored labels are excluded. Provider exception text is
  neither returned nor logged.
- **Cost:** maximum 500-character input; 24 facts / 16 KiB context; at most one
  model request; no SDK retry; minimal reasoning and 8192 total output-token
  ceiling. No AI at startup/load, on Memory/classification changes, analytics or
  visual recall reads. Blank, unsupported, no-data and insufficient-history
  cases avoid AI.
- **Degradation:** timeout, unavailable provider, failure, unusable/unsupported
  output return clearly labelled deterministic facts, not invented interpretation.
- **Authority:** no writes, shopping lists, product orders, deletion or messages.
  AI never invokes visual recall's mutating enrichment builder.
- **UI:** additive `/ask`, desktop-first and phone-usable; fill-only supported
  starters, input, loading, answer, facts, source, empty/unsupported/error/fallback
  states. Other page layouts unchanged except an Ask history link.

## Required AI cases — expected / actual

All following cases passed through live HTTP and the real managed model on
synthetic, isolated fixtures. Figures below describe those fixtures, not personal
history. Twelve real AI requests were made by the live validator.

| Case | Expected | Actual | Result |
|---|---|---|---|
| Recent purchases | Only stored confirmed purchases | Eight grounded item facts, including Milk Gallon; stored dates/merchants retained | PASS |
| Recent food | Food-classified items only | Six food facts; HDMI Cable / Notebook excluded | PASS |
| Often / repeats | Existing analytics authoritative | Milk Gallon on two remembered purchases; stored average interval 11 days; three repeat facts | PASS |
| Merchant counts | Existing merchant counts, no regrouping | Three separate recorded merchant count facts | PASS |
| Walmart recall | Matching Walmart history only | Six matching facts; Corner Shop excluded; existing Walmart predicate used | PASS |
| Needs | Current classifications | Six need item records, with grounded examples | PASS |
| Wants | Current classifications | Two want item records, with grounded examples | PASS |
| Consumables | Current classifications | Six consumable item records, with grounded examples | PASS |
| Patterns | Recorded patterns, not prediction | Three stored purchases and ten grounded analytics facts with eligible interpretations | PASS |
| Food availability style | May be available, not inventory | Six food facts; explicit purchased ≠ available, consumption/expiry/remaining quantity unknown | PASS |
| “What food do I have?” | Cautious recall, no ownership certainty | Same six grounded food facts and explicit inventory caveat | PASS |
| Empty history | Honest, no model call | Empty deterministic response, null provider | PASS |
| Unsupported / blank | No unnecessary AI or writes | Read-only deterministic refusal / HTTP 400 | PASS |
| Insufficient repeat/trend data | No invented trend | Automated cases return insufficient-history, no provider call | PASS |
| Provider timeout/unavailable/failure | Safe usable fallback | Automated injected failures return deterministic facts with reason; old routes stay usable | PASS |
| Unusable / hallucinated output | Reject unsupported claims | Bad references, duplicates, invented prose rejected; canonical fallback only | PASS |
| Privacy / no-write | Minimal context; truth unchanged | Filtered captured payloads; all evidence/DB byte snapshots and analytics unchanged | PASS |

The live receipt pipeline also created three fixtures via real upload, local
Tesseract OCR, corrections, confirmation, automatic Memory and classification;
original receipt bytes matched after the entire flow.

## Browser verification

Twelve interaction checks passed: no load call; fill-only starters; loading and
disabled state; duplicate submission generated one request; real AI answer and
facts rendered; unsupported and empty states; fallback state; HTTP 503 error
state; blank submit made no request; 390-pixel phone had no horizontal overflow;
no uncaught app/browser errors.

The completed browser run used one real model call. One preceding harness run
also completed its real answer check before a CSP-blocked automation predicate;
14 total real model requests were made during live/browser validation.
Fallback and HTTP 503 browser responses were intentionally injected test states;
backend degradation was independently tested at the provider boundary.
The application's CSP was not weakened for testing.

Normal source storage was restored after testing. Synthetic fixtures remain
separate in temporary test storage and are not committed or shown as personal
purchase history.

## Source control and stop

- Repository: `the-ai-guy-2k/purchase_intelligence_app`.
- Target: `feature/aci-007-ai-intelligence-query-recall`.
- Commit message: `ACI-007: restore Replit runtime and add grounded read-only AI query/recall`.
- Required ancestry: the single parent is the authoritative ACI-006 commit.
- Product tree is verified before branch publication through the attached GitHub
  integration. Exact pushed SHA is included in the final operator handoff.
- No main merge; no deletion of prior branches; no publishing/deployment.
- ACI-008 remains unauthorized. Dashboard input direction is preserved separately.

**Material errors:** none remaining.

**Minority report:** NONE.
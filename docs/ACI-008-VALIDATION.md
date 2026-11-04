# ACI-008 — Desktop integration and end-to-end MVP validation

## ACI status

**PASS.** The approved desktop dashboard is integrated into the existing
FastAPI/static HTML/JS application. The complete receipt-to-learning journey
and all 14 E2E cases passed. No Stage 2 work, public publishing or main merge.

## Start forecast and approval

- Authoritative baseline: `feature/aci-007-ai-intelligence-query-recall`,
  `e6b7227f561caf1a5d3e0bd7757f1d01558fa4f1`.
- Target: `feature/aci-008-desktop-dashboard-e2e-mvp`.
- Existing pages discovered: receipt intake `/`, Memory `/memory`, Patterns
  `/analytics`, Food Recall `/food-recall`, Ask `/ask`.
- Reuse: existing APIs, shared CSS palette/cards/controls, all existing page
  controllers, original Memory classifications and deterministic analytics.
- Planned changes: main route/rendering helper; shared styles/navigation;
  existing HTML pages; Overview HTML/controller; Ask prompt prefilling;
  narrow route-contract tests; dashboard tests, validation and documentation.
- Predicted size: approximately 19–22 files / 700–1,200 added or changed code
  lines excluding documentation. Actual product change: 20 files; unchanged
  working intake/Memory/analytics/recall controllers were not regenerated.
- Dependencies predicted and added: **none**. No new service, UI framework,
  chart package, provider, schema, or build system.
- Chart plan: native HTML/CSS horizontal occurrence bars, not unsupported spend.
- Validation plan: targeted checks, one full regression run, one focused browser
  journey, two real AI smoke queries; test providers for remaining AI coverage.
- Risks: missing references, root-route contract changes, optional-source
  blocking, unknown classifications/dates, unsupported totals and inventory
  implications. Addressed without modifying AI or existing truth schemas.
- Operator approved the forecast and supplied all five image references.
  Images guide hierarchy/spacing/palette only; no pixel-perfect cloning or new
  budgeting/finance features.

## Implementation summary

- `/` is Overview; `/intake` preserves upload, extraction, correction and
  confirmation. All intake/purchase APIs are unchanged.
- Shared `nav.html` is inserted server-side without a templating dependency.
  Five primary links plus Upload receipt have exact active-page ARIA markers.
- One consolidated stylesheet reuses existing control selectors. Desktop left
  navigation collapses practically on smaller screens.
- Overview consumes existing Memory, Analytics and visual-recall APIs separately.
  Slow/unavailable optional sources cannot hold the other panels behind them.
- KPI definitions: remembered purchase count, repeating item identities, current
  food item records, and AI configuration status (not a fabricated insight count).
- Recent purchases retain newest-first ordering and unknown values. No receipt
  total exists in Memory, so no spending total is manufactured.
- Repeat bars use existing occurrence counts, zero-based native meters and
  explicit top-N/all-history scope. Intervals are observed, not predictions.
- Top merchants retain existing grouping/counts. Need/Want includes UNKNOWN.
- Walmart food preview retains Exact/Representative/No image, text fallback,
  Memory links, and purchased-not-current-inventory framing.
- History, Patterns and Food Recall retain their working controllers, filters,
  detail views, classification actions, deterministic facts and traceability.
- Ask retains its six starters, explicit-submit/loading/answer/facts/provenance,
  fallback and error states. Overview starters/GET form prefill at most 500
  characters; no automatic submission.
- `GET /api/ai-status` reports configuration and provider/model only; no model
  call, credentials, or live-health promise.
- ACI-007 provider/routing/context/grounding/privacy/no-write logic is unchanged.
- Accessibility: semantic headings, labels, skip link, visible keyboard focus,
  meaningful links/buttons, image alt text, current-page navigation.
- Empty data shows real zeros and guidance; optional-source errors are localized.

## Cost-control report

| Measure | Result |
|---|---|
| Unnecessary framework changes avoided | YES |
| New UI framework added | NO |
| New chart package added | NO |
| New dependency/service/provider/schema | NO |
| Full regression suite runs | 1 |
| Real AI/model validation calls | 2 |
| Major working-module rewrites | NO |
| Focused browser pass | 1, with a limited continuation of unfinished checks |
| Unexpected cost-driving work | Limited repair/recheck, described below |

The full suite found three page-contract issues: extraction/confirmation tests
still read intake at `/`, and shared Food Recall copy omitted its previously
tested inventory caveat. The two tests now use `/intake` with their assertions
unchanged; the original caveat was restored. Only those three checks were rerun.
No second full regression, new architecture, repeated design pass or extra model
request was needed.

The browser pass initially stopped on two checker mistakes: conditional
"may still be available" was interpreted under a stricter contract than the
approved ACI-007 wording, and navigation/KPI checks used incorrect locator or
attribute assumptions. A limited continuation checked the correct selectors,
reassessed the already captured answer, and completed unfinished fault/phone
checks. It did not rerun the receipt journey or make another model call.

The first external HTTPS fixture-preparation attempt hit local certificate trust
failure before any upload/model request. The same app was validated through the
existing local preview proxy, with no TLS/CSP weakening or extra service.

## End-to-end validation — expected / actual

All figures describe isolated synthetic fixtures, not personal purchase history.

| Case | Expected | Actual | Result |
|---|---|---|---|
| 1 Receipt intake | Preserve original evidence | Three uploaded PNGs match original bytes and SHA-256 | PASS |
| 2 Extraction | Extract or surface correction candidates | Real local OCR; unconfirmed three-line candidate | PASS |
| 3 Validation | Correct and explicitly confirm | Browser corrected Walmart/date and confirmed structured purchase; unsupported quantities remained Unknown | PASS |
| 4 Purchase Memory | Confirmed purchase appears in history | Three entries, newest first: 2026-10-03, 2026-10-01, 2026-09-20; detail/filter work | PASS |
| 5 Classification | Available/editable | Browser saved UNKNOWN; stored classification/analytics verified | PASS |
| 6 Analytics | Counts/intervals update from Memory | 3 purchases, 9 item records, 3 identities repeating; average interval 6.5 days, latest 2 days | PASS |
| 7 Walmart food visual recall | Eligible food, truthful labels/fallback | Representative images, exact/no-image empty filters, trace links; prior automated exact-identity case retained | PASS |
| 8 Repeat AI | Grounded answer, facts, deterministic counts | Real HTTP 200; 3 supporting facts, approved provider/model and recorded intervals | PASS |
| 9 Food AI | Purchase framing, no inventory certainty | Real HTTP 200; 9 purchase facts, conditional possibility plus explicit unknown availability/consumption/expiry/remaining quantity | PASS |
| 10 Overview | Reflect stored data | KPIs 3 purchases / 3 repeats / 9 food records; newest-first history and configuration-only AI status | PASS |
| 11 Navigation | Five sections reachable/current marker | All five visited; scoped ARIA current-route selectors matched exactly once | PASS |
| 12 Degraded AI | Core app remains usable | Injected 503 restores Ask form; Memory/Patterns remain usable with optional recall pending | PASS |
| 13 Degraded image | Text fallback works | Nine intercepted image failures → nine No image labels, retained text and nine Memory links | PASS |
| 14 Empty data | Useful empty state, no demo metrics | Intercepted empty sources show real zeros/guidance; removing interception restores fixture counts | PASS |

Two fixtures were prepared via live HTTP/OCR; a third completed the actual browser
upload/extract/review/correct/confirm/classify journey. All three preserved images
hash to `87621ef3340b41b27198fe44d45c8ac7261620d087c8f0686869eb23a1ba9927`.
The original file size is 58,516 bytes. AI queries left Memory/Analytics unchanged.

## Regression

- **Total tests: 144. Final verified outcomes: 144 passed, 0 failed.**
- Existing 130 tests retained; 14 dashboard integration cases added.
- Evidence: the single full run returned 141 PASS / 3 FAIL; after the narrow
  repair, all three failed checks passed. The other 141 results remain valid.
  This is a reconciled final result, not a claim that a second full suite ran.
- All page scripts passed `node --check`; `git diff --check` is clean.
- No data-schema or deterministic analytics changes.

## Browser validation

| Page | Result |
|---|---|
| Overview | PASS — stored data, independent panels, empty/degraded states |
| Purchase History | PASS — newest first, detail, filters, classification |
| Patterns | PASS — authoritative counts/intervals/sources |
| Food Recall | PASS — eligibility, labels, text-only degradation, traces |
| Ask AI | PASS — fill-only entry, explicit queries, facts/provenance/error |

At 390×844, scroll width equaled client width (375 after scrollbar); no horizontal
overflow. Keyboard Tab reached Skip to content, question/Continue had accessible
names, and all three Overview images had descriptive alt text. No uncaught page
errors were captured. Inline-style CSP warnings occurred during instrumentation;
source locations were empty, app source/documents had no inline styles/scripts,
and high-z-index highlighting overlays were present. Their exact origin was not
established. The application's CSP was preserved, not weakened.

## AI integration smoke test

Exactly two real managed `gpt-5-nano` requests:

1. "What do I buy often?" — grounded repeat facts and recorded intervals.
2. "What food might I have to eat?" — cautious history recall and explicit
   purchased-versus-available/unknown-consumption caveats.

Both returned HTTP 200 with supporting facts and provider/model provenance.
No model calls on load/navigation/prefill; no retry or background requests.
The extra degraded Ask request was fully intercepted and not sent to a model.
No 12-query ACI-007 live validation rerun.

## Source control and stop

- Required single parent: the authoritative ACI-007 baseline above.
- Target branch: `feature/aci-008-desktop-dashboard-e2e-mvp`.
- Commit message: `ACI-008: integrate desktop dashboard and validate end-to-end MVP`.
- Commit/publication occur only after these validations; exact SHA, remote-tree
  comparison and prior-branch preservation are returned in the final handoff.
- Runtime validation storage is isolated and normal storage is restored afterward.
  No receipts, fixture history, databases, secrets or raw response reports committed.
- No merge, public deployment, extra integration or Stage 2.

**Material errors:** none remaining.

**Minority report:** NONE.
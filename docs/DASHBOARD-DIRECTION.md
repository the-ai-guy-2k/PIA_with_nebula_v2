# Operator-approved desktop dashboard direction

The operator approved the ACI-008 start forecast and supplied all five visual
references. The dashboard integrates existing capabilities, not a replacement
application or a pixel-perfect copy of those references.

- Warm off-white / light gray background
- Muted deep green primary color
- Cream / warm-white cards
- Restrained muted accent colors
- Clean rounded cards
- Subtle borders and shadows
- Generous whitespace
- Desktop-first
- Left navigation
- Minimal/premium personal-finance feel
- Restrained charts
- No neon
- No heavy dark theme
- No bright gradients
- No generic blue SaaS look

Reference assets remain in Kobe:
Purchase Intelligence App — K → 04. Assets & Evidence → UI Dashboard References.

The uploaded references cover overview/privacy, a dense product system and
palette, spending/budgeting layout, minimal finance UI, and a dense finance
dashboard. Their layout/color cues are inspiration only: budgeting, bank data,
spend totals and other unsupported dimensions were not added.

## Integration boundaries

- Overview is the default landing page, with the original receipt workflow
  reachable through Upload receipt at `/intake`.
- One shared navigation fragment and stylesheet serve all integrated pages.
- Charts are native HTML meter bars using existing occurrence counts, not a new
  charting dependency or a second analytics implementation.
- AI status is configuration only; starters prefill Ask without submitting.
- UNKNOWN classifications, unknown dates/merchants, image provenance and the
  purchased-not-current-inventory rule remain explicit.
- Optional sources render independently so they cannot block core dashboard data.
- No framework, provider, database schema or architecture migration.

The approved MVP ends after integration, validation, commit and branch push.
No main merge, public publishing, additional integrations or Stage 2 work is
authorized by this delivery.
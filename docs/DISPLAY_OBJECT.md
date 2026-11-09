# PIA display object — contract between Muse and the PIA server

Architecture (Tee, Nov 8, 2026). The UI (phone app) only snaps / uploads
the receipt photo. Muse does everything else — receipt reading/extraction,
product-picture lookup per item, grouping by purchase date/time, and the
display shape. Muse returns ONE structured object to the server; the server
stores it and hands it to the UI; the UI just renders it.

This is an extension of the hood AI layer (Muse extraction -> Review &
Confirm), not a replacement. A display object NEVER changes confirmation
state.

## Endpoints

- `POST /api/receipts/{evidence_id}/muse-ai/display` — Muse sends the
  receipt display object. The receipt must already have an extraction, the
  object's `evidence_id` must match the URL, and its `status` must match
  the receipt's actual state (`unconfirmed` unless a confirmed purchase
  already exists — a `confirmed` display is refused otherwise). 200 with
  the stored object, 404 with no extraction, 422 on any validation failure.
- `GET /api/receipts/{evidence_id}/display` — the stored receipt object.
- `POST /api/display/pantry` — Muse sends the pantry display object.
- `GET /api/display/latest?kind=pantry|receipt` — the latest stored object
  of that kind. This is what the UI renders.

## The object

```json
{
  "object": "pia_display",
  "version": 1,
  "kind": "receipt",
  "evidence_id": "935fac61-bfe6-47e3-a349-505cddb854e4",
  "extraction_id": "3366eb7f-d83c-465e-ae91-e086c19c87ae",
  "merchant": "Walmart",
  "purchase_date": "2026-11-06",
  "purchase_time": null,
  "subtotal": "160.38",
  "tax": "4.16",
  "total": "164.54",
  "totals_reconciled": true,
  "status": "unconfirmed",
  "search_placeholder": "Find something...",
  "left_count": { "shown": 37, "total": 37 },
  "groups": [
    {
      "group_id": "2026-11-06-afternoon",
      "heading": "Thursday afternoon, Nov 6",
      "item_count": 37,
      "items": [
        {
          "line_id": "…",
          "name": "Ivory Gentle Body Wash",
          "raw_text": "IVORY BW OR 030772018460 6.97 X",
          "upc": "030772018460",
          "quantity": "1",
          "unit_price": "6.97",
          "line_total": "6.97",
          "image_url": "https://images.openbeautyfacts.org/images/products/003/077/201/8460/front_en.3.400.jpg",
          "image_source": "open_beauty_facts",
          "image_confidence": "high"
        }
      ]
    }
  ],
  "built_by": "muse_ai",
  "built_at": "2026-11-09T01:55:00+00:00"
}
```

For `kind: "pantry"`, `evidence_id` / `extraction_id` / `merchant` /
`purchase_date` / `purchase_time` / `subtotal` / `tax` / `total` /
`totals_reconciled` are all null, and each item is instead:

```json
{
  "pantry_item_id": "…",
  "name": "Bread Loaf",
  "qty_on_hand": "1",
  "pantry_status": "in_stock",
  "image_url": "https://…",
  "image_source": "image_search",
  "image_confidence": "medium"
}
```

## Field rules (enforced server-side, `app/muse_ai/display.py`)

- `object` must be `"pia_display"`, `version` must be `1`,
  `built_by` must be `"muse_ai"`, `kind` is `receipt` or `pantry`.
- Groups: non-empty list. Each group has `group_id`, `heading`
  (e.g. `"Thursday afternoon, Nov 6"` — weekday + morning/afternoon/night
  + month + day), and `item_count` equal to its number of items.
- Receipt items: `line_total` must equal `quantity × unit_price` (±$0.02).
  The lines must sum to `subtotal` (±$0.02) and `subtotal + tax` must equal
  `total` (±$0.02); `totals_reconciled` must state the true result of that
  check. A mismatch is rejected — never silently fixed, never claimed true.
- Pantry `left_count` must equal the in-stock count; receipt `left_count`
  must equal the number of lines. (The UI's search filter narrows the shown
  count itself; the stored object carries the unfiltered totals.)
- `image_url` is a plain `https://` URL or `null`. `image_source` is one of
  `seeded`, `open_beauty_facts`, `open_food_facts`,
  `open_food_facts_search`, `image_search`, or `null` (required when a URL
  is present, forbidden when it is null). `image_confidence` is `high`,
  `medium`, or `low` when a URL is present.
- A photo Muse could not find stays `image_url: null` — the UI shows a
  plain placeholder, never a wrong product's picture.
- `upc`, when present, is 12 or 13 digits.

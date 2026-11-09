"""Product photo lookup for receipt items and pantry items.

Deterministic, no AI, no API keys. Sources, in order:
1. Seeded mapping (human-verified photos, `seeded_images.json` next to
   this module) — a photo is only seeded when a real lookup clearly
   matched the brand/product. A wrong photo is worse than no photo.
2. Open Beauty Facts by UPC (non-food, e.g. Ivory body wash).
3. Open Food Facts by UPC, then by name search.
Anything unresolved returns image_url None — the display shows a
plain placeholder, never an invented product photo.
"""

"""Product photo lookup: seeded mapping, then Open Beauty Facts /
Open Food Facts by UPC, then Open Food Facts by name.

Stdlib only (urllib), 5-second timeouts, in-memory cache. A fetcher
can be injected for tests. Any failure is a miss, never an exception:
the display falls back to a placeholder.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_TIMEOUT = 5
_USER_AGENT = "PIA/1.0 (TAIG ITS; product photo lookup)"

_SEEDED_PATH = Path(__file__).with_name("seeded_images.json")

_cache: dict[tuple[str | None, str | None], dict[str, object]] = {}


def clean_upc(raw: str | None) -> str | None:
    """Digits only; keep 12- or 13-digit codes, else None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) in (12, 13):
        return digits
    return None


def parse_upc_from_raw(raw_text: str | None) -> str | None:
    """First 12- or 13-digit run in a receipt line's raw text."""
    if not raw_text:
        return None
    match = re.search(r"\b(\d{12,13})\b", raw_text)
    return match.group(1) if match else None


def _normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return cleaned or None


def _load_seeded() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_SEEDED_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _default_fetch(url: str) -> dict | None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def _image_from_product(product: dict | None) -> tuple[str | None, str | None]:
    if not isinstance(product, dict):
        return None, None
    image = (
        product.get("image_front_url")
        or product.get("image_url")
        or product.get("image_front_small_url")
    )
    name = product.get("product_name") or product.get("product_name_en")
    return (image if isinstance(image, str) else None), (
        name if isinstance(name, str) else None
    )


def _safe_fetch(fetch, url: str) -> dict | None:
    try:
        result = fetch(url)
    except Exception:
        return None
    return result if isinstance(result, dict) else None


def _lookup_by_upc(upc: str, fetch) -> dict[str, object] | None:
    forms = [upc]
    if len(upc) == 12:
        forms.append("0" + upc)
    elif len(upc) == 13 and upc.startswith("0"):
        forms.append(upc[1:])
    for base, source in (
        ("https://world.openbeautyfacts.org/api/v0/product", "open_beauty_facts"),
        ("https://world.openfoodfacts.org/api/v0/product", "open_food_facts"),
    ):
        for form in forms:
            data = _safe_fetch(fetch, f"{base}/{form}.json")
            if not data or data.get("status") != 1:
                continue
            image, name = _image_from_product(data.get("product"))
            if image:
                return {
                    "status": "ok",
                    "image_url": image,
                    "product_name": name,
                    "source": source,
                }
    return None


def _lookup_by_name(name: str, fetch) -> dict[str, object] | None:
    query = urllib.parse.urlencode(
        {
            "search_terms": name,
            "search_simple": "1",
            "action": "process",
            "json": "1",
            "page_size": "3",
        }
    )
    data = _safe_fetch(fetch, f"https://world.openfoodfacts.org/cgi/search.pl?{query}")
    if not data:
        return None
    tokens = [t for t in _normalize_name(name).split(" ") if len(t) > 2]
    for product in data.get("products", []) or []:
        image, product_name = _image_from_product(product)
        if not image or not product_name:
            continue
        haystack = _normalize_name(product_name) or ""
        if any(token in haystack for token in tokens):
            return {
                "status": "ok",
                "image_url": image,
                "product_name": product_name,
                "source": "open_food_facts_search",
            }
    return None


def lookup_image(
    upc: str | None = None,
    name: str | None = None,
    fetch=None,
) -> dict[str, object]:
    """Return {status, image_url, product_name, source}.

    status is "ok" with an image_url, or "not_found" with image_url None.
    Never raises on a lookup failure.
    """
    fetch = fetch or _default_fetch
    upc = clean_upc(upc)
    norm_name = _normalize_name(name)
    key = (upc, norm_name)
    if key in _cache:
        return dict(_cache[key])

    result: dict[str, object] = {
        "status": "not_found",
        "image_url": None,
        "product_name": None,
        "source": None,
    }
    seeded = _load_seeded()
    if upc and f"upc:{upc}" in seeded:
        hit = seeded[f"upc:{upc}"]
        result = {
            "status": "ok",
            "image_url": hit.get("image_url"),
            "product_name": hit.get("product_name"),
            "source": "seeded",
        }
    elif norm_name and f"name:{norm_name}" in seeded:
        hit = seeded[f"name:{norm_name}"]
        result = {
            "status": "ok",
            "image_url": hit.get("image_url"),
            "product_name": hit.get("product_name"),
            "source": "seeded",
        }
    else:
        found = None
        if upc:
            found = _lookup_by_upc(upc, fetch)
        if found is None and norm_name:
            found = _lookup_by_name(norm_name, fetch)
        if found is not None:
            result = found
    _cache[key] = dict(result)
    return result

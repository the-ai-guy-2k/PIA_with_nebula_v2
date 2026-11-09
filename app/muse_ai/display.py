"""The PIA display object — the contract between Muse and the PIA server.

Architecture (Tee, Nov 8, 2026):
1. The UI (phone app) only snaps / uploads the receipt photo. It does
   NO extraction, NO product lookup, NO display logic.
2. Muse does all of it: receipt reading/extraction, product-picture
   lookup per item, grouping by purchase date/time, and the display
   shape (cards like Tee's screenshot: image + name, grouped
   "Sunday afternoon, Nov 1 · 6 items" style, search + count).
3. Muse returns ONE structured object to the server (this file's
   contract). The server stores it and hands it to the UI.
4. The UI just renders what the server gives it.

This is an extension of the hood AI layer (Muse extraction ->
Review & Confirm), not a replacement. A display object NEVER changes
confirmation state: a receipt display object is stored with the
status the extraction actually has, and the server refuses a
"confirmed" receipt display unless a confirmed purchase already
exists for that extraction.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.config import Settings

_OBJECT = "pia_display"
_VERSION = 1
_KINDS = ("receipt", "pantry")
_STATUSES = ("unconfirmed", "confirmed")
_PANTRY_STATUSES = ("in_stock", "used", "gone")
_IMAGE_SOURCES = (
    "seeded",
    "open_beauty_facts",
    "open_food_facts",
    "open_food_facts_search",
    "image_search",
)
_TOLERANCE = Decimal("0.02")
_MONEY = re.compile(r"^\$?(\d{1,6})\.(\d{2})$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UPC = re.compile(r"^\d{12,13}$")


class DisplayPayloadError(ValueError):
    """The Muse display object is malformed and cannot be stored."""


def _require(payload: dict, field: str) -> object:
    if field not in payload or payload[field] is None:
        raise DisplayPayloadError(f"Missing required field: {field}.")
    return payload[field]


def _money(value: object, field: str) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = f"{Decimal(str(value)):.2f}"
    if not isinstance(value, str):
        raise DisplayPayloadError(f"{field} must be a dollar amount like '6.97'.")
    match = _MONEY.match(value.strip().replace(",", ""))
    if not match:
        raise DisplayPayloadError(f"{field} must be a dollar amount like '6.97', got {value!r}.")
    return f"{match.group(1)}.{match.group(2)}"


def _decimal(text: str) -> Decimal:
    return Decimal(text)


def _quantity(value: object, field: str, minimum: int = 1) -> str:
    if isinstance(value, bool) or value is None:
        raise DisplayPayloadError(f"{field} must be a number.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise DisplayPayloadError(f"{field} must be a number, got {value!r}.") from None
    if number < minimum:
        raise DisplayPayloadError(f"{field} must be at least {minimum}.")
    return str(number.normalize())


def _image(item: dict, where: str) -> tuple[str | None, str | None, str | None]:
    url = item.get("image_url")
    source = item.get("image_source")
    confidence = item.get("image_confidence")
    if url is None:
        if source is not None or confidence is not None:
            raise DisplayPayloadError(
                f"{where}: image_source/image_confidence must be null when image_url is null."
            )
        return None, None, None
    if not isinstance(url, str) or not url.startswith("https://") or "@" in url.split("/")[2]:
        raise DisplayPayloadError(f"{where}: image_url must be a plain https URL.")
    if source not in _IMAGE_SOURCES:
        raise DisplayPayloadError(f"{where}: image_source must be one of {_IMAGE_SOURCES}.")
    if confidence not in ("high", "medium", "low"):
        raise DisplayPayloadError(f"{where}: image_confidence must be high, medium, or low.")
    return url, str(source), str(confidence)


def _validate_item(item: object, kind: str, where: str) -> dict:
    if not isinstance(item, dict):
        raise DisplayPayloadError(f"{where}: item must be an object.")
    name = _require(item, "name")
    if not isinstance(name, str) or not name.strip():
        raise DisplayPayloadError(f"{where}: name must be a non-empty string.")
    image_url, image_source, image_confidence = _image(item, where)
    out: dict[str, object] = {
        "name": name.strip(),
        "image_url": image_url,
        "image_source": image_source,
        "image_confidence": image_confidence,
    }
    if kind == "receipt":
        line_id = _require(item, "line_id")
        if not isinstance(line_id, str) or not line_id:
            raise DisplayPayloadError(f"{where}: line_id must be a non-empty string.")
        raw_text = item.get("raw_text")
        if raw_text is not None and not isinstance(raw_text, str):
            raise DisplayPayloadError(f"{where}: raw_text must be a string.")
        upc = item.get("upc")
        if upc is not None and (not isinstance(upc, str) or not _UPC.match(upc)):
            raise DisplayPayloadError(f"{where}: upc must be 12 or 13 digits.")
        quantity = _quantity(_require(item, "quantity"), f"{where}.quantity")
        unit_price = _money(_require(item, "unit_price"), f"{where}.unit_price")
        line_total = _money(_require(item, "line_total"), f"{where}.line_total")
        expected = _decimal(unit_price) * _decimal(quantity)
        if abs(_decimal(line_total) - expected) > _TOLERANCE:
            raise DisplayPayloadError(
                f"{where}: line_total {line_total} != quantity x unit_price ({expected})."
            )
        out.update(
            {
                "line_id": line_id,
                "raw_text": raw_text,
                "upc": upc,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )
    else:
        pantry_item_id = _require(item, "pantry_item_id")
        if not isinstance(pantry_item_id, str) or not pantry_item_id:
            raise DisplayPayloadError(f"{where}: pantry_item_id must be a non-empty string.")
        pantry_status = _require(item, "pantry_status")
        if pantry_status not in _PANTRY_STATUSES:
            raise DisplayPayloadError(f"{where}: pantry_status must be one of {_PANTRY_STATUSES}.")
        out.update(
            {
                "pantry_item_id": pantry_item_id,
                "qty_on_hand": _quantity(_require(item, "qty_on_hand"), f"{where}.qty_on_hand", minimum=0),
                "pantry_status": pantry_status,
            }
        )
    return out


def validate_display_payload(payload: object) -> dict:
    """Turn an untrusted Muse display JSON object into a validated one.

    Raises DisplayPayloadError on any malformed field or any total that
    does not add up. A photo Muse could not find stays image_url null —
    never invented, never a wrong product's picture.
    """
    if not isinstance(payload, dict):
        raise DisplayPayloadError("Display object must be a JSON object.")
    if payload.get("object") != _OBJECT:
        raise DisplayPayloadError(f"object must be '{_OBJECT}'.")
    if payload.get("version") != _VERSION:
        raise DisplayPayloadError(f"version must be {_VERSION}.")
    kind = _require(payload, "kind")
    if kind not in _KINDS:
        raise DisplayPayloadError(f"kind must be one of {_KINDS}.")
    if payload.get("built_by") != "muse_ai":
        raise DisplayPayloadError("built_by must be 'muse_ai'.")
    built_at = _require(payload, "built_at")
    if not isinstance(built_at, str) or not built_at:
        raise DisplayPayloadError("built_at must be an ISO timestamp string.")
    status = _require(payload, "status")
    if status not in _STATUSES:
        raise DisplayPayloadError(f"status must be one of {_STATUSES}.")
    left = _require(payload, "left_count")
    if not isinstance(left, dict):
        raise DisplayPayloadError("left_count must be an object.")
    shown = left.get("shown")
    total_left = left.get("total")
    if not isinstance(shown, int) or not isinstance(total_left, int) or shown < 0 or total_left < 0:
        raise DisplayPayloadError("left_count.shown/total must be non-negative integers.")
    if shown > total_left:
        raise DisplayPayloadError("left_count.shown cannot exceed left_count.total.")
    groups = _require(payload, "groups")
    if not isinstance(groups, list) or not groups:
        raise DisplayPayloadError("groups must be a non-empty list.")
    norm_groups = []
    total_items = 0
    in_stock = 0
    for gi, group in enumerate(groups):
        where = f"groups[{gi}]"
        if not isinstance(group, dict):
            raise DisplayPayloadError(f"{where} must be an object.")
        group_id = _require(group, "group_id")
        heading = _require(group, "heading")
        if not isinstance(group_id, str) or not group_id:
            raise DisplayPayloadError(f"{where}.group_id must be a non-empty string.")
        if not isinstance(heading, str) or not heading:
            raise DisplayPayloadError(f"{where}.heading must be a non-empty string.")
        items = _require(group, "items")
        if not isinstance(items, list) or not items:
            raise DisplayPayloadError(f"{where}.items must be a non-empty list.")
        item_count = _require(group, "item_count")
        if item_count != len(items):
            raise DisplayPayloadError(
                f"{where}.item_count ({item_count}) != number of items ({len(items)})."
            )
        norm_items = [_validate_item(it, kind, f"{where}.items[{i}]") for i, it in enumerate(items)]
        total_items += len(norm_items)
        if kind == "pantry":
            in_stock += sum(1 for it in norm_items if it.get("pantry_status") == "in_stock")
        norm_groups.append({"group_id": group_id, "heading": heading, "item_count": len(norm_items), "items": norm_items})
    out: dict[str, object] = {
        "object": _OBJECT,
        "version": _VERSION,
        "kind": kind,
        "status": status,
        "left_count": {"shown": shown, "total": total_left},
        "groups": norm_groups,
        "built_by": "muse_ai",
        "built_at": built_at,
    }
    for field in ("evidence_id", "extraction_id", "merchant", "purchase_date", "purchase_time", "search_placeholder"):
        out[field] = payload.get(field)
    if kind == "receipt":
        merchant = _require(payload, "merchant")
        if not isinstance(merchant, str) or not merchant.strip():
            raise DisplayPayloadError("merchant must be a non-empty string.")
        purchase_date = payload.get("purchase_date")
        if purchase_date is not None and (not isinstance(purchase_date, str) or not _DATE.match(purchase_date)):
            raise DisplayPayloadError("purchase_date must be YYYY-MM-DD.")
        subtotal = _money(_require(payload, "subtotal"), "subtotal")
        tax = _money(_require(payload, "tax"), "tax")
        total = _money(_require(payload, "total"), "total")
        lines_sum = sum(
            (_decimal(it["line_total"]) for g in norm_groups for it in g["items"]),
            Decimal("0"),
        )
        reconciled = abs(lines_sum - _decimal(subtotal)) <= _TOLERANCE and abs(
            _decimal(subtotal) + _decimal(tax) - _decimal(total)
        ) <= _TOLERANCE
        if payload.get("totals_reconciled") is not reconciled:
            raise DisplayPayloadError(
                f"totals_reconciled must be {str(reconciled).lower()}: "
                f"lines sum {lines_sum}, subtotal {subtotal}, tax {tax}, total {total}."
            )
        if shown != total_items or total_left != total_items:
            raise DisplayPayloadError(
                "Receipt left_count must equal the number of lines (all lines are shown)."
            )
        out.update(
            {
                "merchant": merchant.strip(),
                "purchase_date": purchase_date,
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
                "totals_reconciled": reconciled,
            }
        )
    else:
        if shown != in_stock or total_left != in_stock:
            raise DisplayPayloadError(
                f"Pantry left_count must equal the in-stock count ({in_stock})."
            )
        out.update({"merchant": None, "purchase_date": None, "subtotal": None, "tax": None, "total": None, "totals_reconciled": None})
    return out


_SCHEMA = """
CREATE TABLE IF NOT EXISTS muse_ai_display (
    display_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def init_display_db(settings: Settings) -> None:
    path = settings.data_dir / "muse_ai" / "muse_ai.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def _db_path(settings: Settings):
    return settings.data_dir / "muse_ai" / "muse_ai.sqlite"


def store_display(settings: Settings, display_key: str, kind: str, payload: dict) -> dict:
    init_display_db(settings)
    now = datetime.now(timezone.utc).isoformat()
    connection = sqlite3.connect(_db_path(settings))
    try:
        connection.execute(
            """
            INSERT INTO muse_ai_display (display_key, kind, payload_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(display_key) DO UPDATE SET
                kind = excluded.kind,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (display_key, kind, json.dumps(payload), now),
        )
        connection.commit()
    finally:
        connection.close()
    stored = dict(payload)
    stored["stored_at"] = now
    return stored


def read_display(settings: Settings, display_key: str) -> dict | None:
    path = _db_path(settings)
    if not path.exists():
        return None
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM muse_ai_display WHERE display_key = ?", (display_key,)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    payload["stored_at"] = row["updated_at"]
    return payload


def read_latest_display(settings: Settings, kind: str) -> dict | None:
    path = _db_path(settings)
    if not path.exists():
        return None
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM muse_ai_display WHERE kind = ? ORDER BY updated_at DESC LIMIT 1",
            (kind,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    payload["stored_at"] = row["updated_at"]
    return payload

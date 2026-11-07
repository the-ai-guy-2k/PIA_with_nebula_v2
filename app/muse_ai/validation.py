"""Validate a Muse-produced extraction JSON.

Strict about types and arithmetic, honest about uncertainty:
- A line total that disagrees with qty x price is FLAGGED, never fixed.
- A subtotal/total that disagrees with the line sum is FLAGGED, never fixed.
- A field Muse could not read becomes None — never invented.
- Confidence is per line: high (all fields read cleanly), medium (something
  inferred, e.g. quantity assumed 1), low (a value guessed or unreadable).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.muse_ai.models import MuseExtraction, MuseLine

_CENT = Decimal("0.01")
_TOLERANCE = Decimal("0.02")
_MONEY = re.compile(r"^\$?(\d{1,6})\.(\d{2})$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MusePayloadError(ValueError):
    """The Muse extraction JSON is malformed and cannot be stored."""


def _money(value: object, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = f"{Decimal(str(value)):.2f}"
    if not isinstance(value, str):
        raise MusePayloadError(f"{field} must be a dollar amount like '6.97'.")
    text = value.strip().replace(",", "")
    match = _MONEY.match(text)
    if not match:
        raise MusePayloadError(f"{field} must be a dollar amount like '6.97', got {value!r}.")
    return f"{match.group(1)}.{match.group(2)}"


def _decimal(text: str) -> Decimal:
    return Decimal(text)


def _quantity(value: object) -> str:
    if value is None:
        return "1"
    if isinstance(value, bool):
        raise MusePayloadError("quantity must be a number.")
    if isinstance(value, int):
        if value < 1:
            raise MusePayloadError("quantity must be at least 1.")
        return str(value)
    if isinstance(value, float):
        if value < 1:
            raise MusePayloadError("quantity must be at least 1.")
        return str(value).rstrip("0").rstrip(".") or "1"
    if isinstance(value, str) and value.strip():
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            raise MusePayloadError(f"quantity must be a number, got {value!r}.") from None
        if number < 1:
            raise MusePayloadError("quantity must be at least 1.")
        return str(number.normalize())
    raise MusePayloadError("quantity must be a number.")


def _confidence(value: object) -> str:
    if value in ("high", "medium", "low"):
        return str(value)
    if value is None:
        return "medium"
    raise MusePayloadError("confidence must be 'high', 'medium', or 'low'.")


def validate_muse_payload(payload: object) -> MuseExtraction:
    """Turn an untrusted Muse JSON object into a validated extraction.

    Raises MusePayloadError on anything malformed. Arithmetic disagreements
    do NOT raise — they are flagged on the result for Review.
    """
    if not isinstance(payload, dict):
        raise MusePayloadError("extraction must be a JSON object.")
    if payload.get("source") not in (None, "muse_ai", "muse"):
        raise MusePayloadError("source must be 'muse_ai' when present.")

    merchant = payload.get("merchant")
    if merchant is not None and (not isinstance(merchant, str) or not merchant.strip()):
        raise MusePayloadError("merchant must be a name or null.")
    merchant = merchant.strip() if isinstance(merchant, str) else None

    purchase_date = payload.get("purchase_date")
    if purchase_date is not None:
        if not isinstance(purchase_date, str) or not _DATE.match(purchase_date.strip()):
            raise MusePayloadError("purchase_date must be ISO YYYY-MM-DD or null.")
        purchase_date = purchase_date.strip()
    purchase_time = payload.get("purchase_time")
    if purchase_time is not None and (not isinstance(purchase_time, str) or not purchase_time.strip()):
        raise MusePayloadError("purchase_time must be a time or null.")
    purchase_time = purchase_time.strip() if isinstance(purchase_time, str) else None

    subtotal = _money(payload.get("subtotal"), "subtotal")
    tax = _money(payload.get("tax"), "tax")
    total = _money(payload.get("total"), "total")

    raw_lines = payload.get("lines")
    if raw_lines is None:
        raw_lines = []
    if not isinstance(raw_lines, list):
        raise MusePayloadError("lines must be a list.")
    if len(raw_lines) > 500:
        raise MusePayloadError("lines has too many entries (max 500).")

    lines: list[MuseLine] = []
    flags: list[str] = []
    lines_sum = Decimal("0.00")
    for index, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            raise MusePayloadError(f"line {index} must be an object.")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise MusePayloadError(f"line {index} needs a name.")
        quantity = _quantity(raw.get("quantity"))
        unit_price = _money(raw.get("unit_price"), f"line {index} unit_price")
        line_total = _money(raw.get("line_total"), f"line {index} line_total")
        if line_total is None:
            raise MusePayloadError(f"line {index} needs a line_total.")
        raw_text = raw.get("raw_text")
        if raw_text is not None and not isinstance(raw_text, str):
            raise MusePayloadError(f"line {index} raw_text must be text.")
        confidence = _confidence(raw.get("confidence"))
        line_total_ok = True
        if unit_price is not None:
            expected = _decimal(quantity) * _decimal(unit_price)
            if abs(expected - _decimal(line_total)) > _TOLERANCE:
                line_total_ok = False
                flags.append(
                    f"line {index} ({name.strip()[:40]}): qty x price is "
                    f"${expected:.2f} but the receipt line total is ${line_total}."
                )
        lines_sum += _decimal(line_total)
        lines.append(
            MuseLine(
                name=name.strip(),
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
                raw_text=(raw_text or name).strip(),
                confidence=confidence,
                line_total_ok=line_total_ok,
            )
        )

    lines_sum_text = f"{lines_sum:.2f}"
    totals_reconciled = True
    total_mismatch = False
    if subtotal is not None and abs(_decimal(subtotal) - lines_sum) > _TOLERANCE:
        totals_reconciled = False
        total_mismatch = True
        flags.append(
            f"lines sum to ${lines_sum_text} but the receipt subtotal is ${subtotal}."
        )
    if subtotal is not None and tax is not None and total is not None:
        if abs((_decimal(subtotal) + _decimal(tax)) - _decimal(total)) > _TOLERANCE:
            totals_reconciled = False
            total_mismatch = True
            flags.append(
                f"subtotal ${subtotal} + tax ${tax} is not the receipt total ${total}."
            )
    if not lines:
        totals_reconciled = False

    return MuseExtraction(
        merchant=merchant,
        purchase_date=purchase_date,
        purchase_time=purchase_time,
        subtotal=subtotal,
        tax=tax,
        total=total,
        lines=tuple(lines),
        lines_sum=lines_sum_text,
        totals_reconciled=totals_reconciled,
        total_mismatch=total_mismatch,
        flags=tuple(flags),
    )

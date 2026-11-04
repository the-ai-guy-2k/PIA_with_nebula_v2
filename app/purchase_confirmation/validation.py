"""Server-side checks for a confirmation submission."""

from __future__ import annotations

import re
from datetime import date

from app.purchase_confirmation.errors import ConfirmationRejected

_MONEY = re.compile(r"\A\$?\d{1,6}(?:\.\d{1,2})?\Z")
_QUANTITY = re.compile(r"\A\d{1,4}(?:\.\d{1,3})?\Z")
_DATE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})\Z")
_TIME = re.compile(r"\A(\d{2}):(\d{2})(?::(\d{2}))?\Z")


def clean_optional_label(value: object, field_name: str, max_length: int) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfirmationRejected(f"Enter a valid {field_name} or leave the field blank.")
    cleaned = _printable(" ".join(value.split()))
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ConfirmationRejected(f"The {field_name} is too long.")
    return cleaned


def require_item_name(value: object) -> str:
    if not isinstance(value, str):
        raise ConfirmationRejected("Each confirmed item needs a name.")
    cleaned = _printable(" ".join(value.split()))
    if not cleaned:
        raise ConfirmationRejected("Each confirmed item needs a name.")
    if len(cleaned) > 200:
        raise ConfirmationRejected("An item name is too long.")
    return cleaned


def parse_money(value: object, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or _MONEY.fullmatch(value.strip()) is None:
        raise ConfirmationRejected(f"Enter a valid {field_name} or leave the field blank.")
    amount = value.strip().lstrip("$")
    if "." not in amount:
        whole, fraction = amount, "00"
    else:
        whole, fraction = amount.split(".")
        fraction = fraction.ljust(2, "0")
    return f"{int(whole)}.{fraction}"


def parse_quantity(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or _QUANTITY.fullmatch(value.strip()) is None:
        raise ConfirmationRejected("Enter a valid quantity or leave the field blank.")
    number = float(value.strip())
    if number <= 0:
        raise ConfirmationRejected("Enter a valid quantity or leave the field blank.")
    whole, _, fraction = value.strip().partition(".")
    fraction = fraction.rstrip("0")
    if not fraction:
        return str(int(whole))
    return f"{int(whole)}.{fraction}"


def parse_date(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfirmationRejected("Enter a valid date or leave the field blank.")
    match = _DATE.fullmatch(value.strip())
    if match is None:
        raise ConfirmationRejected("Enter a valid date or leave the field blank.")
    year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if year < 1990 or year > date.today().year + 1:
        raise ConfirmationRejected("Enter a valid date or leave the field blank.")
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        raise ConfirmationRejected("Enter a valid date or leave the field blank.") from None


def parse_time(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfirmationRejected("Enter a valid time or leave the field blank.")
    match = _TIME.fullmatch(value.strip())
    if match is None:
        raise ConfirmationRejected("Enter a valid time or leave the field blank.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        raise ConfirmationRejected("Enter a valid time or leave the field blank.")
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _printable(value: str) -> str:
    return "".join(character for character in value if character.isprintable()).strip()

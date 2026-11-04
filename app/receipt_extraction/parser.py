"""Turn recognized receipt lines into unconfirmed candidates.

Normalization only cleans spacing, casing, and obvious quantity or price tokens.
It does not invent a merchant, a date, a product, or an amount.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

_MONEY = re.compile(r"(?<![\w.])\$?(\d{1,6})\.(\d{2})(?![\w.])")
_AMBIGUOUS_AMOUNT = re.compile(
    r"(?<![\w])\$?(?:\d+[A-Za-z]\d*\.[\dA-Za-z]+|\d+\.[A-Za-z]\d*|[A-Za-z]\.\s*\d{2})(?![\w])"
)
_QTY = re.compile(r"\b(\d{1,3})\s*@\s*\$?(\d{1,6}\.\d{2})\b")
_PRICE_ONLY = re.compile(r"\A\$?\d{1,6}\.\d{2}\Z")
_SUBTOTAL = re.compile(r"\Asub[\s-]*total\b", re.IGNORECASE)
_TOTAL_TAX = re.compile(r"\Atotal\s+tax\b", re.IGNORECASE)
_TAX = re.compile(r"\Atax\b", re.IGNORECASE)
_TOTAL = re.compile(r"\A(?:grand\s+)?total\b|\Aamount\s+due\b|\Abalance\s+due\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
_ADDRESS = re.compile(
    r"\b(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr)\b\.?",
    re.IGNORECASE,
)
_STREET_NUMBER = re.compile(r"\A\d{1,6}\s+[A-Za-z]")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MDY_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_SPACED_DATE = re.compile(r"\b(\d{1,2})\s+(\d{1,2})\s+(\d{4})\b")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?\b")
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_DATE = re.compile(rf"\b({_MONTH_PATTERN})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE)
_DAY_MONTH_DATE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_PATTERN})\s+(\d{{4}})\b", re.IGNORECASE)
_STOPWORDS = {
    "receipt",
    "welcome",
    "thank",
    "thanks",
    "you",
    "customer",
    "copy",
    "original",
    "store",
    "phone",
    "tel",
    "cashier",
    "date",
    "time",
    "visa",
    "debit",
    "credit",
    "cash",
    "change",
}


@dataclass(frozen=True)
class ParsedLine:
    raw_text: str
    normalized_name_candidate: str | None
    quantity_candidate: str | None
    unit_price_candidate: str | None
    line_total_candidate: str | None


@dataclass(frozen=True)
class ParsedReceipt:
    merchant_raw: str | None
    merchant_normalized_candidate: str | None
    purchase_date_candidate: str | None
    purchase_time_candidate: str | None
    subtotal_candidate: str | None
    tax_candidate: str | None
    total_candidate: str | None
    raw_text: str
    extraction_status: str
    lines: tuple[ParsedLine, ...]


def parse_receipt_text(lines: list[str]) -> ParsedReceipt:
    cleaned = [line.strip() for line in lines if line and line.strip()]
    raw_text = "\n".join(cleaned)
    if not cleaned:
        return _empty("no_text")

    purchase_date = _first_date(cleaned)
    purchase_time = _first_time(cleaned)
    summary_end = _first_structured_index(cleaned)
    merchant_raw, merchant_normalized = _merchant(cleaned[:summary_end])
    subtotal, tax, total, item_lines = _items_and_totals(cleaned)

    if (
        merchant_raw is None
        and purchase_date is None
        and purchase_time is None
        and subtotal is None
        and tax is None
        and total is None
        and not item_lines
    ):
        status = "insufficient_data"
    else:
        status = "extracted"

    return ParsedReceipt(
        merchant_raw=merchant_raw,
        merchant_normalized_candidate=merchant_normalized,
        purchase_date_candidate=purchase_date,
        purchase_time_candidate=purchase_time,
        subtotal_candidate=subtotal,
        tax_candidate=tax,
        total_candidate=total,
        raw_text=raw_text,
        extraction_status=status,
        lines=tuple(item_lines),
    )


def _empty(status: str) -> ParsedReceipt:
    return ParsedReceipt(
        merchant_raw=None,
        merchant_normalized_candidate=None,
        purchase_date_candidate=None,
        purchase_time_candidate=None,
        subtotal_candidate=None,
        tax_candidate=None,
        total_candidate=None,
        raw_text="",
        extraction_status=status,
        lines=(),
    )


def _first_structured_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if _summary_kind(line) is not None or _is_item_line(line):
            return index
    return len(lines)


def _merchant(header_lines: list[str]) -> tuple[str | None, str | None]:
    for line in header_lines:
        if not _looks_like_merchant(line):
            continue
        return line, _normalize_label(line)
    return None, None


def _looks_like_merchant(line: str) -> bool:
    if _find_date(line) is not None or _line_is_time_only(line):
        return False
    if _PHONE.search(line) or _ADDRESS.search(line) or _STREET_NUMBER.search(line):
        return False
    letters = [character for character in line if character.isalpha()]
    if len(letters) < 3 or len(line) > 40:
        return False
    words = re.findall(r"[A-Za-z]+", line)
    if not words or all(word.lower() in _STOPWORDS for word in words):
        return False
    return True


def _items_and_totals(
    lines: list[str],
) -> tuple[str | None, str | None, str | None, list[ParsedLine]]:
    subtotal = None
    tax = None
    total = None
    items: list[ParsedLine] = []
    pending: ParsedLine | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            items.append(pending)
            pending = None

    for line in lines:
        kind = _summary_kind(line)
        if kind is not None:
            flush()
            amount = _single_money(line)
            if kind == "subtotal" and subtotal is None:
                subtotal = amount
            elif kind == "tax" and tax is None:
                tax = amount
            elif kind == "total" and total is None:
                total = amount
            continue
        if pending is not None and _PRICE_ONLY.fullmatch(line) and _can_attach_price(pending):
            pending = ParsedLine(
                raw_text=f"{pending.raw_text} {line}",
                normalized_name_candidate=pending.normalized_name_candidate,
                quantity_candidate=pending.quantity_candidate,
                unit_price_candidate=pending.unit_price_candidate,
                line_total_candidate=_format_money(_MONEY.search(line)),
            )
            continue
        if _is_item_line(line):
            flush()
            pending = _parse_item(line)
            continue
        flush()
    flush()
    return subtotal, tax, total, items


def _summary_kind(line: str) -> str | None:
    if _SUBTOTAL.search(line):
        return "subtotal"
    if _TOTAL_TAX.search(line) or _TAX.search(line):
        return "tax"
    if _TOTAL.search(line):
        return "total"
    return None


def _is_item_line(line: str) -> bool:
    if _summary_kind(line) is not None or _PRICE_ONLY.fullmatch(line):
        return False
    return _MONEY.search(line) is not None or _AMBIGUOUS_AMOUNT.search(line) is not None or _QTY.search(line) is not None


def _can_attach_price(line: ParsedLine) -> bool:
    return line.line_total_candidate is None and line.unit_price_candidate is None


def _parse_item(line: str) -> ParsedLine:
    quantity_match = _QTY.search(line)
    quantity = str(int(quantity_match.group(1))) if quantity_match else None
    unit_price = _format_amount(quantity_match.group(2)) if quantity_match else None
    amounts = list(_MONEY.finditer(line))
    line_total = None
    if amounts:
        last_amount = _format_money(amounts[-1])
        if unit_price is None or last_amount != unit_price:
            line_total = last_amount
    name = _item_name(line, quantity_match, amounts)
    return ParsedLine(
        raw_text=line,
        normalized_name_candidate=name,
        quantity_candidate=quantity,
        unit_price_candidate=unit_price,
        line_total_candidate=line_total,
    )


def _item_name(line: str, quantity_match: re.Match[str] | None, amounts: list[re.Match[str]]) -> str | None:
    masked = list(line)
    spans = [(match.start(), match.end()) for match in amounts]
    spans.extend((match.start(), match.end()) for match in _AMBIGUOUS_AMOUNT.finditer(line))
    if quantity_match is not None:
        spans.append((quantity_match.start(), quantity_match.end()))
    for start, end in spans:
        for index in range(start, end):
            masked[index] = " "
    return _normalize_label("".join(masked))


def _single_money(line: str) -> str | None:
    amounts = list(_MONEY.finditer(line))
    if len(amounts) != 1 or _AMBIGUOUS_AMOUNT.search(line):
        return None
    return _format_money(amounts[0])


def _format_money(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    return _format_amount(f"{match.group(1)}.{match.group(2)}")


def _format_amount(value: str) -> str:
    whole, fraction = value.split(".")
    return f"{int(whole)}.{fraction}"


def _normalize_label(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" \t.,;:-")
    if not cleaned or not any(character.isalpha() for character in cleaned):
        return None
    if cleaned.isupper():
        return cleaned.title()
    return cleaned


def _first_date(lines: list[str]) -> str | None:
    for line in lines:
        found = _find_date(line)
        if found is not None:
            return found.isoformat()
    return None


def _find_date(line: str) -> date | None:
    iso_match = _ISO_DATE.search(line)
    if iso_match:
        found = _valid_date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        if found is not None:
            return found
    mdy_match = _MDY_DATE.search(line)
    if mdy_match:
        found = _valid_date(int(mdy_match.group(3)), int(mdy_match.group(1)), int(mdy_match.group(2)))
        if found is not None:
            return found
    month_match = _MONTH_DATE.search(line)
    if month_match:
        found = _valid_date(
            int(month_match.group(3)),
            _MONTHS[month_match.group(1).lower()],
            int(month_match.group(2)),
        )
        if found is not None:
            return found
    day_month_match = _DAY_MONTH_DATE.search(line)
    if day_month_match:
        found = _valid_date(
            int(day_month_match.group(3)),
            _MONTHS[day_month_match.group(2).lower()],
            int(day_month_match.group(1)),
        )
        if found is not None:
            return found
    spaced_match = _SPACED_DATE.search(line)
    if spaced_match:
        return _valid_date(int(spaced_match.group(3)), int(spaced_match.group(1)), int(spaced_match.group(2)))
    return None


def _valid_date(year: int, month: int, day: int) -> date | None:
    if year < 1990 or year > date.today().year + 1:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _first_time(lines: list[str]) -> str | None:
    for line in lines:
        match = _TIME.search(line)
        if match is None:
            continue
        parsed = _valid_time(match)
        if parsed is not None:
            return parsed
    return None


def _line_is_time_only(line: str) -> bool:
    match = _TIME.search(line)
    if match is None:
        return False
    remainder = _TIME.sub(" ", line)
    return _normalize_label(remainder) is None


def _valid_time(match: re.Match[str]) -> str | None:
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    meridiem = match.group(4)
    if minute > 59 or second > 59:
        return None
    if meridiem:
        if hour < 1 or hour > 12:
            return None
        if meridiem.lower() == "pm" and hour != 12:
            hour += 12
        if meridiem.lower() == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        return None
    return f"{hour:02d}:{minute:02d}:{second:02d}"

"""Conservative merchant check. The stored merchant text is not changed.

A merchant matches only when the name, after casefolding and turning hyphens
into spaces, is exactly Walmart or Wal Mart, or starts with one of those
followed by a space. Super Walmart and unrelated names do not match.
"""

from __future__ import annotations


def is_walmart_merchant(merchant: str | None) -> bool:
    if not isinstance(merchant, str):
        return False
    normalized = " ".join(merchant.casefold().replace("-", " ").split())
    return (
        normalized == "walmart"
        or normalized.startswith("walmart ")
        or normalized == "wal mart"
        or normalized.startswith("wal mart ")
    )

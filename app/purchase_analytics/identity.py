"""Derived comparison key. This does not change the stored item name.

Rule, in order:
1. Trim surrounding whitespace.
2. Collapse any internal run of whitespace to one space.
3. Apply Unicode casefold.
Punctuation and word differences are preserved.
"""

from __future__ import annotations


def analytics_key(item_name: str) -> str:
    return " ".join(item_name.split()).casefold()

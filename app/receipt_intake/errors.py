"""User-facing intake failures."""

from __future__ import annotations


class IntakeRejected(Exception):
    """A receipt upload was rejected before any evidence was stored."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

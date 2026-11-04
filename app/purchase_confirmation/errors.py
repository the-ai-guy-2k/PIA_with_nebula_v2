"""Confirmation failures that leave evidence and extraction unchanged."""

from __future__ import annotations


class ExtractionNotFound(Exception):
    """No extraction exists for the requested id."""


class ConfirmationRejected(Exception):
    """The confirmation was rejected before any purchase was stored."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AlreadyConfirmed(Exception):
    """This extraction already has its one confirmed purchase."""

    def __init__(self, purchase_id: str) -> None:
        super().__init__(purchase_id)
        self.purchase_id = purchase_id

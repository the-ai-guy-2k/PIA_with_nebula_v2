"""Failures while reading a preserved receipt."""

from __future__ import annotations


class EvidenceNotFound(Exception):
    """No preserved receipt exists for the requested evidence id."""


class UnreadableReceipt(Exception):
    """The preserved image could not be decoded or recognized."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

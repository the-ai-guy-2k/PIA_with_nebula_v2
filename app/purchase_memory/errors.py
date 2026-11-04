"""Failures while remembering a confirmed purchase."""


class PurchaseNotFound(Exception):
    """The purchase id does not identify a confirmed purchase."""


class MemoryNotFound(Exception):
    """The memory id does not identify a remembered purchase."""


class MemoryRejected(Exception):
    """The memory request cannot be applied."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

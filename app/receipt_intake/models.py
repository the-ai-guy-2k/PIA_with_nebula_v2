"""Minimum receipt-evidence record."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

_EVIDENCE_ID = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z"
)


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    original_filename: str
    storage_reference: str
    mime_type: str
    byte_size: int
    uploaded_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": "accepted",
            "evidence_id": self.evidence_id,
            "original_filename": self.original_filename,
            "storage_reference": self.storage_reference,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "uploaded_at": self.uploaded_at,
        }


def parse_evidence_id(value: str) -> str | None:
    """Return a canonical id, or None when the value is not a v4 UUID."""
    if not isinstance(value, str) or _EVIDENCE_ID.fullmatch(value) is None:
        return None
    return str(uuid.UUID(value))

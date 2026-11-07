"""File queue for the Muse AI loop.

One JSON file per receipt under <data_dir>/muse_ai_queue/<evidence_id>.json.
The queue is only a mailbox: it never executes anything, never touches the
original receipt image, and never changes a purchase or pantry item.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.muse_ai.models import QueueRecord

_STATUSES = {"queued", "processing", "done", "done_with_mismatch", "failed"}


def _queue_dir(settings: Settings) -> Path:
    return settings.data_dir / "muse_ai_queue"


def _path(settings: Settings, evidence_id: str) -> Path:
    return _queue_dir(settings) / f"{evidence_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_record(settings: Settings, evidence_id: str, ocr_text: str = "") -> QueueRecord:
    _queue_dir(settings).mkdir(parents=True, exist_ok=True)
    existing = read_record(settings, evidence_id)
    record = QueueRecord(
        evidence_id=evidence_id,
        status="queued",
        queued_at=existing.queued_at if existing else _now(),
        ocr_text=ocr_text,
        updated_at=_now(),
    )
    _write(settings, record)
    return record


def read_record(settings: Settings, evidence_id: str) -> QueueRecord | None:
    path = _path(settings, evidence_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return QueueRecord(
        evidence_id=data["evidence_id"],
        status=data["status"],
        queued_at=data["queued_at"],
        ocr_text=data.get("ocr_text", ""),
        error=data.get("error"),
        extraction_id=data.get("extraction_id"),
        updated_at=data.get("updated_at", ""),
    )


def list_records(settings: Settings) -> list[QueueRecord]:
    directory = _queue_dir(settings)
    if not directory.exists():
        return []
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records.append(
                QueueRecord(
                    evidence_id=data["evidence_id"],
                    status=data["status"],
                    queued_at=data["queued_at"],
                    ocr_text=data.get("ocr_text", ""),
                    error=data.get("error"),
                    extraction_id=data.get("extraction_id"),
                    updated_at=data.get("updated_at", ""),
                )
            )
        except (json.JSONDecodeError, KeyError):
            continue
    return records


def set_status(
    settings: Settings,
    evidence_id: str,
    status: str,
    error: str | None = None,
    extraction_id: str | None = None,
) -> QueueRecord:
    if status not in _STATUSES:
        raise ValueError(f"unknown queue status {status!r}")
    existing = read_record(settings, evidence_id)
    if existing is None:
        raise KeyError(f"no queue entry for {evidence_id}")
    record = QueueRecord(
        evidence_id=evidence_id,
        status=status,
        queued_at=existing.queued_at,
        ocr_text=existing.ocr_text,
        error=error,
        extraction_id=extraction_id or existing.extraction_id,
        updated_at=_now(),
    )
    _write(settings, record)
    return record


def _write(settings: Settings, record: QueueRecord) -> None:
    path = _path(settings, record.evidence_id)
    path.write_text(
        json.dumps(
            {
                "evidence_id": record.evidence_id,
                "status": record.status,
                "queued_at": record.queued_at,
                "updated_at": record.updated_at,
                "ocr_text": record.ocr_text,
                "error": record.error,
                "extraction_id": record.extraction_id,
                "source": "muse_ai",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

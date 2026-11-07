"""Audit record for a Muse AI extraction.

Kept apart from the extraction itself: the extraction record stays in the
existing format the Review screen already reads; this table is the audit
trail that says Muse produced it, whether the totals reconciled, and what
confidence each line carried.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.config import Settings
from app.muse_ai.models import MuseAudit

_SCHEMA = """
CREATE TABLE IF NOT EXISTS muse_ai_extraction (
    extraction_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL,
    source TEXT NOT NULL,
    model TEXT NOT NULL,
    totals_reconciled INTEGER NOT NULL,
    lines_sum TEXT NOT NULL,
    total_mismatch INTEGER NOT NULL,
    confidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def init_muse_ai_db(settings: Settings) -> None:
    path = settings.data_dir / "muse_ai" / "muse_ai.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def record_audit(settings: Settings, audit: MuseAudit) -> MuseAudit:
    path = settings.data_dir / "muse_ai" / "muse_ai.sqlite"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT OR REPLACE INTO muse_ai_extraction (
                extraction_id, evidence_id, source, model, totals_reconciled,
                lines_sum, total_mismatch, confidence_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit.extraction_id,
                audit.evidence_id,
                audit.source,
                audit.model,
                1 if audit.totals_reconciled else 0,
                audit.lines_sum,
                1 if audit.total_mismatch else 0,
                json.dumps(audit.confidence),
                audit.created_at or datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return audit


def read_audit(settings: Settings, extraction_id: str) -> MuseAudit | None:
    path = settings.data_dir / "muse_ai" / "muse_ai.sqlite"
    if not path.exists():
        return None
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM muse_ai_extraction WHERE extraction_id = ?",
            (extraction_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return MuseAudit(
        extraction_id=row["extraction_id"],
        evidence_id=row["evidence_id"],
        source=row["source"],
        model=row["model"],
        totals_reconciled=bool(row["totals_reconciled"]),
        lines_sum=row["lines_sum"],
        total_mismatch=bool(row["total_mismatch"]),
        confidence=json.loads(row["confidence_json"]),
        created_at=row["created_at"],
    )

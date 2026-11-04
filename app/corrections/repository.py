"""Persist correction records. Extractions are never modified here."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from app.config import Settings
from app.corrections.models import Correction

_SCHEMA = """
CREATE TABLE IF NOT EXISTS corrections (
    correction_id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL,
    extraction_id TEXT NOT NULL,
    item_id TEXT,
    field TEXT NOT NULL,
    original_value TEXT,
    corrected_value TEXT NOT NULL,
    corrected_by TEXT NOT NULL,
    corrected_at TEXT NOT NULL,
    pattern_key TEXT NOT NULL
);
"""


def _connect(settings: Settings) -> sqlite3.Connection:
    path = Path(settings.data_dir) / "corrections" / "corrections.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_corrections_db(settings: Settings) -> None:
    connection = _connect(settings)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def insert_correction(settings: Settings, correction: Correction) -> Correction:
    connection = _connect(settings)
    try:
        connection.execute(
            """INSERT INTO corrections (correction_id, receipt_id, extraction_id,
                item_id, field, original_value, corrected_value, corrected_by,
                corrected_at, pattern_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (correction.correction_id, correction.receipt_id, correction.extraction_id,
             correction.item_id, correction.field, correction.original_value,
             correction.corrected_value, correction.corrected_by,
             correction.corrected_at, correction.pattern_key),
        )
        connection.commit()
    finally:
        connection.close()
    return correction


def list_corrections(
    settings: Settings,
    extraction_id: str | None = None,
    pattern_key: str | None = None,
) -> list[Correction]:
    connection = _connect(settings)
    try:
        if pattern_key:
            rows = connection.execute(
                "SELECT * FROM corrections WHERE pattern_key = ? ORDER BY corrected_at",
                (pattern_key,),
            ).fetchall()
        elif extraction_id:
            rows = connection.execute(
                "SELECT * FROM corrections WHERE extraction_id = ? ORDER BY corrected_at",
                (extraction_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM corrections ORDER BY corrected_at"
            ).fetchall()
        return [_from_row(row) for row in rows]
    finally:
        connection.close()


def latest_for_pattern(settings: Settings, pattern_key: str) -> Correction | None:
    connection = _connect(settings)
    try:
        row = connection.execute(
            """SELECT * FROM corrections WHERE pattern_key = ?
               ORDER BY corrected_at DESC LIMIT 1""",
            (pattern_key,),
        ).fetchone()
        return _from_row(row) if row else None
    finally:
        connection.close()


def _from_row(row: sqlite3.Row) -> Correction:
    return Correction(
        correction_id=row["correction_id"],
        receipt_id=row["receipt_id"],
        extraction_id=row["extraction_id"],
        item_id=row["item_id"],
        field=row["field"],
        original_value=row["original_value"],
        corrected_value=row["corrected_value"],
        corrected_by=row["corrected_by"],
        corrected_at=row["corrected_at"],
        pattern_key=row["pattern_key"],
    )


def new_correction_id() -> str:
    return str(uuid.uuid4())

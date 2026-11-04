"""Persist unconfirmed extraction candidates apart from original evidence."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.receipt_extraction.models import ExtractionRecord, LineCandidate
from app.receipt_extraction.parser import ParsedReceipt

_SCHEMA = """
CREATE TABLE IF NOT EXISTS receipt_extraction (
    extraction_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL UNIQUE,
    merchant_raw TEXT,
    merchant_normalized_candidate TEXT,
    purchase_date_candidate TEXT,
    purchase_time_candidate TEXT,
    subtotal_candidate TEXT,
    tax_candidate TEXT,
    total_candidate TEXT,
    raw_text TEXT NOT NULL,
    extraction_status TEXT NOT NULL CHECK (
        extraction_status IN ('extracted', 'no_text', 'insufficient_data', 'failed')
    ),
    failure_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipt_line_candidate (
    line_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    normalized_name_candidate TEXT,
    quantity_candidate TEXT,
    unit_price_candidate TEXT,
    line_total_candidate TEXT,
    line_order INTEGER NOT NULL CHECK (line_order > 0),
    FOREIGN KEY (extraction_id) REFERENCES receipt_extraction(extraction_id) ON DELETE CASCADE
);
"""

_MAX_RAW_CHARS = 100_000


def init_extraction_db(settings: Settings) -> None:
    settings.extraction_db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(settings)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def replace_extraction(settings: Settings, evidence_id: str, parsed: ParsedReceipt, failure_reason: str | None = None) -> ExtractionRecord:
    """Keep one current unconfirmed extraction per evidence id."""
    extraction_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    raw_text = parsed.raw_text[:_MAX_RAW_CHARS]
    lines = tuple(
        LineCandidate(
            line_id=str(uuid.uuid4()),
            extraction_id=extraction_id,
            raw_text=line.raw_text[:2000],
            normalized_name_candidate=line.normalized_name_candidate,
            quantity_candidate=line.quantity_candidate,
            unit_price_candidate=line.unit_price_candidate,
            line_total_candidate=line.line_total_candidate,
            line_order=index,
        )
        for index, line in enumerate(parsed.lines, start=1)
    )
    record = ExtractionRecord(
        extraction_id=extraction_id,
        evidence_id=evidence_id,
        merchant_raw=parsed.merchant_raw,
        merchant_normalized_candidate=parsed.merchant_normalized_candidate,
        purchase_date_candidate=parsed.purchase_date_candidate,
        purchase_time_candidate=parsed.purchase_time_candidate,
        subtotal_candidate=parsed.subtotal_candidate,
        tax_candidate=parsed.tax_candidate,
        total_candidate=parsed.total_candidate,
        raw_text=raw_text,
        extraction_status=parsed.extraction_status,
        failure_reason=failure_reason,
        created_at=created_at,
        lines=lines,
    )
    connection = _connect(settings)
    try:
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                DELETE FROM receipt_line_candidate
                WHERE extraction_id IN (
                    SELECT extraction_id FROM receipt_extraction WHERE evidence_id = ?
                )
                """,
                (evidence_id,),
            )
            connection.execute("DELETE FROM receipt_extraction WHERE evidence_id = ?", (evidence_id,))
            connection.execute(
                """
                INSERT INTO receipt_extraction (
                    extraction_id, evidence_id, merchant_raw, merchant_normalized_candidate,
                    purchase_date_candidate, purchase_time_candidate, subtotal_candidate,
                    tax_candidate, total_candidate, raw_text, extraction_status,
                    failure_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.extraction_id,
                    record.evidence_id,
                    record.merchant_raw,
                    record.merchant_normalized_candidate,
                    record.purchase_date_candidate,
                    record.purchase_time_candidate,
                    record.subtotal_candidate,
                    record.tax_candidate,
                    record.total_candidate,
                    record.raw_text,
                    record.extraction_status,
                    record.failure_reason,
                    record.created_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO receipt_line_candidate (
                    line_id, extraction_id, raw_text, normalized_name_candidate,
                    quantity_candidate, unit_price_candidate, line_total_candidate, line_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        line.line_id,
                        line.extraction_id,
                        line.raw_text,
                        line.normalized_name_candidate,
                        line.quantity_candidate,
                        line.unit_price_candidate,
                        line.line_total_candidate,
                        line.line_order,
                    )
                    for line in record.lines
                ],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()
    return record


def get_extraction(settings: Settings, evidence_id: str) -> ExtractionRecord | None:
    return _load_extraction(settings, "evidence_id = ?", (evidence_id,))


def get_extraction_by_id(settings: Settings, extraction_id: str) -> ExtractionRecord | None:
    return _load_extraction(settings, "extraction_id = ?", (extraction_id,))


def _load_extraction(settings: Settings, where_sql: str, params: tuple[str, ...]) -> ExtractionRecord | None:
    connection = _connect(settings)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            f"""
            SELECT extraction_id, evidence_id, merchant_raw, merchant_normalized_candidate,
                   purchase_date_candidate, purchase_time_candidate, subtotal_candidate,
                   tax_candidate, total_candidate, raw_text, extraction_status,
                   failure_reason, created_at
            FROM receipt_extraction
            WHERE {where_sql}
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        line_rows = connection.execute(
            """
            SELECT line_id, extraction_id, raw_text, normalized_name_candidate,
                   quantity_candidate, unit_price_candidate, line_total_candidate, line_order
            FROM receipt_line_candidate
            WHERE extraction_id = ?
            ORDER BY line_order
            """,
            (row["extraction_id"],),
        ).fetchall()
    finally:
        connection.close()
    lines = tuple(
        LineCandidate(
            line_id=line["line_id"],
            extraction_id=line["extraction_id"],
            raw_text=line["raw_text"],
            normalized_name_candidate=line["normalized_name_candidate"],
            quantity_candidate=line["quantity_candidate"],
            unit_price_candidate=line["unit_price_candidate"],
            line_total_candidate=line["line_total_candidate"],
            line_order=line["line_order"],
        )
        for line in line_rows
    )
    return ExtractionRecord(
        extraction_id=row["extraction_id"],
        evidence_id=row["evidence_id"],
        merchant_raw=row["merchant_raw"],
        merchant_normalized_candidate=row["merchant_normalized_candidate"],
        purchase_date_candidate=row["purchase_date_candidate"],
        purchase_time_candidate=row["purchase_time_candidate"],
        subtotal_candidate=row["subtotal_candidate"],
        tax_candidate=row["tax_candidate"],
        total_candidate=row["total_candidate"],
        raw_text=row["raw_text"],
        extraction_status=row["extraction_status"],
        failure_reason=row["failure_reason"],
        created_at=row["created_at"],
        lines=lines,
    )


def _connect(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.extraction_db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

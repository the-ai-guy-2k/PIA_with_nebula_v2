"""One current image association per remembered item."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.visual_recall.models import VisualEnrichment

_SCHEMA = """
CREATE TABLE IF NOT EXISTS visual_enrichment (
    enrichment_id TEXT PRIMARY KEY,
    memory_item_id TEXT NOT NULL UNIQUE,
    memory_id TEXT NOT NULL,
    purchase_id TEXT NOT NULL,
    merchant TEXT,
    confirmed_item_name TEXT NOT NULL,
    match_type TEXT NOT NULL CHECK (match_type IN ('exact', 'representative', 'none', 'error')),
    image_reference TEXT,
    source_reference TEXT,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def init_visual_db(settings: Settings) -> None:
    settings.visual_db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(settings)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def get_enrichment_for_item(settings: Settings, memory_item_id: str) -> VisualEnrichment | None:
    connection = _connect(settings)
    try:
        return _get(connection, "memory_item_id = ?", (memory_item_id,))
    finally:
        connection.close()


def get_enrichment(settings: Settings, enrichment_id: str) -> VisualEnrichment | None:
    connection = _connect(settings)
    try:
        return _get(connection, "enrichment_id = ?", (enrichment_id,))
    finally:
        connection.close()


def save_enrichment(settings: Settings, enrichment: VisualEnrichment) -> VisualEnrichment:
    connection = _connect(settings)
    try:
        connection.execute("BEGIN")
        connection.execute(
            """
            INSERT INTO visual_enrichment (
                enrichment_id, memory_item_id, memory_id, purchase_id, merchant,
                confirmed_item_name, match_type, image_reference, source_reference,
                provider, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_item_id) DO UPDATE SET
                match_type = excluded.match_type,
                image_reference = excluded.image_reference,
                source_reference = excluded.source_reference,
                provider = excluded.provider,
                updated_at = excluded.updated_at
            """,
            (
                enrichment.enrichment_id,
                enrichment.memory_item_id,
                enrichment.memory_id,
                enrichment.purchase_id,
                enrichment.merchant,
                enrichment.confirmed_item_name,
                enrichment.match_type,
                enrichment.image_reference,
                enrichment.source_reference,
                enrichment.provider,
                enrichment.created_at,
                enrichment.updated_at,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    stored = get_enrichment_for_item(settings, enrichment.memory_item_id)
    return stored if stored is not None else enrichment


def new_enrichment_id() -> str:
    return str(uuid.uuid4())


def enrichment_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(connection: sqlite3.Connection, where_sql: str, params: tuple[str, ...]) -> VisualEnrichment | None:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        f"""
        SELECT enrichment_id, memory_item_id, memory_id, purchase_id, merchant,
               confirmed_item_name, match_type, image_reference, source_reference,
               provider, created_at, updated_at
        FROM visual_enrichment
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    return VisualEnrichment(
        enrichment_id=row["enrichment_id"],
        memory_item_id=row["memory_item_id"],
        memory_id=row["memory_id"],
        purchase_id=row["purchase_id"],
        merchant=row["merchant"],
        confirmed_item_name=row["confirmed_item_name"],
        match_type=row["match_type"],
        image_reference=row["image_reference"],
        source_reference=row["source_reference"],
        provider=row["provider"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _connect(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.visual_db_path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

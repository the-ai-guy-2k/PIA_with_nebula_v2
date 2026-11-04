"""Store one remembered purchase per confirmed purchase."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.purchase_memory.models import MemoryEntry, MemoryItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS purchase_memory (
    memory_id TEXT PRIMARY KEY,
    purchase_id TEXT NOT NULL UNIQUE,
    evidence_id TEXT NOT NULL,
    merchant TEXT,
    purchase_date TEXT,
    purchase_time TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_memory_item (
    memory_item_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    purchase_item_id TEXT NOT NULL UNIQUE,
    item_name TEXT NOT NULL CHECK (length(item_name) > 0),
    quantity TEXT,
    unit_price TEXT,
    line_total TEXT,
    line_order INTEGER NOT NULL CHECK (line_order > 0),
    food_classification TEXT NOT NULL CHECK (
        food_classification IN ('food', 'non-food', 'unknown')
    ),
    need_want_classification TEXT NOT NULL CHECK (
        need_want_classification IN ('need', 'want', 'unknown')
    ),
    durability_classification TEXT NOT NULL CHECK (
        durability_classification IN ('consumable', 'long-term', 'unknown')
    ),
    FOREIGN KEY (memory_id) REFERENCES purchase_memory(memory_id)
);
"""

_FILTERS = {
    "food": ("food_classification", "food"),
    "non-food": ("food_classification", "non-food"),
    "need": ("need_want_classification", "need"),
    "want": ("need_want_classification", "want"),
    "consumable": ("durability_classification", "consumable"),
    "long-term": ("durability_classification", "long-term"),
}


def init_memory_db(settings: Settings) -> None:
    settings.memory_db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(settings)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def insert_memory(settings: Settings, entry: MemoryEntry) -> MemoryEntry:
    connection = _connect(settings)
    try:
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                INSERT INTO purchase_memory (
                    memory_id, purchase_id, evidence_id, merchant, purchase_date,
                    purchase_time, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.memory_id,
                    entry.purchase_id,
                    entry.evidence_id,
                    entry.merchant,
                    entry.purchase_date,
                    entry.purchase_time,
                    entry.created_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO purchase_memory_item (
                    memory_item_id, memory_id, purchase_item_id, item_name, quantity,
                    unit_price, line_total, line_order, food_classification,
                    need_want_classification, durability_classification
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.memory_item_id,
                        item.memory_id,
                        item.purchase_item_id,
                        item.item_name,
                        item.quantity,
                        item.unit_price,
                        item.line_total,
                        item.line_order,
                        item.food_classification,
                        item.need_want_classification,
                        item.durability_classification,
                    )
                    for item in entry.items
                ],
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            existing = _get_memory(connection, "purchase_id = ?", (entry.purchase_id,))
            if existing is not None:
                return existing
            raise
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()
    return entry


def get_memory(settings: Settings, memory_id: str) -> MemoryEntry | None:
    connection = _connect(settings)
    try:
        return _get_memory(connection, "memory_id = ?", (memory_id,))
    finally:
        connection.close()


def get_memory_for_purchase(settings: Settings, purchase_id: str) -> MemoryEntry | None:
    connection = _connect(settings)
    try:
        return _get_memory(connection, "purchase_id = ?", (purchase_id,))
    finally:
        connection.close()


def list_memories(settings: Settings, memory_filter: str | None) -> list[MemoryEntry]:
    column = None
    value = None
    if memory_filter:
        mapped = _FILTERS.get(memory_filter)
        if mapped is None:
            raise ValueError(memory_filter)
        column, value = mapped
    connection = _connect(settings)
    try:
        connection.row_factory = sqlite3.Row
        if column is None:
            rows = connection.execute(
                """
                SELECT memory_id, purchase_id, evidence_id, merchant, purchase_date,
                       purchase_time, created_at
                FROM purchase_memory
                ORDER BY purchase_date IS NULL, purchase_date DESC, created_at DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                f"""
                SELECT memory_id, purchase_id, evidence_id, merchant, purchase_date,
                       purchase_time, created_at
                FROM purchase_memory
                WHERE memory_id IN (
                    SELECT memory_id FROM purchase_memory_item WHERE {column} = ?
                )
                ORDER BY purchase_date IS NULL, purchase_date DESC, created_at DESC
                """,
                (value,),
            ).fetchall()
        return [_entry_from_row(connection, row) for row in rows]
    finally:
        connection.close()


def update_classifications(
    settings: Settings,
    memory_id: str,
    memory_item_id: str,
    food: str,
    need_want: str,
    durability: str,
) -> bool:
    connection = _connect(settings)
    try:
        connection.execute("BEGIN")
        found = connection.execute(
            """
            SELECT 1 FROM purchase_memory_item
            WHERE memory_id = ? AND memory_item_id = ?
            """,
            (memory_id, memory_item_id),
        ).fetchone()
        if found is None:
            connection.rollback()
            return False
        connection.execute(
            """
            UPDATE purchase_memory_item
            SET food_classification = ?,
                need_want_classification = ?,
                durability_classification = ?
            WHERE memory_id = ? AND memory_item_id = ?
            """,
            (food, need_want, durability, memory_id, memory_item_id),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def new_memory_id() -> str:
    return str(uuid.uuid4())


def new_memory_item_id() -> str:
    return str(uuid.uuid4())


def memory_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_memory(
    connection: sqlite3.Connection, where_sql: str, params: tuple[str, ...]
) -> MemoryEntry | None:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        f"""
        SELECT memory_id, purchase_id, evidence_id, merchant, purchase_date,
               purchase_time, created_at
        FROM purchase_memory
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    return _entry_from_row(connection, row)


def _entry_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> MemoryEntry:
    item_rows = connection.execute(
        """
        SELECT memory_item_id, memory_id, purchase_item_id, item_name, quantity,
               unit_price, line_total, line_order, food_classification,
               need_want_classification, durability_classification
        FROM purchase_memory_item
        WHERE memory_id = ?
        ORDER BY line_order
        """,
        (row["memory_id"],),
    ).fetchall()
    items = tuple(
        MemoryItem(
            memory_item_id=item["memory_item_id"],
            memory_id=item["memory_id"],
            purchase_item_id=item["purchase_item_id"],
            item_name=item["item_name"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            line_total=item["line_total"],
            line_order=item["line_order"],
            food_classification=item["food_classification"],
            need_want_classification=item["need_want_classification"],
            durability_classification=item["durability_classification"],
        )
        for item in item_rows
    )
    return MemoryEntry(
        memory_id=row["memory_id"],
        purchase_id=row["purchase_id"],
        evidence_id=row["evidence_id"],
        merchant=row["merchant"],
        purchase_date=row["purchase_date"],
        purchase_time=row["purchase_time"],
        created_at=row["created_at"],
        items=items,
    )


def _connect(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.memory_db_path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

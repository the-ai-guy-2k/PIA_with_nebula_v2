"""Persist pantry items and their status history. Nothing is deleted."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.pantry.models import PantryHistory, PantryItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pantry_item (
    pantry_item_id TEXT PRIMARY KEY,
    purchase_id TEXT,
    purchase_item_id TEXT,
    item_name TEXT NOT NULL CHECK (length(item_name) > 0),
    quantity TEXT,
    unit TEXT,
    qty_on_hand REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('in_stock', 'used', 'gone')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pantry_history (
    history_id TEXT PRIMARY KEY,
    pantry_item_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    qty_change REAL NOT NULL DEFAULT 0,
    changed_at TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (pantry_item_id) REFERENCES pantry_item(pantry_item_id)
);
"""


def _connect(settings: Settings) -> sqlite3.Connection:
    path = Path(settings.data_dir) / "pantry" / "pantry.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_pantry_db(settings: Settings) -> None:
    connection = _connect(settings)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def new_pantry_item_id() -> str:
    return str(uuid.uuid4())


def insert_item(settings: Settings, item: PantryItem) -> PantryItem:
    connection = _connect(settings)
    try:
        connection.execute(
            """INSERT INTO pantry_item (pantry_item_id, purchase_id, purchase_item_id,
                item_name, quantity, unit, qty_on_hand, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.pantry_item_id, item.purchase_id, item.purchase_item_id,
             item.item_name, item.quantity, item.unit, item.qty_on_hand,
             item.status, item.created_at, item.updated_at),
        )
        connection.execute(
            """INSERT INTO pantry_history (history_id, pantry_item_id, from_status,
                to_status, qty_change, changed_at, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), item.pantry_item_id, None, item.status,
             item.qty_on_hand, item.created_at, "created"),
        )
        connection.commit()
    finally:
        connection.close()
    return item


def get_item(settings: Settings, pantry_item_id: str) -> PantryItem | None:
    connection = _connect(settings)
    try:
        row = connection.execute(
            "SELECT * FROM pantry_item WHERE pantry_item_id = ?", (pantry_item_id,)
        ).fetchone()
        return _item_from_row(row) if row else None
    finally:
        connection.close()


def list_items(settings: Settings, status: str | None = None) -> list[PantryItem]:
    connection = _connect(settings)
    try:
        if status:
            rows = connection.execute(
                "SELECT * FROM pantry_item WHERE status = ? ORDER BY item_name, created_at",
                (status,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM pantry_item ORDER BY item_name, created_at"
            ).fetchall()
        return [_item_from_row(row) for row in rows]
    finally:
        connection.close()


def update_item(settings: Settings, item: PantryItem, qty_change: float, note: str | None) -> PantryItem:
    connection = _connect(settings)
    try:
        previous = connection.execute(
            "SELECT status FROM pantry_item WHERE pantry_item_id = ?", (item.pantry_item_id,)
        ).fetchone()
        connection.execute(
            """UPDATE pantry_item SET qty_on_hand = ?, status = ?, updated_at = ?
               WHERE pantry_item_id = ?""",
            (item.qty_on_hand, item.status, item.updated_at, item.pantry_item_id),
        )
        connection.execute(
            """INSERT INTO pantry_history (history_id, pantry_item_id, from_status,
                to_status, qty_change, changed_at, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), item.pantry_item_id,
             previous["status"] if previous else None, item.status,
             qty_change, item.updated_at, note),
        )
        connection.commit()
    finally:
        connection.close()
    return item


def list_history(settings: Settings, pantry_item_id: str) -> list[PantryHistory]:
    connection = _connect(settings)
    try:
        rows = connection.execute(
            """SELECT * FROM pantry_history WHERE pantry_item_id = ?
               ORDER BY changed_at""",
            (pantry_item_id,),
        ).fetchall()
        return [
            PantryHistory(
                pantry_item_id=row["pantry_item_id"],
                from_status=row["from_status"],
                to_status=row["to_status"],
                qty_change=row["qty_change"],
                changed_at=row["changed_at"],
                note=row["note"],
            )
            for row in rows
        ]
    finally:
        connection.close()


def _item_from_row(row: sqlite3.Row) -> PantryItem:
    return PantryItem(
        pantry_item_id=row["pantry_item_id"],
        purchase_id=row["purchase_id"],
        purchase_item_id=row["purchase_item_id"],
        item_name=row["item_name"],
        quantity=row["quantity"],
        unit=row["unit"],
        qty_on_hand=row["qty_on_hand"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )

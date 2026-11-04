"""Store one confirmed purchase per extraction."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.purchase_confirmation.errors import AlreadyConfirmed
from app.purchase_confirmation.models import ConfirmedItem, ConfirmedPurchase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS confirmed_purchase (
    purchase_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL,
    extraction_id TEXT NOT NULL UNIQUE,
    merchant TEXT,
    purchase_date TEXT,
    purchase_time TEXT,
    subtotal TEXT,
    tax TEXT,
    total TEXT,
    confirmed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS confirmed_purchase_item (
    purchase_item_id TEXT PRIMARY KEY,
    purchase_id TEXT NOT NULL,
    source_line_id TEXT NOT NULL,
    item_name TEXT NOT NULL CHECK (length(item_name) > 0),
    quantity TEXT,
    unit_price TEXT,
    line_total TEXT,
    raw_line_text TEXT NOT NULL,
    line_order INTEGER NOT NULL CHECK (line_order > 0),
    FOREIGN KEY (purchase_id) REFERENCES confirmed_purchase(purchase_id)
);
"""


def init_confirmed_db(settings: Settings) -> None:
    settings.confirmed_db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(settings)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def insert_purchase(settings: Settings, purchase: ConfirmedPurchase) -> ConfirmedPurchase:
    connection = _connect(settings)
    try:
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                INSERT INTO confirmed_purchase (
                    purchase_id, evidence_id, extraction_id, merchant, purchase_date,
                    purchase_time, subtotal, tax, total, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purchase.purchase_id,
                    purchase.evidence_id,
                    purchase.extraction_id,
                    purchase.merchant,
                    purchase.purchase_date,
                    purchase.purchase_time,
                    purchase.subtotal,
                    purchase.tax,
                    purchase.total,
                    purchase.confirmed_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO confirmed_purchase_item (
                    purchase_item_id, purchase_id, source_line_id, item_name, quantity,
                    unit_price, line_total, raw_line_text, line_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.purchase_item_id,
                        item.purchase_id,
                        item.source_line_id,
                        item.item_name,
                        item.quantity,
                        item.unit_price,
                        item.line_total,
                        item.raw_line_text,
                        item.line_order,
                    )
                    for item in purchase.items
                ],
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            existing = _get_purchase(connection, "extraction_id = ?", (purchase.extraction_id,))
            if existing is not None:
                raise AlreadyConfirmed(existing.purchase_id) from None
            raise
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()
    return purchase


def get_purchase(settings: Settings, purchase_id: str) -> ConfirmedPurchase | None:
    connection = _connect(settings)
    try:
        return _get_purchase(connection, "purchase_id = ?", (purchase_id,))
    finally:
        connection.close()


def get_purchase_for_extraction(settings: Settings, extraction_id: str) -> ConfirmedPurchase | None:
    connection = _connect(settings)
    try:
        return _get_purchase(connection, "extraction_id = ?", (extraction_id,))
    finally:
        connection.close()


def new_purchase_id() -> str:
    return str(uuid.uuid4())


def new_item_id() -> str:
    return str(uuid.uuid4())


def confirmation_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_purchase(connection: sqlite3.Connection, where_sql: str, params: tuple[str, ...]) -> ConfirmedPurchase | None:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        f"""
        SELECT purchase_id, evidence_id, extraction_id, merchant, purchase_date,
               purchase_time, subtotal, tax, total, confirmed_at
        FROM confirmed_purchase
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    item_rows = connection.execute(
        """
        SELECT purchase_item_id, purchase_id, source_line_id, item_name, quantity,
               unit_price, line_total, raw_line_text, line_order
        FROM confirmed_purchase_item
        WHERE purchase_id = ?
        ORDER BY line_order
        """,
        (row["purchase_id"],),
    ).fetchall()
    items = tuple(
        ConfirmedItem(
            purchase_item_id=item["purchase_item_id"],
            purchase_id=item["purchase_id"],
            source_line_id=item["source_line_id"],
            item_name=item["item_name"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            line_total=item["line_total"],
            raw_line_text=item["raw_line_text"],
            line_order=item["line_order"],
        )
        for item in item_rows
    )
    return ConfirmedPurchase(
        purchase_id=row["purchase_id"],
        evidence_id=row["evidence_id"],
        extraction_id=row["extraction_id"],
        merchant=row["merchant"],
        purchase_date=row["purchase_date"],
        purchase_time=row["purchase_time"],
        subtotal=row["subtotal"],
        tax=row["tax"],
        total=row["total"],
        confirmed_at=row["confirmed_at"],
        items=items,
    )


def _connect(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.confirmed_db_path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

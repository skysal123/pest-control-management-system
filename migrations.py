"""Lightweight schema migrations for SQLite.

SQLite's ``create_all()`` only creates missing *tables*; it never adds columns
to an existing one. This module adds the scheduling columns idempotently so an
existing installation upgrades in place on the next start, without losing data.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

log = logging.getLogger(__name__)

# (table, column, column definition) - applied only when missing.
COLUMNS = [
    ("services", "estimated_minutes", "INTEGER DEFAULT 90"),
    ("users", "work_start", "VARCHAR(5) DEFAULT '09:00'"),
    ("users", "work_end", "VARCHAR(5) DEFAULT '20:00'"),
    ("users", "work_days", "VARCHAR(30) DEFAULT '0,1,2,3,4,5,6'"),
    ("leads", "service_category", "VARCHAR(60)"),
]

# (table, column, column definition) - backfilled for existing rows.
BACKFILL = [
    ("services", "estimated_minutes", "90"),
    ("users", "work_start", "'09:00'"),
    ("users", "work_end", "'20:00'"),
    ("users", "work_days", "'0,1,2,3,4,5,6'"),
]


def _existing_columns(db, table):
    inspector = inspect(db.engine)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def run_migrations(db) -> list[str]:
    """Add any missing scheduling columns. Returns the list of changes made."""
    changes: list[str] = []
    for table, column, definition in COLUMNS:
        try:
            cols = _existing_columns(db, table)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not inspect %s: %s", table, exc)
            continue
        if not cols:
            continue  # table does not exist yet, create_all will handle it
        if column in cols:
            continue
        try:
            db.session.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            )
            changes.append(f"{table}.{column}")
        except Exception as exc:  # noqa: BLE001
            log.warning("could not add %s.%s: %s", table, column, exc)
            db.session.rollback()

    if not changes:
        return changes

    # Backfill defaults for rows created before the column existed.
    for table, column, value in BACKFILL:
        try:
            db.session.execute(
                text(
                    f"UPDATE {table} SET {column} = {value} "
                    f"WHERE {column} IS NULL"
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("could not backfill %s.%s: %s", table, column, exc)
            db.session.rollback()

    db.session.commit()
    return changes

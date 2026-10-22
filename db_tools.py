"""Database safety helpers: automatic backups, stats, and restore.

The live SQLite file is the only copy of every lead, booking and customer, so
this module keeps timestamped backups in ``instance/backups/`` and exposes the
information needed to restore one.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime

# Only files created by the automatic backup are pruned - manual backups
# (onestep_preclear_*.db, onestep_manual_*.db, ...) are never touched.
AUTO_PREFIX = "onestep_autobackup_"


def database_path(app) -> str | None:
    """Absolute filesystem path of the SQLite file, or None for other engines."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite:///"):
        return None
    path = uri[len("sqlite:///"):]
    if not path or path == ":memory:":
        return None
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]  # "/C:/db.sqlite" -> "C:/db.sqlite"
    return os.path.abspath(path)


def backup_dir(app) -> str:
    """Folder holding the timestamped backups."""
    path = database_path(app)
    base = os.path.dirname(path) if path else app.root_path
    folder = os.path.join(base, "backups")
    os.makedirs(folder, exist_ok=True)
    return folder


def backup_database(app, label: str = "manual", keep: int = 15) -> str | None:
    """Copy the live database into ``instance/backups/`` and return the new path.

    Uses SQLite's own backup API so the copy is consistent even when the app is
    writing at the same time. Falls back to a plain file copy if that fails.
    """
    path = database_path(app)
    if not path or not os.path.exists(path):
        return None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = AUTO_PREFIX if label == "autobackup" else f"onestep_{label}_"
    dest = os.path.join(backup_dir(app), f"{prefix}{stamp}.db")

    try:
        src = sqlite3.connect(path)
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
            src.close()
    except sqlite3.Error:
        shutil.copy2(path, dest)

    prune_backups(app, keep=keep)
    return dest


def prune_backups(app, keep: int = 15) -> list[str]:
    """Keep the newest `keep` automatic backups; manual ones are never removed."""
    folder = backup_dir(app)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    auto = [n for n in names if n.startswith(AUTO_PREFIX) and n.endswith(".db")]
    auto.sort(key=lambda n: os.path.getmtime(os.path.join(folder, n)), reverse=True)
    removed = []
    for name in auto[keep:]:
        try:
            os.remove(os.path.join(folder, name))
            removed.append(name)
        except OSError:
            pass
    return removed


def list_backups(app) -> list[dict]:
    """Newest-first list of available backups."""
    folder = backup_dir(app)
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        if not name.endswith(".db"):
            continue
        full = os.path.join(folder, name)
        out.append({
            "name": name,
            "path": full,
            "size_kb": round(os.path.getsize(full) / 1024, 1),
            "modified": datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M:%S"),
        })
    out.sort(key=lambda d: d["modified"], reverse=True)
    return out


def database_stats(app) -> dict:
    """Row count per table, for the startup banner."""
    path = database_path(app)
    stats: dict = {}
    if not path or not os.path.exists(path):
        return stats
    con = sqlite3.connect(path)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        for (table,) in cur.fetchall():
            if table.startswith("sqlite_"):
                continue
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cur.fetchone()[0]
            except sqlite3.Error:
                stats[table] = "?"
    finally:
        con.close()
    return stats


def restore_database(app, backup_file: str) -> str:
    """Replace the live database with a backup file. Returns the live path."""
    path = database_path(app)
    if not path:
        raise RuntimeError("restore is only supported for SQLite databases")
    if not os.path.exists(backup_file):
        raise FileNotFoundError(backup_file)
    # Keep a copy of the current state so a restore is itself reversible.
    backup_database(app, label="prerestore")
    shutil.copy2(backup_file, path)
    return path

"""
db.py — shared SQLite connection helper.

Every process (scheduler, future ingestor, future orchestrator) gets its
connection through here so PRAGMAs and row_factory are consistent.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("ghost.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn
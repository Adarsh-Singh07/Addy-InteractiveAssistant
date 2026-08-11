"""
SQLite database configuration for Addy local state.
Stores collected outreach leads and session memories.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

DB_DIR = "data"
DB_FILE = os.path.join(DB_DIR, "addy.db")


def init_db() -> None:
    """Initialize the database schema."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                requirements TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS session_memory (
                session_id TEXT PRIMARY KEY,
                memory TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_lead(name: str, email: str, requirements: str) -> None:
    """Insert a new recruiter/visitor lead into the database."""
    conn = sqlite3.connect(DB_FILE)
    try:
        cursor = conn.cursor()
        created_at = datetime.utcnow().isoformat() + "Z"
        cursor.execute(
            "INSERT INTO leads (name, email, requirements, created_at) VALUES (?, ?, ?, ?)",
            (name, email, requirements, created_at),
        )
        conn.commit()
    finally:
        conn.close()

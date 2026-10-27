"""
SQLite Database interface for storing shortened URLs and click telemetry.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Tuple


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_code TEXT NOT NULL UNIQUE,
    target_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    click_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_urls_short_code ON urls(short_code);

CREATE TABLE IF NOT EXISTS clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_id INTEGER NOT NULL,
    clicked_at TEXT NOT NULL,
    user_agent TEXT,
    referer TEXT,
    ip_address TEXT,
    FOREIGN KEY(url_id) REFERENCES urls(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_clicks_url_id ON clicks(url_id);
"""


class Database:
    """Manages SQLite connections, schema initialization, and transactional queries."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._is_memory = (db_path == ":memory:")
        # For :memory:, keep a persistent shared connection so table schema is preserved across calls
        self._shared_conn: Optional[sqlite3.Connection] = None
        if self._is_memory:
            self._shared_conn = sqlite3.connect(
                ":memory:",
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            self._shared_conn.row_factory = sqlite3.Row
        self.init_db()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._is_memory and self._shared_conn is not None:
            yield self._shared_conn
        else:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for high concurrency
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            try:
                yield conn
            finally:
                conn.close()

    def init_db(self) -> None:
        """Initializes database schema and ensures required indexes exist."""
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def insert_url(
        self,
        short_code: str,
        target_url: str,
        created_at: str,
        expires_at: Optional[str] = None
    ) -> bool:
        """
        Inserts a new short URL mapping.
        Returns True on success, or False if short_code already exists (conflict).
        """
        sql = """
        INSERT INTO urls (short_code, target_url, created_at, expires_at, click_count)
        VALUES (?, ?, ?, ?, 0)
        """
        with self.get_connection() as conn:
            try:
                conn.execute(sql, (short_code, target_url, created_at, expires_at))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_url(self, short_code: str) -> Optional[Dict[str, Any]]:
        """Retrieves URL record by short code."""
        sql = "SELECT id, short_code, target_url, created_at, expires_at, click_count FROM urls WHERE short_code = ?"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (short_code,))
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    def record_click(
        self,
        url_id: int,
        clicked_at: str,
        user_agent: Optional[str] = None,
        referer: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> None:
        """Atomically increments the URL's click counter and records click telemetry."""
        with self.get_connection() as conn:
            # Atomic counter increment
            conn.execute("UPDATE urls SET click_count = click_count + 1 WHERE id = ?", (url_id,))
            # Append detailed event
            conn.execute(
                """
                INSERT INTO clicks (url_id, clicked_at, user_agent, referer, ip_address)
                VALUES (?, ?, ?, ?, ?)
                """,
                (url_id, clicked_at, user_agent, referer, ip_address)
            )
            conn.commit()

    def get_analytics(self, short_code: str, limit: int = 50) -> Optional[Dict[str, Any]]:
        """Retrieves click statistics and recent telemetry logs for a given short code."""
        url_record = self.get_url(short_code)
        if url_record is None:
            return None

        sql = """
        SELECT clicked_at, user_agent, referer
        FROM clicks
        WHERE url_id = ?
        ORDER BY id DESC
        LIMIT ?
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (url_record["id"], limit))
            rows = cursor.fetchall()
            recent_clicks = [
                {
                    "clicked_at": r["clicked_at"],
                    "user_agent": r["user_agent"],
                    "referer": r["referer"]
                }
                for r in rows
            ]

        # Check expiry status against UTC now
        is_expired = False
        if url_record.get("expires_at"):
            try:
                exp_dt = datetime.fromisoformat(url_record["expires_at"])
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                is_expired = datetime.now(timezone.utc) >= exp_dt
            except ValueError:
                pass

        return {
            "short_code": url_record["short_code"],
            "target_url": url_record["target_url"],
            "total_clicks": url_record["click_count"],
            "created_at": url_record["created_at"],
            "expires_at": url_record["expires_at"],
            "is_expired": is_expired,
            "recent_clicks": recent_clicks,
        }

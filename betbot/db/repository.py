"""Database access layer for Betbot."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from betbot.config import settings
from betbot.logging_setup import get_logger

log = get_logger(__name__)


def get_db_path() -> Path:
    return Path(settings.DB_PATH)


SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(
        get_db_path(),
        timeout=30.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create database file and apply schema if needed."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.executescript(schema_sql)
        _migrate(conn)
    _seed_defaults()


_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("home_score_regular", "ALTER TABLE matches ADD COLUMN home_score_regular INTEGER"),
    ("away_score_regular", "ALTER TABLE matches ADD COLUMN away_score_regular INTEGER"),
    ("home_score_et", "ALTER TABLE matches ADD COLUMN home_score_et INTEGER"),
    ("away_score_et", "ALTER TABLE matches ADD COLUMN away_score_et INTEGER"),
    ("home_score_pen", "ALTER TABLE matches ADD COLUMN home_score_pen INTEGER"),
    ("away_score_pen", "ALTER TABLE matches ADD COLUMN away_score_pen INTEGER"),
    ("match_duration", "ALTER TABLE matches ADD COLUMN match_duration TEXT"),
    ("match_winner", "ALTER TABLE matches ADD COLUMN match_winner TEXT"),
)


def _migrate(conn) -> None:
    """Add columns that may be missing from an older schema.

    SQLite has no ADD COLUMN IF NOT EXISTS, so we inspect pragma_table_info
    and apply only the missing ALTERs. Idempotent and safe on every init.
    """
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(matches)").fetchall()
    }
    for col, ddl in _MIGRATIONS:
        if col in existing:
            continue
        try:
            conn.execute(ddl)
            log.info("migration: added matches.%s", col)
        except Exception as exc:
            log.warning("migration failed for %s: %s", col, exc)


def _seed_defaults() -> None:
    """Seed initial bankroll and settings if first run."""
    with get_conn() as conn:
        cur = conn.execute("SELECT COUNT(*) AS c FROM bankroll_log")
        if cur.fetchone()["c"] == 0:
            conn.execute(
                "INSERT INTO bankroll_log (balance, event, notes) VALUES (?, ?, ?)",
                (settings.BANKROLL_START, "init", "Initial bankroll"),
            )
        cur = conn.execute("SELECT COUNT(*) AS c FROM settings WHERE key='bankroll_current'")
        if cur.fetchone()["c"] == 0:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('bankroll_current', ?)",
                (str(settings.BANKROLL_START),),
            )


def query(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall()


def query_one(sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params: tuple[Any, ...] = ()) -> int:
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid or cur.rowcount

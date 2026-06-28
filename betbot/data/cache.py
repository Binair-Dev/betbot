"""API response cache (SQLite-backed) to respect rate-limits on free tiers."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from betbot.config import settings
from betbot.logging_setup import get_logger

log = get_logger(__name__)


def _raw_connect() -> sqlite3.Connection:
    """Open a raw connection without timestamp detection (for ISO strings)."""
    conn = sqlite3.connect(str(settings.DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def cache_get(key: str) -> Any | None:
    conn = _raw_connect()
    try:
        cur = conn.execute(
            "SELECT response_json, expires_at FROM api_cache WHERE cache_key = ?",
            (key,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return None
    expires_at = row["expires_at"]
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except (ValueError, TypeError):
            expires_at = None
    if expires_at and expires_at < datetime.utcnow():
        return None
    try:
        return json.loads(row["response_json"])
    except (TypeError, ValueError):
        return None


def cache_set(key: str, endpoint: str, data: Any, ttl_seconds: int = 3600) -> None:
    payload = json.dumps(data, default=str)
    expires_at = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
    conn = _raw_connect()
    try:
        conn.execute(
            """
            INSERT INTO api_cache (cache_key, endpoint, response_json, ttl_seconds, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                endpoint=excluded.endpoint,
                response_json=excluded.response_json,
                ttl_seconds=excluded.ttl_seconds,
                expires_at=excluded.expires_at,
                fetched_at=CURRENT_TIMESTAMP
            """,
            (key, endpoint, payload, ttl_seconds, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def cache_clear_expired() -> int:
    log.info("Clearing expired cache entries")
    return execute(
        "DELETE FROM api_cache WHERE expires_at < CURRENT_TIMESTAMP",
    )


def cached(key: str, endpoint: str, ttl: int = 3600):
    """Decorator-style helper: returns cached value if fresh, else calls fn()."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            cached_val = cache_get(key)
            if cached_val is not None:
                log.debug("Cache HIT for %s", key)
                return cached_val
            log.debug("Cache MISS for %s — calling %s", key, fn.__name__)
            result = fn(*args, **kwargs)
            if result is not None:
                cache_set(key, endpoint, result, ttl)
            return result
        return wrapper
    return decorator

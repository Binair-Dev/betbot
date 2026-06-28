"""HTTP client with retry, timeout, and rate-limit handling."""
from __future__ import annotations

import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from betbot.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
BACKOFF_FACTOR = 1.5


def build_session(retries: int = DEFAULT_RETRIES) -> requests.Session:
    session = requests.Session()
    retry_cfg = Retry(
        total=retries,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_cfg, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_SESSION: requests.Session | None = None


def get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = build_session()
    return _SESSION


def get(url: str, *, headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict | list:
    log.debug("GET %s params=%s", url, params)
    resp = get_session().get(url, headers=headers, params=params, timeout=timeout)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "60"))
        log.warning("Rate limited on %s — sleeping %ss", url, retry_after)
        time.sleep(retry_after)
        resp = get_session().get(url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError as exc:
        log.error("Non-JSON response from %s: %s", url, exc)
        raise

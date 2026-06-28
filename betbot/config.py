"""Configuration management for Betbot."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def _get(key: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.getenv(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val or ""


def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # Paths
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    LOG_DIR: Path = BASE_DIR / "data" / "logs"
    DB_PATH: str = _get("DB_PATH", str(BASE_DIR / "data" / "betbot.db"))

    # Bankroll
    BANKROLL_START: float = _get_float("BANKROLL_START", 5000.0)
    BET_SIZE: float = _get_float("BET_SIZE", 5.0)
    TIMEZONE: str = _get("TIMEZONE", "Europe/Brussels")

    # Thresholds
    CONFIDENCE_THRESHOLD: float = _get_float("CONFIDENCE_THRESHOLD", 0.60)
    VALUE_THRESHOLD: float = _get_float("VALUE_THRESHOLD", 0.03)

    # API keys
    API_FOOTBALL_KEY: str = _get("API_FOOTBALL_KEY", required=False)
    API_FOOTBALL_HOST: str = _get("API_FOOTBALL_HOST", "api-football-v1.p.rapidapi.com")
    ODDS_API_KEY: str = _get("ODDS_API_KEY", required=False)
    OPENWEATHER_API_KEY: str = _get("OPENWEATHER_API_KEY", required=False)

    # Dashboard
    DASHBOARD_USER: str = _get("DASHBOARD_USER", "admin")
    DASHBOARD_PASSWORD: str = _get("DASHBOARD_PASSWORD", "changeme")

    # Logging
    LOG_LEVEL: str = _get("LOG_LEVEL", "INFO")

    # Leagues to track (Top 5 EU + NL/PT/BE + UEFA cups + internationals)
    TARGET_LEAGUES: tuple[int, ...] = field(
        default_factory=lambda: (
            39,   # Premier League
            40,   # Championship
            61,   # Ligue 1
            62,   # Ligue 2
            78,   # Bundesliga
            79,   # Bundesliga 2
            135,  # Serie A
            136,  # Serie B
            140,  # La Liga
            141,  # La Liga 2
            88,   # Eredivisie
            94,   # Liga Portugal
            144,  # Jupiler Pro League
            2,    # Champions League
            3,    # Europa League
            848,  # Conference League
            5,    # UEFA Nations League
            10,   # Friendlies
            1,    # World Cup
            4,    # Euro Championship
        )
    )

    # Feature weights (must sum to 1.0)
    FEATURE_WEIGHTS: dict[str, float] = field(
        default_factory=lambda: {
            "xg_form": 0.20,
            "elo": 0.15,
            "odds_value": 0.20,
            "injuries": 0.12,
            "context": 0.10,
            "weather": 0.03,
            "referee": 0.03,
            "fatigue": 0.05,
            "odds_movement": 0.05,
            "market_bias": 0.04,
            "players": 0.03,
        }
    )

    # Hybrid model weights (weighted + ML)
    WEIGHTED_MODEL_WEIGHT: float = 0.6
    ML_MODEL_WEIGHT: float = 0.4


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

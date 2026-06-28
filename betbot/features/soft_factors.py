"""Feature 13: Soft factors via news sentiment (Google News RSS + TextBlob).

Fetches recent headlines for each team, scores polarity with TextBlob,
converts sentiment differential into a small probability shift.
Falls back to keyword counting if TextBlob unavailable.
Results cached 6h to avoid hammering Google News.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus

from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get_session
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)

_TEXTBLOB_AVAILABLE = False
try:
    from textblob import TextBlob
    _TEXTBLOB_AVAILABLE = True
except ImportError:
    pass


class SoftFactorsFeature(Feature):
    name = "soft_factors"
    weight = 0.01

    NEGATIVE_KEYWORDS = (
        "crisis", "scandal", "sack", "sacked", "fired", "controversy",
        "conflict", "protest", "strike", "salary", "unpaid", "boycott",
        "arrested", "ban", "tension", "riot", "chaos", "lawsuit",
    )
    POSITIVE_KEYWORDS = (
        "victory", "triumph", "comeback", "fit", "boost", "signing",
        "renewal", "extend", "title", "champion", "unbeaten", "record",
        "return", "star", "win",
    )

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_name = match.get("home_team_name", "")
        away_name = match.get("away_team_name", "")
        if not (home_name and away_name):
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no team names"}, missing=True)

        home_texts = _fetch_news(home_name)
        away_texts = _fetch_news(away_name)

        home_sent = _sentiment_score(home_texts)
        away_sent = _sentiment_score(away_texts)

        if home_sent == 0.0 and away_sent == 0.0:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no news or neutral"}, missing=True)

        diff = home_sent - away_sent
        shift = max(-0.04, min(0.04, diff * 0.015))
        delta = (shift / 2, 0.0, -shift / 2)
        delta = normalize_delta(delta)

        return FeatureResult(
            delta=delta,
            confidence=0.20,
            raw={
                "home_sentiment": round(home_sent, 3),
                "away_sentiment": round(away_sent, 3),
                "home_articles": len(home_texts),
                "away_articles": len(away_texts),
                "engine": "textblob" if _TEXTBLOB_AVAILABLE else "keywords",
            },
        )


def _fetch_news(team_name: str) -> list[str]:
    """Fetch Google News RSS for a team. Returns list of text snippets. Cached 6h."""
    cache_key = f"news_v2:{team_name}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    query = f"{team_name} football"
    url = (
        f"https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=en&gl=US&ceid=US:en"
    )
    try:
        resp = get_session().get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Betbot/1.0)"},
            timeout=15,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        texts: list[str] = []
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            desc = item.findtext("description") or ""
            combined = f"{title} {desc}".strip()
            if combined:
                texts.append(combined)
            if len(texts) >= 10:
                break
        cache_set(cache_key, "news", texts, ttl_seconds=6 * 3600)
        return texts
    except Exception as exc:
        log.debug("News fetch failed for %s: %s", team_name, exc)
        cache_set(cache_key, "news", [], ttl_seconds=3600)
        return []


def _sentiment_score(texts: list[str]) -> float:
    """Return aggregate sentiment in [-1, +1].

    Hybrid: TextBlob polarity (catches emotional language) + keyword adjustment
    (catches football-specific terms TextBlob's lexicon misses: sacked, crisis, conflict).
    """
    if not texts:
        return 0.0

    scores: list[float] = []
    for t in texts:
        tb_pol = TextBlob(t).sentiment.polarity if _TEXTBLOB_AVAILABLE else 0.0

        t_l = t.lower()
        if any(kw in t_l for kw in SoftFactorsFeature.NEGATIVE_KEYWORDS):
            kw_adj = -0.3
        elif any(kw in t_l for kw in SoftFactorsFeature.POSITIVE_KEYWORDS):
            kw_adj = 0.3
        else:
            kw_adj = 0.0

        scores.append(max(-1.0, min(1.0, tb_pol + kw_adj)))

    return max(-1.0, min(1.0, sum(scores) / len(scores)))

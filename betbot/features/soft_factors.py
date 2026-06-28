"""Feature 13: Soft factors via lightweight news scraping + sentiment.

Scrape Google News RSS for team names. Compute a polarity score.
Negative polarity (crisis, conflict, injuries in headlines) shifts prob
slightly against the team.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from betbot.data.cache import cache_get, cache_set
from betbot.data.http_client import get_session
from betbot.features.base import Feature, FeatureResult, normalize_delta
from betbot.logging_setup import get_logger

log = get_logger(__name__)


class SoftFactorsFeature(Feature):
    name = "soft_factors"
    weight = 0.0  # weak signal; we mostly treat it as info, not scoring input

    NEGATIVE_KEYWORDS = (
        "crisis", "scandal", "injury", "sack", "sacked", "fired", "controversy",
        "conflict", "protest", "strike", "salary", "unpaid", "boycott",
        "arrested", "ban", "suspended", "doubt", "miss", "out", "absent",
        "rumor", "transfer", "leaving", "exit", "tension",
    )

    POSITIVE_KEYWORDS = (
        "win", "victory", "triumph", "return", "comeback", "fit",
        "boost", "star", "signing", "arrival", "renewal", "extend",
        "title", "champion", "unbeaten", "record",
    )

    def compute(self, match: dict[str, Any]) -> FeatureResult:
        home_name = match.get("home_team_name", "")
        away_name = match.get("away_team_name", "")
        if not (home_name and away_name):
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no team names"}, missing=True)

        home_news = _fetch_news(home_name)
        away_news = _fetch_news(away_name)

        home_sent = _sentiment_score(home_news)
        away_sent = _sentiment_score(away_news)

        if home_sent == 0 and away_sent == 0:
            return FeatureResult(delta=(0.0, 0.0, 0.0), confidence=0.0,
                                 raw={"reason": "no news"}, missing=True)

        diff = home_sent - away_sent
        # 1.0 polarity diff ≈ 1pp shift
        shift = max(-0.04, min(0.04, diff * 0.01))
        delta = (shift / 2, 0.0, -shift / 2)
        delta = normalize_delta(delta)

        return FeatureResult(
            delta=delta,
            confidence=0.25,
            raw={
                "home_sentiment": round(home_sent, 2),
                "away_sentiment": round(away_sent, 2),
                "home_headlines_count": len(home_news),
                "away_headlines_count": len(away_news),
            },
        )


def _fetch_news(team_name: str) -> list[str]:
    """Fetch Google News RSS headlines for a team. Cached 6h."""
    cache_key = f"news:{team_name}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(team_name)}&hl=en"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = get_session().get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.find_all("item")
        headlines = []
        for it in items[:10]:
            title = it.find("title")
            if title and title.text:
                clean = re.sub(r"<[^>]+>", "", title.text).strip()
                if clean:
                    headlines.append(clean)
        cache_set(cache_key, "news", headlines, ttl_seconds=6 * 3600)
        return headlines
    except Exception as exc:
        log.warning("News fetch failed for %s: %s", team_name, exc)
        return []


def _sentiment_score(headlines: list[str]) -> float:
    """Return sentiment in [-1, +1]. Crude keyword-based."""
    if not headlines:
        return 0.0
    score = 0
    for h in headlines:
        h_l = h.lower()
        for kw in SoftFactorsFeature.NEGATIVE_KEYWORDS:
            if kw in h_l:
                score -= 1
                break
        else:
            for kw in SoftFactorsFeature.POSITIVE_KEYWORDS:
                if kw in h_l:
                    score += 1
                    break
    return max(-1.0, min(1.0, score / max(1, len(headlines))))

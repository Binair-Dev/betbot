"""ML-based prediction filter (XGBoost).

Trained on historical matches (features → outcome). Used as a 2nd filter
on top of the weighted scoring system. The hybrid confidence is:
    final_confidence = w_weighted × weighted_score + w_ml × ml_score
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

from betbot.config import settings
from betbot.db.repository import query, execute
from betbot.logging_setup import get_logger

log = get_logger(__name__)

MODEL_DIR = settings.DATA_DIR / "models"
MODEL_PATH = MODEL_DIR / "ml_model.joblib"
SCALER_PATH = MODEL_DIR / "scaler.joblib"
METADATA_PATH = MODEL_DIR / "ml_metadata.json"


@dataclass
class MLPrediction:
    """ML model output for one match — probability per outcome."""
    match_id: int
    p_home: float
    p_draw: float
    p_away: float
    confidence: float  # max prob - second max prob (sharpness)
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "p_home": round(self.p_home, 4),
            "p_draw": round(self.p_draw, 4),
            "p_away": round(self.p_away, 4),
            "confidence": round(self.confidence, 4),
            "available": self.available,
        }


class MLModel:
    """XGBoost / LogisticRegression wrapper for outcome prediction."""

    FEATURE_COLUMNS: tuple[str, ...] = (
        "home_xg_per_match", "away_xg_per_match",
        "home_xga_per_match", "away_xga_per_match",
        "home_elo", "away_elo", "elo_diff",
        "home_form_score", "away_form_score",
        "home_injuries_penalty", "away_injuries_penalty",
        "home_rest_days", "away_rest_days",
        "home_recent_n", "away_recent_n",
        "odds_home", "odds_draw", "odds_away",
        "implied_home", "implied_draw", "implied_away",
    )

    def __init__(self):
        self.model = None
        self.scaler: StandardScaler | None = None
        self.metadata: dict[str, Any] = {}
        self._load_or_init()

    def _load_or_init(self) -> None:
        if MODEL_PATH.exists() and SCALER_PATH.exists() and METADATA_PATH.exists():
            try:
                import joblib
                self.model = joblib.load(MODEL_PATH)
                self.scaler = joblib.load(SCALER_PATH)
                self.metadata = json.loads(METADATA_PATH.read_text())
                log.info("ML model loaded (trained at %s, accuracy=%.3f)",
                         self.metadata.get("trained_at"), self.metadata.get("accuracy", 0))
                return
            except Exception as exc:
                log.warning("Failed to load ML model: %s — will retrain", exc)
        log.info("No ML model available yet — will use fallback (uniform).")

    def predict(self, features: dict[str, float]) -> MLPrediction:
        """Predict outcome probabilities for a match.

        If model not trained, returns uniform 1/3 with low confidence.
        """
        if self.model is None or self.scaler is None:
            return MLPrediction(
                match_id=features.get("match_id", 0),
                p_home=0.33, p_draw=0.34, p_away=0.33,
                confidence=0.0, available=False,
            )

        try:
            x = self._vectorize(features)
            x_scaled = self.scaler.transform([x])
            probs = self.model.predict_proba(x_scaled)[0]
            sorted_probs = sorted(probs, reverse=True)
            confidence = sorted_probs[0] - sorted_probs[1]
            return MLPrediction(
                match_id=int(features.get("match_id", 0)),
                p_home=float(probs[2]),  # class order: 0=away, 1=draw, 2=home
                p_draw=float(probs[1]),
                p_away=float(probs[0]),
                confidence=float(confidence),
                available=True,
            )
        except Exception as exc:
            log.warning("ML prediction failed: %s", exc)
            return MLPrediction(
                match_id=features.get("match_id", 0),
                p_home=0.33, p_draw=0.34, p_away=0.33,
                confidence=0.0, available=False,
            )

    def train(self, df: pd.DataFrame, target_col: str = "outcome") -> dict[str, float]:
        """Train on a DataFrame of historical matches.

        Returns training metrics: accuracy, log loss, n_train.
        """
        from xgboost import XGBClassifier

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        missing = [c for c in self.FEATURE_COLUMNS if c not in df.columns]
        if missing:
            log.warning("Missing columns for ML training: %s", missing)
            for c in missing:
                df[c] = 0.0

        X = df[list(self.FEATURE_COLUMNS)].fillna(0.0).astype(float).values
        y = df[target_col].astype(int).values

        # Time-series cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        accuracies = []
        log_losses = []
        for train_idx, val_idx in tscv.split(X):
            X_tr, X_val = X[train_idx], X[val_idx]
            y_tr, y_val = y[train_idx], y[val_idx]
            scaler = StandardScaler()
            X_tr_s = scaler.fit_transform(X_tr)
            X_val_s = scaler.transform(X_val)

            try:
                model = XGBClassifier(
                    n_estimators=200, max_depth=4, learning_rate=0.05,
                    use_label_encoder=False, eval_metric="mlogloss",
                    verbosity=0,
                )
                model.fit(X_tr_s, y_tr)
                preds = model.predict(X_val_s)
                proba = model.predict_proba(X_val_s)
                accuracies.append(accuracy_score(y_val, preds))
                log_losses.append(log_loss(y_val, proba, labels=[0, 1, 2]))
            except Exception as exc:
                log.warning("XGBoost training fold failed: %s — fallback to LogReg", exc)
                lr = LogisticRegression(max_iter=1000, multi_class="multinomial")
                lr.fit(X_tr_s, y_tr)
                preds = lr.predict(X_val_s)
                proba = lr.predict_proba(X_val_s)
                accuracies.append(accuracy_score(y_val, preds))
                log_losses.append(log_loss(y_val, proba, labels=[0, 1, 2]))

        # Train final model on all data
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        try:
            self.model = XGBClassifier(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                use_label_encoder=False, eval_metric="mlogloss",
                verbosity=0,
            )
            self.model.fit(X_scaled, y)
        except Exception as exc:
            log.warning("Final XGBoost failed, using LogReg: %s", exc)
            self.model = LogisticRegression(max_iter=2000, multi_class="multinomial")
            self.model.fit(X_scaled, y)

        # Save artifacts
        import joblib
        joblib.dump(self.model, MODEL_PATH)
        joblib.dump(self.scaler, SCALER_PATH)

        avg_acc = float(np.mean(accuracies)) if accuracies else 0.0
        avg_ll = float(np.mean(log_losses)) if log_losses else 0.0
        self.metadata = {
            "trained_at": datetime.utcnow().isoformat(),
            "accuracy": round(avg_acc, 4),
            "log_loss": round(avg_ll, 4),
            "n_train": len(X),
            "features": list(self.FEATURE_COLUMNS),
        }
        METADATA_PATH.write_text(json.dumps(self.metadata, indent=2))
        log.info("ML model trained: accuracy=%.3f, log_loss=%.3f, n=%d",
                 avg_acc, avg_ll, len(X))
        return self.metadata

    def _vectorize(self, features: dict[str, float]) -> list[float]:
        return [float(features.get(col, 0.0)) for col in self.FEATURE_COLUMNS]


def build_training_dataframe(min_matches: int = 200,
                             use_football_data: bool = True) -> pd.DataFrame:
    """Build a training DataFrame.

    Strategy:
    1. Try football-data.co.uk CSVs first (free, no API quota)
    2. Fall back to SQLite (requires API backfill)

    Returns DataFrame with FEATURE_COLUMNS + target.
    """
    if use_football_data:
        try:
            from betbot.data.football_data.loader import build_training_set
            df_fd = build_training_set()
            if not df_fd.empty and len(df_fd) >= min_matches:
                log.info("Using football-data.co.uk training set: %d matches", len(df_fd))
                df = _adapt_football_data_to_schema(df_fd)
                return _finalize_training_df(df)
            log.warning("football-data.co.uk returned %d matches (< %d) — falling back to SQLite",
                        len(df_fd), min_matches)
        except Exception as exc:
            log.warning("football-data.co.uk loader failed: %s — falling back to SQLite", exc)

    return _build_from_sqlite(min_matches)


def _adapt_football_data_to_schema(df_fd: pd.DataFrame) -> pd.DataFrame:
    """Adapt football-data.co.uk normalized DataFrame to our ML training schema."""
    df = df_fd.copy()
    df["match_date"] = pd.to_datetime(df["match_date"])

    # No Elo available from football-data.co.uk — set defaults
    df["home_elo"] = 1500.0
    df["away_elo"] = 1500.0
    df["elo_diff"] = 0.0

    # No xG from football-data.co.uk — use league averages as proxies
    league_avg = {
        "Premier League": (1.45, 1.20), "Championship": (1.35, 1.10),
        "Ligue 1": (1.40, 1.10), "Ligue 2": (1.30, 1.05),
        "Bundesliga": (1.55, 1.20), "Bundesliga 2": (1.40, 1.10),
        "Serie A": (1.50, 1.15), "Serie B": (1.35, 1.10),
        "La Liga": (1.45, 1.10), "La Liga 2": (1.35, 1.05),
        "Eredivisie": (1.55, 1.25), "Liga Portugal": (1.35, 1.10),
        "Jupiler Pro League": (1.40, 1.15),
    }

    def row_xg(row, side):
        avg = league_avg.get(row.get("__league_name"), (1.4, 1.15))
        return avg[0] if side == "for" else avg[1]

    df["home_xg_per_match"] = df.apply(lambda r: row_xg(r, "for"), axis=1)
    df["away_xg_per_match"] = df.apply(lambda r: row_xg(r, "for"), axis=1)
    df["home_xga_per_match"] = df.apply(lambda r: row_xg(r, "against"), axis=1)
    df["away_xga_per_match"] = df.apply(lambda r: row_xg(r, "against"), axis=1)
    df["home_form_score"] = 0.5
    df["away_form_score"] = 0.5
    df["home_injuries_penalty"] = 0.0
    df["away_injuries_penalty"] = 0.0
    df["home_rest_days"] = 7.0
    df["away_rest_days"] = 7.0
    df["home_recent_n"] = 0
    df["away_recent_n"] = 0
    return df


def _build_from_sqlite(min_matches: int = 200) -> pd.DataFrame:
    """Fallback: build training set from the local SQLite database."""
    sql = """
        SELECT m.match_id, m.home_team_id, m.away_team_id, m.league_id, m.season,
               m.match_date, m.home_score, m.away_score,
               t1.elo AS home_elo, t2.elo AS away_elo
        FROM matches m
        LEFT JOIN teams t1 ON t1.team_id = m.home_team_id
        LEFT JOIN teams t2 ON t2.team_id = m.away_team_id
        WHERE m.status = 'FT' AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL
        ORDER BY m.match_date ASC
    """
    rows = query(sql)
    if len(rows) < min_matches:
        log.warning("Only %d finished matches in SQLite (need %d)", len(rows), min_matches)

    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df

    df["match_date"] = pd.to_datetime(df["match_date"])
    df["outcome"] = df.apply(
        lambda r: 2 if r["home_score"] > r["away_score"]
                  else (1 if r["home_score"] == r["away_score"] else 0),
        axis=1,
    )
    df["elo_diff"] = df["home_elo"].fillna(1500) - df["away_elo"].fillna(1500)

    # Add recent-form features from team_recent_form (if populated)
    form_df = pd.DataFrame([dict(r) for r in query("SELECT * FROM team_recent_form")])
    if not form_df.empty:
        df = df.merge(form_df.rename(columns={
            "team_id": "home_team_id",
            "avg_xg_for": "home_xg_per_match",
            "avg_xg_against": "home_xga_per_match",
            "form_score": "home_form_score",
        })[["home_team_id", "season", "home_xg_per_match", "home_xga_per_match", "home_form_score"]],
            on=["home_team_id", "season"], how="left")
        df = df.merge(form_df.rename(columns={
            "team_id": "away_team_id",
            "avg_xg_for": "away_xg_per_match",
            "avg_xg_against": "away_xga_per_match",
            "form_score": "away_form_score",
        })[["away_team_id", "season", "away_xg_per_match", "away_xga_per_match", "away_form_score"]],
            on=["away_team_id", "season"], how="left")

    # Add odds features
    odds_rows = query("""
        SELECT match_id, selection, odds, implied_prob FROM odds_history
        WHERE market = 'h2h'
    """)
    if odds_rows:
        odds_df = pd.DataFrame([dict(r) for r in odds_rows])
        pivot = odds_df.pivot_table(
            index="match_id", columns="selection",
            values=["odds", "implied_prob"], aggfunc="mean",
        )
        pivot.columns = [f"{v}_{s}" for v, s in pivot.columns]
        pivot = pivot.reset_index()
        df = df.merge(pivot, on="match_id", how="left")

    return _finalize_training_df(df)


def _finalize_training_df(df: pd.DataFrame) -> pd.DataFrame:
    """Finalize training DataFrame: ensure all FEATURE_COLUMNS exist with defaults."""
    for col in MLModel.FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
    df["home_xg_per_match"] = df.get("home_xg_per_match", 1.3).fillna(1.3)
    df["away_xg_per_match"] = df.get("away_xg_per_match", 1.1).fillna(1.1)
    df["home_xga_per_match"] = df.get("home_xga_per_match", 1.1).fillna(1.1)
    df["away_xga_per_match"] = df.get("away_xga_per_match", 1.3).fillna(1.3)
    df["home_form_score"] = df.get("home_form_score", 0.5).fillna(0.5)
    df["away_form_score"] = df.get("away_form_score", 0.5).fillna(0.5)
    df["odds_home"] = df.get("odds_home", 2.5).fillna(2.5)
    df["odds_draw"] = df.get("odds_draw", 3.3).fillna(3.3)
    df["odds_away"] = df.get("odds_away", 3.0).fillna(3.0)
    df["implied_home"] = df.get("implied_home", 0.4).fillna(0.4)
    df["implied_draw"] = df.get("implied_draw", 0.3).fillna(0.3)
    df["implied_away"] = df.get("implied_away", 0.3).fillna(0.3)
    return df

# Plan Betbot — Vue d'ensemble

Plan détaillé des phases d'implémentation.

## Phase 1 — Fondations ✅
- Structure projet, Docker, docker-compose
- Schéma SQLite (13 tables)
- Config env-driven
- Logging + cache
- Scheduler APScheduler

## Phase 2 — Collecte de données ✅
- API-Football client (fixtures, stats, blessures, arbitres, classements, H2H)
- The Odds API client (cotes multi-bookmakers)
- OpenWeatherMap client
- Understat scraper (xG/xGA)
- Backfill module (récupération 6 mois)
- HTTP client commun avec retry

## Phase 3 — Extraction des 15 features ✅
Chaque feature produit un delta (home/draw/away) + une confidence (0-1) :

| # | Feature | Module | Poids |
|---|---------|--------|-------|
| 1 | xG/xGA forme | `features/form.py` | 20% |
| 2 | Elo rating | `features/elo.py` | 15% |
| 3 | Avantage domicile | `features/home_advantage.py` | implicite |
| 4 | Blessures | `features/injuries.py` | 12% |
| 5 | Contexte match | `features/context.py` | 10% |
| 6 | Styles H2H | `features/styles.py` | info |
| 7 | Value cotes | `features/odds_features.py` | 20% |
| 8 | Météo | `features/conditions.py` | 3% |
| 9 | Arbitre | `features/referee.py` | 3% |
| 10 | Fatigue | `features/fatigue.py` | 5% |
| 11 | Joueurs | `features/players.py` | 3% |
| 12 | Set pieces | `features/setpieces.py` | info |
| 13 | Soft factors | `features/soft_factors.py` | info |
| 14 | Mouvement cotes | `features/odds_features.py` | 5% |
| 15 | Biais marché | `features/odds_features.py` | 4% |

Orchestrateur : `features/orchestrator.py`

## Phase 4 — Modèles prédictifs ✅
- **Poisson/Dixon-Coles** : `models/poisson.py`
  - λ_home, λ_away depuis ratings attaque/défense
  - Dérivation probabilités : 1/N/2, score exact, OU, BTTS, double chance, DNB
- **Modèle ML (XGBoost)** : `models/ml_model.py`
  - 21 features, time-series cross-validation
  - **Entraîné sur football-data.co.uk (gratuit)** : ~19 000 matchs, 13 ligues, 4 saisons
  - Accuracy ~50% sur 1X2 (3 classes), log_loss ~1.0
  - Calibration probabiliste
- **Fusion hybride** : `models/confidence.py`
  - `0.6 × pondéré + 0.4 × ML`
- **Fallback gracieux** : si ML non entraîné, 100% pondéré + Poisson

## Phase 5 — Backtest ⚠️ (optionnel, requiert backfill)
- `models/backtest.py` : simulation jour-par-jour sur 6 mois
- Métriques : ROI, hit rate, max drawdown, Sharpe
- Découpage par marché / ligue
- Persiste dans `backtest_results`
- **⚠️ NON UTILISÉ en mode free APIs** (backfill consommerait le quota)
- Toujours disponible pour upgrade vers plan payant

## Phase 6 — Moteur de paris ✅
- **Value calc** : `betting/value_calc.py`
- **Decision engine** : `betting/decision.py`
  - **Règle clé** : 1 seul pari par match = marché avec confiance max
- **Simulator** : `betting/simulator.py`
  - Bankroll tracking, pari 5€, stake déduit
- **Results settlement** : `betting/results.py`
  - 23h chaque jour, récup résultats, update bankroll

## Phase 7 — Scheduler ✅
- APScheduler avec timezone Europe/Brussels
- 3 jobs :
  - 00:00 — analyse & paris
  - 06:00 — recalcul Elo
  - 23:00 — règlement

## Phase 8 — Dashboard ✅
- Streamlit + auth (login/password)
- 5 pages : Vue d'ensemble, Prédictions du jour, Historique, Statistiques, Backtest
- Graphiques Plotly (line, bar, scatter)
- Filtres par marché/statut/date

## Phase 9 — Tests & docs ✅
- 37 tests unitaires (pytest)
  - 10 tests Poisson
  - 7 tests betting (value, decision, simulator)
  - 20+ tests features
- README complet
- CLI : `python -m betbot.cli {backfill,backtest,train,run-once,settle}`

## Métriques cibles

Pour passer en production, le backtest 6 mois doit afficher :
- **ROI > 0%** (idéalement > 3%)
- **Hit rate > 50%** sur les 1X2
- **Max drawdown < 15%**
- **N paris > 200** (significativité statistique)

## Roadmap future (hors MVP)

- Phase 10 : Notifications Telegram
- Phase 11 : Support de plusieurs bookmakers simultanément (meilleur prix)
- Phase 12 : Modèles deep learning pour le score exact
- Phase 13 : Live in-play betting
- Phase 14 : Kelly Criterion pour mise variable
- Phase 15 : Web UI avec react / next.js

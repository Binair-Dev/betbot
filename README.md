# Betbot — Value Betting Bot ⚽

Bot automatisé de **value betting** sur le football. Simulation (paper trading) avec bankroll de 5000€ et mise fixe de 5€ par pari.

## 🎯 Principe

Chaque nuit à **00:00 heure belge**, le bot :
1. Récupère les matchs de foot des 24 prochaines heures (ligues majeures + coupes UEFA + internationaux)
2. Collecte **16 features** par match (xG/xGA, Elo, blessures, météo, cotes, etc.)
3. Calcule un **score de confiance** hybride (scoring pondéré + modèle ML XGBoost)
4. Pour chaque match, identifie le **SEUL marché** avec la plus haute confiance
5. Si confiance > 60% **ET** value > 3% → pari simulé de 5€

Le pari n'est placé que si le modèle détecte un **edge positif** vs les cotes du marché (principe du value betting).

## 📊 Architecture

```
┌─────────────────────────────────────────────────────┐
│  Docker Compose                                     │
│  ┌──────────────┐    ┌────────────────────────┐   │
│  │  betbot-bot  │    │  betbot-dashboard      │   │
│  │  Scheduler   │◄──►│  Streamlit UI          │   │
│  │  APScheduler │    │  http://localhost:8501  │   │
│  └──────────────┘    └────────────────────────┘   │
│         │                                            │
│         ▼                                            │
│  ┌──────────────────────────────────────────────┐  │
│  │  SQLite (./data/betbot.db)                   │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Modules

| Module | Rôle |
|--------|------|
| `betbot/data/api_football.py` | Fixtures, stats, blessures, arbitres |
| `betbot/data/odds_api.py` | Cotes multi-bookmakers |
| `betbot/data/weather.py` | Météo stades (OpenWeatherMap) |
| `betbot/data/understat.py` | xG/xGA scraping |
| `betbot/data/backfill.py` | Backfill historique |
| `betbot/features/*` | 15 modules de features (1 par paramètre + combinés) |
| `betbot/features/orchestrator.py` | Agrégation des features |
| `betbot/models/poisson.py` | Modèle Poisson/Dixon-Coles |
| `betbot/models/markets.py` | Dérivation probabilités tous marchés |
| `betbot/models/ml_model.py` | XGBoost / LogisticRegression |
| `betbot/models/confidence.py` | Fusion pondéré + ML |
| `betbot/betting/decision.py` | 1 pari par match = le plus sûr |
| `betbot/betting/value_calc.py` | Calcul de value |
| `betbot/betting/simulator.py` | Placement & bankroll |
| `betbot/betting/results.py` | Règlement des paris |
| `betbot/scheduler/` | Jobs quotidiens |

### Les 16 features

1. **Forme récente + xG/xGA** (Understat) — poids 20%
2. **Rating Elo** (calcul interne) — poids 15%
3. **Avantage domicile** (par ligue) — implicite
4. **Blessures/suspensions** (API-Football) — poids 12%
5. **Contexte match** (enjeu, derby, calendrier) — poids 10%
6. **Styles de jeu / H2H** — informatif
7. **Cotes du marché** (value detection) — poids 20%
8. **Météo + pelouse** — poids 3%
9. **Arbitre** (statistiques) — poids 3%
10. **Fatigue & déplacements** — poids 5%
11. **Données joueurs** (lineups) — poids 3%
12. **Phases arrêtées** — informatif
13. **Soft factors** (NLP news) — informatif
14. **Mouvements de cotes** — poids 5%
15. **Biais favori-outsider** — poids 4%

## 🚀 Démarrage rapide

### Prérequis
- Docker + Docker Compose
- Clés API (voir `.env.example`) — **uniquement pour le bot en production** :
  - **API-Football** via [RapidAPI](https://rapidapi.com/api-sports/api/api-football) — gratuit 100 req/jour
  - **The Odds API** sur [the-odds-api.com](https://the-odds-api.com/) — gratuit 500 req/mois
  - **OpenWeatherMap** — gratuit 1000 req/jour

> 💡 **Le setup initial ne consomme AUCUN crédit API** — on utilise [football-data.co.uk](https://www.football-data.co.uk/) (CSV publics gratuits, 4 saisons, ~19 000 matchs).

### Installation

```bash
# 1. Cloner le repo
cd /mnt/hdde/Dev/Betbot

# 2. Configurer les clés API
cp .env.example .env
nano .env  # remplir API_FOOTBALL_KEY, ODDS_API_KEY, OPENWEATHER_API_KEY

# 3. Lancer les containers
docker compose up -d

# 4. Setup initial (gratuit, ~1 minute) — entraîne le modèle ML
docker compose exec bot python -m betbot.cli setup
# → 18 925 matchs récupérés, modèle XGBoost entraîné (accuracy ~50%)

# 5. Vérifier
docker compose logs -f bot
```

### URLs

- **Dashboard** : http://localhost:8501 (login: `admin` / `changeme`)

### CLI

```bash
# Setup one-shot (recommandé au premier lancement, 0 quota API)
docker compose exec bot python -m betbot.cli setup

# Entraîner le modèle ML sur football-data.co.uk (gratuit)
docker compose exec bot python -m betbot.cli train

# Backfill via API (⚠️ consomme le quota API gratuit, optionnel)
docker compose exec bot python -m betbot.cli backfill --days 180

# Lancer un backtest (⚠️ nécessite des données backfillées)
docker compose exec bot python -m betbot.cli backtest --days 180

# Exécuter le pipeline quotidien manuellement (debug)
docker compose exec bot python -m betbot.cli run-once

# Régler les paris en attente
docker compose exec bot python -m betbot.cli settle
```

## ⚠️ Stratégie sans backtest (recommandée pour free APIs)

Avec les **APIs gratuites**, on a 100 req/jour (API-Football) et 500 req/mois (Odds API). Backfiller 6 mois = ~10 000 appels = quota cramé en une heure.

**Solution adoptée :**
- ✅ **Données historiques d'entraînement** : [football-data.co.uk](https://www.football-data.co.uk/) — CSV gratuits, pas de quota, 4 saisons de 13 ligues majeures (~19 000 matchs)
- ✅ **Pas de backtest requis** — le modèle ML est entraîné sur les CSVs et fonctionne immédiatement
- ✅ **Fallback gracieux** : si le ML n'est pas entraîné, le scoring pondéré + Poisson font le boulot seuls
- ⚠️ **Backtest toujours disponible** si tu passes à un plan API payant plus tard

## 📈 Pipeline quotidien (auto)

```
00:00 Europe/Brussels  → run_daily_analysis
                          ├─ Fetch fixtures (aujourd'hui + demain)
                          ├─ Fetch odds (The Odds API)
                          ├─ For each match:
                          │   ├─ Compute 15 features
                          │   ├─ Run Poisson model
                          │   ├─ Run ML model
                          │   ├─ Hybrid confidence
                          │   ├─ Decision (best market per match)
                          │   └─ Place bet if conf>60% AND value>3%
                          └─ Log results

06:00                  → recompute_elo (rolling)

23:00                  → settle_pending_bets
                          ├─ Fetch match results from API-Football
                          ├─ Update bets won/lost
                          └─ Update bankroll
```

## 🧪 Tests

```bash
docker compose exec bot python -m pytest tests/ -v
```

37 tests couvrent : modèle Poisson, value calc, decision engine, simulator, features.

## 🔧 Maintenance

### Ajuster les poids des features

Éditer `betbot/config.py` :

```python
FEATURE_WEIGHTS: dict[str, float] = field(
    default_factory=lambda: {
        "xg_form": 0.20,
        "elo": 0.15,
        "odds_value": 0.20,
        ...
    }
)
```

Puis re-backtester :
```bash
docker compose exec bot python -m betbot.cli backtest --days 180
```

### Ajouter une ligue

1. Trouver l'`id` de la ligue dans API-Football
2. Trouver le `sport_key` dans The Odds API
3. Ajouter dans `betbot/config.py` :

```python
TARGET_LEAGUES: tuple[int, ...] = (
    ...,
    307,  # Saudi Pro League par exemple
)
```

4. Mapper la ligue vers The Odds API dans `betbot/data/odds_fetcher.py` :

```python
LEAGUE_TO_SPORT_KEY: dict[int, str] = {
    ...,
    307: "soccer_saudi_arabia_stars_league",
}
```

### Ajouter un bookmaker referee

Éditer `betbot/features/referee.py` et ajouter dans `_REFEREE_DATABASE`.

### Améliorer le modèle ML

Le modèle actuel utilise XGBoost avec 21 features. Pour améliorer :
1. Backfiller plus de données historiques
2. Ajouter des features (par exemple ELO par ligue)
3. Tester d'autres algos (LightGBM, CatBoost, neural nets)
4. Faire de la validation croisée temporelle plus poussée

## 📁 Structure du projet

```
Betbot/
├── betbot/                  # Package principal
│   ├── config.py            # Configuration (env-driven)
│   ├── main.py              # Entry point
│   ├── logging_setup.py
│   ├── data/                # Collecte (5 modules)
│   ├── features/            # 15 features + orchestrator
│   ├── models/              # Poisson + ML + confidence + backtest
│   ├── betting/             # Value, decision, simulator, results
│   ├── scheduler/           # Jobs APScheduler
│   └── db/                  # Schema + repository
├── dashboard/               # Streamlit UI
│   ├── app.py               # Page principale
│   ├── auth.py              # Login
│   ├── utils.py
│   └── pages/               # 5 pages
├── tests/                   # 37 tests
├── data/                    # Volume monté (DB + logs)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## ⚠️ Disclaimer

Ce bot est un **projet éducatif et de simulation**. Aucun argent réel n'est misé. Les paris sportifs comportent des risques financiers importants. Les performances passées ne préjugent pas des performances futures.

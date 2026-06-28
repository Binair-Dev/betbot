-- ============================================================================
-- Betbot Database Schema
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ----------------------------------------------------------------------------
-- Teams
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    logo_url TEXT,
    elo REAL DEFAULT 1500.0,
    elo_updated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_teams_country ON teams(country);

-- ----------------------------------------------------------------------------
-- Leagues / Competitions
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leagues (
    league_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    type TEXT,                 -- 'league' or 'cup'
    tier INTEGER,              -- 1 = top tier
    is_active INTEGER DEFAULT 1
);

-- ----------------------------------------------------------------------------
-- Matches / Fixtures
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    match_id INTEGER PRIMARY KEY,
    league_id INTEGER,
    season INTEGER,
    match_date TIMESTAMP NOT NULL,
    home_team_id INTEGER NOT NULL,
    away_team_id INTEGER NOT NULL,
    venue TEXT,
    referee TEXT,
    status TEXT DEFAULT 'NS',   -- NS / 1H / HT / 2H / FT / POSTPONED
    home_score INTEGER,
    away_score INTEGER,
    home_ht_score INTEGER,
    away_ht_score INTEGER,
    weather_json TEXT,
    pitch_type TEXT,
    context_flags_json TEXT,    -- derby, manager_change, congested, etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (league_id) REFERENCES leagues(league_id),
    FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
    FOREIGN KEY (away_team_id) REFERENCES teams(team_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league_id);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_team_id);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_team_id);

-- ----------------------------------------------------------------------------
-- Team form / stats (rolling window)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_recent_form (
    team_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    n_matches INTEGER,
    matches_json TEXT,          -- list of last N matches (opponent, h/a, gf, ga, xg, xga, result)
    form_score REAL,            -- 0-1 normalized
    avg_xg_for REAL,
    avg_xg_against REAL,
    avg_goals_for REAL,
    avg_goals_against REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (team_id, season),
    FOREIGN KEY (team_id) REFERENCES teams(team_id)
);

-- ----------------------------------------------------------------------------
-- Injuries / Suspensions
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS injuries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    player_name TEXT,
    player_id INTEGER,
    reason TEXT,                -- injury / suspension / doubt
    importance REAL DEFAULT 0.5, -- 0-1 rating of player importance
    expected_return TEXT,
    fixture_id INTEGER,         -- match_id
    source TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (team_id) REFERENCES teams(team_id),
    FOREIGN KEY (fixture_id) REFERENCES matches(match_id)
);

CREATE INDEX IF NOT EXISTS idx_injuries_team ON injuries(team_id);
CREATE INDEX IF NOT EXISTS idx_injuries_fixture ON injuries(fixture_id);

-- ----------------------------------------------------------------------------
-- Odds history (multi-bookmaker)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS odds_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL,       -- h2h / over_under / btts / correct_score / double_chance
    selection TEXT NOT NULL,    -- home / draw / away / over_2.5 / under_2.5 / etc.
    odds REAL NOT NULL,
    implied_prob REAL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);

CREATE INDEX IF NOT EXISTS idx_odds_match ON odds_history(match_id);
CREATE INDEX IF NOT EXISTS idx_odds_bookmaker ON odds_history(bookmaker);
CREATE INDEX IF NOT EXISTS idx_odds_market ON odds_history(market);
CREATE INDEX IF NOT EXISTS idx_odds_fetched ON odds_history(fetched_at);

-- ----------------------------------------------------------------------------
-- Predictions (per match, per market)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    market TEXT NOT NULL,       -- '1X2', 'over_under', 'btts', 'correct_score', 'double_chance'
    selection TEXT NOT NULL,    -- 'home', 'draw', 'over_2.5', '2-1', etc.
    prob_model REAL NOT NULL,   -- probability from our model
    confidence REAL NOT NULL,   -- 0-1 final confidence score
    best_odds REAL,
    best_bookmaker TEXT,
    market_avg_odds REAL,
    value REAL,                 -- (prob * odds) - 1
    weighted_score REAL,
    ml_score REAL,
    features_json TEXT,         -- all features snapshot
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);

CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id);
CREATE INDEX IF NOT EXISTS idx_predictions_market ON predictions(market);
CREATE INDEX IF NOT EXISTS idx_predictions_confidence ON predictions(confidence);

-- ----------------------------------------------------------------------------
-- Bets (only placed bets)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    prediction_id INTEGER,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    odds REAL NOT NULL,
    bookmaker TEXT,
    stake REAL NOT NULL,
    confidence REAL,
    value REAL,
    status TEXT DEFAULT 'pending',  -- pending / won / lost / void
    payout REAL,
    profit REAL,
    placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settled_at TIMESTAMP,
    notes TEXT,
    FOREIGN KEY (match_id) REFERENCES matches(match_id),
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);

CREATE INDEX IF NOT EXISTS idx_bets_match ON bets(match_id);
CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
CREATE INDEX IF NOT EXISTS idx_bets_placed ON bets(placed_at);

-- ----------------------------------------------------------------------------
-- Bankroll log
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bankroll_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    balance REAL NOT NULL,
    delta REAL,
    event TEXT,                -- 'bet_placed' / 'bet_settled' / 'reset'
    bet_id INTEGER,
    notes TEXT,
    at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bankroll_at ON bankroll_log(at);

-- ----------------------------------------------------------------------------
-- API cache (rate-limit management)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    endpoint TEXT,
    response_json TEXT,
    ttl_seconds INTEGER,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cache_expires ON api_cache(expires_at);

-- ----------------------------------------------------------------------------
-- Settings / config runtime
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- Backtest results
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    period_start DATE,
    period_end DATE,
    total_bets INTEGER,
    won_bets INTEGER,
    lost_bets INTEGER,
    total_stake REAL,
    total_payout REAL,
    profit REAL,
    roi REAL,
    hit_rate REAL,
    max_drawdown REAL,
    config_json TEXT,
    notes TEXT
);

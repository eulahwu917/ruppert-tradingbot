"""
Configuration loader - reads credentials from secrets folder.
Never hardcodes API keys.
"""
import json
import os
from pathlib import Path

# Paths
# _WORKSPACE_ROOT is injected by workspace/config.py shim when loaded via exec().
# Fall back to __file__-based resolution when this file is run directly.
_this_file = Path(__file__).resolve() if '__file__' in dir() and Path(__file__).exists() else None
if '_WORKSPACE' in dir():
    # Injected by workspace shim — use it directly (avoids __file__ being workspace/config.py)
    SECRETS_DIR = str(_WORKSPACE / 'secrets')
elif _this_file is not None:
    SECRETS_DIR = str(_this_file.parent.parent.parent / 'secrets')
else:
    SECRETS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'secrets')
CONFIG_FILE = os.path.join(SECRETS_DIR, 'kalshi_config.json')

# DRY_RUN: derived from mode.json — True = demo (no real orders), False = live
_MODE_FILE = os.path.join(os.path.dirname(__file__), 'mode.json')
try:
    with open(_MODE_FILE, 'r', encoding='utf-8') as _f:
        _mode = json.load(_f).get('mode', 'demo')
except Exception:
    _mode = 'demo'
DRY_RUN = (_mode != 'live')

def load_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    return cfg

def get_private_key_path():
    cfg = load_config()
    return cfg['private_key_path']

def get_api_key_id():
    cfg = load_config()
    return cfg['api_key_id']

def get_environment():
    cfg = load_config()
    return cfg.get('environment', 'demo')

# Daily cap per module — percentage of total capital (scaled dynamically)
WEATHER_DAILY_CAP_PCT = 0.07   # 7% of capital/day
CRYPTO_DAILY_CAP_PCT  = 0.07   # 7% of capital/day
GEO_DAILY_CAP_PCT     = 0.04   # 4% of capital/day
ECON_DAILY_CAP_PCT    = 0.04   # 4% of capital/day
FED_DAILY_CAP_PCT        = 0.03   # 3% of capital/day (fed trades are rare/high-conviction)
CRYPTO_15M_DAILY_CAP_PCT = 0.10   # 10% of capital/day — canary threshold; not enforced
                                   # Strategist to tune after 30 trades

# Per-trade position size cap — percentage of total capital
MAX_POSITION_PCT = 0.01   # 1% of capital per trade (replaces fixed $25 caps)

MAX_ADD_ALLOCATION = 50.0   # Maximum total allocation per add-on position ($)

# Legacy fixed-dollar position caps — used by trader.py legacy fallback (risk.py inlined)
# These are safety backstops; actual sizing is done by strategy.py MAX_POSITION_PCT.
MAX_POSITION_SIZE   = 100.0   # P0-1 fix: was deleted; restored for trader.py legacy path
MAX_DAILY_EXPOSURE  = 700.0   # P0-1 fix: was deleted; restored for trader.py legacy path

# Risk settings - Weather / Economics
MIN_EDGE_THRESHOLD = 0.12      # Min edge (12%) to trigger a trade
MIN_MARKET_LIQUIDITY = 100.00  # Min $ volume in market to trade

# Risk settings - Crypto (separate budget, FULLY AUTO like weather)
CRYPTO_MIN_EDGE_THRESHOLD = 0.12   # 12% min edge (consistent with weather)
CRYPTO_SIGNAL_THRESHOLD   = 3.5    # bull/bear score threshold to declare directional signal

# Auto-trade settings
# Weather + Crypto + Geo = fully autonomous in DEMO (data collection)
# Geo = ON in DEMO for data gathering — LLM pipeline (Haiku screen + Sonnet estimate)
WEATHER_AUTO_TRADE  = True   # Bot executes without asking
CRYPTO_AUTO_TRADE   = True   # Bot executes without asking
GEO_AUTO_TRADE      = True   # DEMO: ON for data collection (LLM edge pipeline, not news_volume)
ECON_AUTO_TRADE       = True    # DEMO: fully autonomous (Phase 5)
ECON_MIN_EDGE         = 0.12   # 12% min edge to trigger a trade
ECON_MIN_VOLUME       = 100    # minimum market volume (contracts) to consider
ECON_FAR_DATED_MIN_EDGE = 0.20 # 20% min edge for contracts >60 days out
ECON_MAX_ENTRY_PRICE  = 0.65   # No entries above 65c (poor risk/reward)
ECON_MAX_POSITION     = 25.00  # kept for ruppert_cycle.py budget checks
ECON_MAX_DAILY_EXPOSURE = 100.00  # kept for ruppert_cycle.py budget checks

# Risk settings - Geopolitical (separate budget, LLM-estimated edges)
GEO_MAX_POSITION_SIZE    = 25.00   # kept for ruppert_cycle.py budget checks
GEO_MAX_DAILY_EXPOSURE   = 100.00  # kept for ruppert_cycle.py budget checks
GEO_MIN_EDGE_THRESHOLD   = 0.15    # 15% min edge (higher than weather/crypto - geo harder to model)
GEO_MAX_CONFIDENCE       = 0.85    # Cap - LLM estimates less calibrated than ensemble weather
GEO_MIN_DAYS_TO_EXPIRY   = 1       # No same-day expiry for geo markets

# Loss circuit breaker — halt trading if realized losses exceed this % of capital today
LOSS_CIRCUIT_BREAKER_PCT = 0.05  # 5% of capital

# Bot settings
CHECK_INTERVAL_HOURS = 6       # How often to scan for opportunities
# Minimum hours remaining before market close to enter a trade.
# Markets closing in less than this many hours are skipped.
# Uses Kalshi close_time directly — no timezone math needed.
# Autoresearch-tunable: lower = more trades, higher = more certainty of fill.
MIN_HOURS_TO_CLOSE = 4.0

# DEPRECATED: replaced by MIN_HOURS_TO_CLOSE (timezone-independent)
# SAME_DAY_SKIP_AFTER_HOUR = 14

# Minimum hours to settlement before allowing entry — per module
# Default (hourly/daily markets): 0.5h (30 min)
# crypto_15m: 0.04h (≈2.4 min) — 15m window is only 0.25h total; timing gate is the binding constraint
MIN_HOURS_ENTRY = {
    'default':    0.5,
    'crypto_15m': 0.04,   # 2.4 min remaining — allows all primary + secondary window entries
}

# Minimum confidence thresholds per module
MIN_CONFIDENCE = {
    'weather':    0.25,
    'crypto':     0.50,
    'fed':        0.55,
    'geo':        0.50,
    'crypto_15m': 0.50,
    'econ':       0.55,
}

# ── Volume-Tier Edge Discounting ──────────────────────────────────────────────
# Discount edge for thin markets — low volume means poor price discovery
# Optimizer will review thin-market outcomes after 30 days of data
VOLUME_TIER_THICK    = 5000   # contracts/24h; no discount
VOLUME_TIER_MID      = 1000   # moderate discount
VOLUME_DISCOUNT_MID  = 0.85   # edge × 0.85 (15% discount)
VOLUME_DISCOUNT_THIN = 0.65   # edge × 0.65 (35% discount)

# Minimum yes_ask price to enter (skip penny markets with no orderbook)
MIN_YES_ASK = 5  # cents — skip markets priced at 1-4c

# Maximum model vs market divergence for unvalidated cities
# If |model_prob - market_prob| > this threshold, skip (market is telling us something)
MAX_MODEL_MARKET_DIVERGENCE = 0.70  # 70% gap = market likely knows better

# Optimizer thresholds
OPTIMIZER_MIN_TRADES         = 30    # minimum trades per module before optimizer runs
OPTIMIZER_LOW_WIN_RATE       = 0.60  # flag if win rate below this
OPTIMIZER_BRIER_FLAG         = 0.25  # flag if Brier score above this (worse calibration)
OPTIMIZER_HOLD_TIME_FLAG_HRS = 12    # flag if avg hold time above this
OPTIMIZER_CAP_UTIL_FLAG      = 0.30  # flag if avg cap utilization below 30%
OPTIMIZER_MAX_AVG_SIZE       = 40.0  # flag if avg position size above this

# ── 15-Min Crypto Direction (KXBTC15M / KXETH15M / KXXRP15M / KXDOGE15M / KXSOL15M) ────
CRYPTO_15M_MIN_EDGE          = 0.02   # DATA COLLECTION: 2% min edge (was 0.05)
CRYPTO_15M_LIQUIDITY_MIN_PCT = 0.0005 # DATA COLLECTION: 0.05% of OI (was 0.001)
CRYPTO_15M_SIGMOID_SCALE     = 1.0    # sigmoid scale factor (autoresearcher-tunable)
CRYPTO_15M_WINDOW_CAP_PCT           = 0.02   # 2% of capital per 15-min window (~$166 at $8,300 capital)
CRYPTO_15M_DAILY_WAGER_CAP_PCT      = 0.40   # 40% backstop only — execution bug safety net, not normal risk control
CRYPTO_15M_CIRCUIT_BREAKER_N        = 3      # consecutive complete-loss windows before halt
CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = True   # True = log warning only, don't actually halt (data collection mode)
CRYPTO_15M_MAX_SPREAD        = 25     # DATA COLLECTION: 25c max spread (was 15)
CRYPTO_15M_THIN_MARKET_RATIO = 0.01   # DATA COLLECTION: 1% of 30d avg vol (was 0.05)
CRYPTO_15M_MIN_CONVICTION    = 0.05   # DATA COLLECTION: min |raw_score| (was hardcoded 0.15)
CRYPTO_15M_LIQUIDITY_FLOOR   = 20.0   # DATA COLLECTION: absolute floor $20 (was $50/$100)
CRYPTO_15M_ENTRY_CUTOFF_SECS    = 800    # Max elapsed secs to allow entry (was 720 = 12 min); 800 = 13.3 min — captures WS reconnect close-calls
CRYPTO_15M_EARLY_WINDOW_SECS    = 90     # Min elapsed secs before entry allowed (was hardcoded 120); 90s re-admits 90-120s band
CRYPTO_15M_SECONDARY_START_SECS = 480    # Elapsed secs where secondary (tighter) window begins (was hardcoded 480)
CRYPTO_15M_FALLBACK_MIN_REMAINING = 180  # Fallback stops firing if < this many secs remain before close (was hardcoded 120)

# ── WS-First Architecture ────────────────────────────────────────────────────
# Active series prefixes — only cache tickers matching these.
# Update this list when adding new market series (no code change needed).
WS_ACTIVE_SERIES = [
    # Weather
    'KXHIGHT', 'KXHIGHNY', 'KXHIGHMI', 'KXHIGHCH',
    'KXHIGHDE', 'KXHIGHAT', 'KXHIGHLAX', 'KXHIGHAUS',
    'KXHIGHSE', 'KXHIGHSF', 'KXHIGHPH', 'KXHIGHLV',
    'KXHIGHSA', 'KXHIGHMIA',
    # Crypto hourly bands
    'KXBTC', 'KXETH', 'KXXRP', 'KXDOGE', 'KXSOL',
    # Crypto 15m direction
    'KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M',
    # Crypto long-horizon (monthly/annual)
    'KXBTCMAXM', 'KXBTCMAXY', 'KXBTCMINY', 'KXBTC2026250', 'KXBTCMAX100',
    'KXETHMAXM', 'KXETHMINY', 'KXETHMAXY',
    # Econ
    'KXCPI', 'KXPCE', 'KXJOBS', 'KXUNEMPLOYMENT', 'KXGDP',
    # Fed
    'KXFED', 'KXFOMC',
    # Geo — P2-7 fix: added so ws_feed monitors geo positions for real-time exits
    'KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN', 'KXTAIWAN',
    'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE',
]
WS_CACHE_STALE_SECONDS = 60      # trigger REST fallback after this many seconds
WS_CACHE_PURGE_SECONDS = 86400   # purge dead entries after this many seconds (24h)

# ── Long-Horizon Crypto (KXBTCMAXY, KXBTCMAXM, etc.) ────────────────────────
LONG_HORIZON_MIN_EDGE = 0.08        # 8c minimum edge
LONG_HORIZON_MAX_SPREAD = 10        # max 10c spread (monthly/annual are tighter)
LONG_HORIZON_MAX_POSITION_PCT = 0.005  # 0.5% of capital per trade
LONG_HORIZON_DAILY_CAP_PCT = 0.10   # 10% of capital/day total for this module

# ── Expanded Cities (Weather) ────────────────────────────────────────────────
# Disable trading on cities with unvalidated bias corrections (0.0 bias).
# Re-enable after GHCND analysis validates bias offsets for each city.
EXPANDED_CITIES_ENABLED = False

# ── New City Gate ────────────────────────────────────────────────────────────
# Prevent bot from picking up brand-new cities it has never traded before.
# Existing cities (any trade history in logs/trades/) are always allowed.
# Set True only when existing cities have 30+ scored trades each.
ALLOW_NEW_CITIES = False

# Cities to skip when EXPANDED_CITIES_ENABLED = False
# These have 0.0 bias correction (not yet calibrated from GHCND data)
EXPANDED_CITIES_SKIP = [
    "KXHIGHTDC",    # Washington DC
    "KXHIGHPHIL",   # Philadelphia
    "KXHIGHDEN",    # Denver
    "KXHIGHTMIN",   # Minneapolis
    "KXHIGHTLV",    # Las Vegas
    "KXHIGHTNOU",   # New Orleans
    "KXHIGHTOKC",   # Oklahoma City
    "KXHIGHTSEA",   # Seattle
    "KXHIGHTSATX",  # San Antonio
    "KXHIGHTATL",   # Atlanta
]

# ── Capital Fallback ─────────────────────────────────────────────────────────
CAPITAL_FALLBACK = 10000.0  # fallback capital when API unavailable

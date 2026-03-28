"""
Configuration loader - reads credentials from secrets folder.
Never hardcodes API keys.
"""
import json
import os

# Paths
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

# Per-trade position size cap — percentage of total capital
MAX_POSITION_PCT = 0.01   # 1% of capital per trade (replaces fixed $25 caps)

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

# Minimum confidence thresholds per module
MIN_CONFIDENCE = {
    'weather': 0.25,
    'crypto':  0.50,
    'fed':     0.55,
    'geo':     0.50,
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

# ── 15-Min Crypto Direction (KXBTC15M / KXETH15M / KXXRP15M / KXDOGE15M) ────
CRYPTO_15M_MIN_EDGE      = 0.08   # 8% minimum edge to enter
CRYPTO_15M_LIQUIDITY_MIN_PCT = 0.003  # book depth must be >= 0.3% of open interest
CRYPTO_15M_SIGMOID_SCALE = 1.0    # sigmoid scale factor (autoresearcher-tunable)
CRYPTO_15M_DAILY_CAP_PCT = 0.04   # 4% of capital per day

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
    'KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M',
    # Crypto long-horizon (monthly/annual)
    'KXBTCMAXM', 'KXBTCMAXY', 'KXBTCMINY', 'KXBTC2026250', 'KXBTCMAX100',
    'KXETHMAXM', 'KXETHMINY', 'KXETHMAXY',
    # Econ
    'KXCPI', 'KXPCE', 'KXJOBS', 'KXUNEMPLOYMENT', 'KXGDP',
    # Fed
    'KXFED', 'KXFOMC',
]
WS_CACHE_STALE_SECONDS = 60      # trigger REST fallback after this many seconds
WS_CACHE_PURGE_SECONDS = 300     # purge dead entries after this many seconds

# ── Long-Horizon Crypto (KXBTCMAXY, KXBTCMAXM, etc.) ────────────────────────
LONG_HORIZON_MIN_EDGE = 0.08        # 8c minimum edge
LONG_HORIZON_MAX_SPREAD = 10        # max 10c spread (monthly/annual are tighter)
LONG_HORIZON_MAX_POSITION_PCT = 0.005  # 0.5% of capital per trade
LONG_HORIZON_DAILY_CAP_PCT = 0.10   # 10% of capital/day total for this module

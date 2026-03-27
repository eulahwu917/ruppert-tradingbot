"""
Configuration loader - reads credentials from secrets folder.
Never hardcodes API keys.
"""
import json
import os

# Paths
SECRETS_DIR = os.path.join(os.path.dirname(__file__), '..', 'secrets')
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

# Risk settings - Weather / Economics
MIN_EDGE_THRESHOLD = 0.12      # Min edge (12%) to trigger a trade
MIN_MARKET_LIQUIDITY = 100.00  # Min $ volume in market to trade

# Risk settings - Crypto (separate budget, FULLY AUTO like weather)
CRYPTO_MIN_EDGE_THRESHOLD = 0.12   # 12% min edge (consistent with weather)

# Auto-trade settings
# Weather + Crypto = fully autonomous (no notification, no approval)
# Geo = OFF until Phase 4 is validated - David decides when to enable
WEATHER_AUTO_TRADE  = True   # Bot executes without asking
CRYPTO_AUTO_TRADE   = True   # Bot executes without asking
GEO_AUTO_TRADE      = True   # DEMO: enabled for training data accumulation (2026-03-26)
ECON_AUTO_TRADE       = True    # DEMO: fully autonomous (Phase 5)
ECON_MIN_EDGE         = 0.12   # 12% min edge to trigger a trade
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

# Bot settings
CHECK_INTERVAL_HOURS = 6       # How often to scan for opportunities
SAME_DAY_SKIP_AFTER_HOUR = 14  # skip same-day weather markets after 2pm local

# Direction filter - only bet NO on weather markets
# Backtest 2026-03-13: NO=90.4% win rate, YES=14.9%
WEATHER_DIRECTION_FILTER = "NO"

# Minimum confidence thresholds per module
MIN_CONFIDENCE = {
    'weather': 0.25,
    'crypto':  0.50,
    'fed':     0.55,
    'geo':     0.50,
}

# Optimizer thresholds
OPTIMIZER_MIN_TRADES         = 30    # minimum trades per module before optimizer runs
OPTIMIZER_LOW_WIN_RATE       = 0.60  # flag if win rate below this
OPTIMIZER_BRIER_FLAG         = 0.25  # flag if Brier score above this (worse calibration)
OPTIMIZER_HOLD_TIME_FLAG_HRS = 12    # flag if avg hold time above this
OPTIMIZER_CAP_UTIL_FLAG      = 0.30  # flag if avg cap utilization below 30%
OPTIMIZER_MAX_AVG_SIZE       = 40.0  # flag if avg position size above this

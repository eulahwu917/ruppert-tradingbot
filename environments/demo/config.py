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

# DAILY CAPS REMOVED (Phase 2 — 2026-03-31)
# Rationale: Circuit breaker is the daily hard stop. Per-module caps were
# limiting trade throughput with insufficient risk-control benefit.
# Optimizer to revisit after 30+ days of post-CB data.

# Legacy keys (kept for reference / future re-enable)
# WEATHER_DAILY_CAP_PCT = 0.07   # removed Phase 2
CRYPTO_DAILY_CAP_PCT  = 0.07   # daily cap for crypto module (legacy fallback)
# ECON_DAILY_CAP_PCT    = 0.04   # removed Phase 2
# FED_DAILY_CAP_PCT     = 0.03   # removed Phase 2
# CRYPTO_15M_DAILY_CAP_PCT = 0.10 # removed Phase 2

# New taxonomy keys (also removed Phase 2)
# WEATHER_BAND_DAILY_CAP_PCT      = 0.07   # removed Phase 2
# WEATHER_THRESHOLD_DAILY_CAP_PCT = 0.07   # removed Phase 2
# CRYPTO_1H_BAND_DAILY_CAP_PCT    = 0.07   # removed Phase 2
# CRYPTO_1H_DIR_DAILY_CAP_PCT     = 0.15   # removed Phase 2
# CRYPTO_15M_DIR_DAILY_CAP_PCT    = 0.10   # removed Phase 2
# ECON_CPI_DAILY_CAP_PCT          = 0.04   # removed Phase 2
# ECON_UNEMPLOYMENT_DAILY_CAP_PCT = 0.04   # removed Phase 2
# ECON_FED_RATE_DAILY_CAP_PCT     = 0.03   # removed Phase 2
# ECON_RECESSION_DAILY_CAP_PCT    = 0.04   # removed Phase 2
# GEO_DAILY_CAP_PCT               = 0.04   # removed Phase 2

# GEO_DAILY_CAP_PCT still needed — it was in strategy gate checks only,
# and with caps removed, strategy.py will log a warning and allow through.
# (No value needed; getattr fallback of None in should_enter() = no enforcement)

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
WEATHER_AUTO_TRADE  = False  # HALTED 2026-04-01 - focus on crypto only
CRYPTO_AUTO_TRADE   = True   # Bot executes without asking
GEO_AUTO_TRADE      = False  # HALTED 2026-04-01 - focus on crypto only
ECON_AUTO_TRADE       = False   # HALTED 2026-04-01 - focus on crypto only
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
# crypto_dir_15m_*: 0.04h (≈2.4 min) — 15m window is only 0.25h total; timing gate is the binding constraint
MIN_HOURS_ENTRY = {
    'default':                    0.5,
    'crypto_dir_15m_btc':         0.04,   # ≈2.4 min remaining — allows all primary + secondary window entries
    'crypto_dir_15m_eth':         0.04,
    'crypto_dir_15m_sol':         0.04,
    'crypto_dir_15m_xrp':         0.04,
    'crypto_dir_15m_doge':        0.04,
    'crypto_threshold_daily_btc': 2.0,    # hard cutoff at 15:00 ET = 2h before 17:00 settlement
    'crypto_threshold_daily_eth': 2.0,
    'crypto_threshold_daily_sol': 2.0,
}

# Minimum confidence thresholds per module
MIN_CONFIDENCE = {
    'weather_band':               0.25,
    'weather_threshold':          0.25,
    'crypto_band_daily_btc':      0.50,
    'crypto_band_daily_eth':      0.50,
    'crypto_band_daily_xrp':      0.50,
    'crypto_band_daily_doge':     0.50,
    'crypto_band_daily_sol':      0.50,
    'crypto_threshold_daily_btc': 0.50,
    'crypto_threshold_daily_eth': 0.50,
    'crypto_threshold_daily_sol': 0.50,
    'crypto_dir_15m_btc':         0.40,   # Phase 2: lowered from 0.50
    'crypto_dir_15m_eth':         0.40,
    'crypto_dir_15m_sol':         0.40,
    'crypto_dir_15m_xrp':         0.40,
    'crypto_dir_15m_doge':        0.40,
    'econ_cpi':                   0.55,
    'econ_unemployment':          0.55,
    'econ_fed_rate':              0.55,
    'econ_recession':             0.55,
    'geo':                        0.50,
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
# Batch-3 config keys (previously hardcoded in crypto_15m.py)
CRYPTO_15M_SESSION_DRAWDOWN_PAUSE_PCT = 0.05    # pause if session loss > this % of capital
CRYPTO_15M_SECONDARY_EDGE_MULTIPLIER  = 1.25    # edge multiplier for secondary window
CRYPTO_15M_MAX_BASIS_PCT              = 0.0015  # max Coinbase-OKX basis before BASIS_RISK block
CRYPTO_15M_TFI_BUCKET_WEIGHTS         = [0.20, 0.30, 0.50]  # time-weighted TFI composite weights
CRYPTO_15M_ROLLING_WINDOW_BUCKETS     = 48      # 4 hours of 5-min buckets
CRYPTO_15M_FUNDING_Z_THRESHOLD        = 2.0     # funding rate z-score threshold
CRYPTO_15M_FUNDING_BEARISH_MULT       = 0.85    # P multiplier when funding z > threshold (bearish)
CRYPTO_15M_FUNDING_BULLISH_MULT       = 1.15    # P multiplier when funding z < -threshold (bullish)
CRYPTO_15M_POLY_DIVERGENCE_THRESHOLD  = 0.03    # min |divergence| to apply Polymarket nudge
CRYPTO_15M_POLY_NUDGE_WEIGHT          = 0.3     # weight for Polymarket divergence nudge

CRYPTO_15M_MIN_EDGE          = 0.02   # DATA COLLECTION: 2% min edge (was 0.05)
CRYPTO_15M_LIQUIDITY_MIN_PCT = 0.0005 # DATA COLLECTION: 0.05% of OI (was 0.001)
CRYPTO_15M_SIGMOID_SCALE     = 1.0    # sigmoid scale factor (autoresearcher-tunable)
CRYPTO_15M_WINDOW_CAP_PCT           = 0.04   # 4% of capital per 15-min window (Phase 2; was 0.02)
CRYPTO_15M_DAILY_WAGER_CAP_PCT      = 0.60   # 60% backstop — raised to give strategy gate more room; CB is the daily hard stop
CRYPTO_15M_CIRCUIT_BREAKER_N        = 3      # consecutive complete-loss windows before halt
CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = False  # False = hard stop — halt all crypto_15m entries for rest of trading day
CRYPTO_15M_STOP_LOSS_SECS = 210  # stop-loss fires when < this many seconds remain AND bid < 40% of entry

# ── crypto_dir_15m_* Signal Weights ─────────────────────────────────────────
CRYPTO_15M_DIR_W_TFI  = 0.50   # Taker Flow Imbalance weight (Phase 2: increased from 0.42)
CRYPTO_15M_DIR_W_OBI  = 0.25   # Orderbook Imbalance weight (unchanged)
CRYPTO_15M_DIR_W_MACD = 0.15   # MACD Histogram weight (unchanged)
CRYPTO_15M_DIR_W_OI   = 0.10   # Open Interest Delta weight (Phase 2: reduced from 0.18)
# Must sum to 1.0; Optimizer owns these values
# Sum check: 0.50 + 0.25 + 0.15 + 0.10 = 1.00 ✓

CRYPTO_15M_DIR_HARD_CAP_USD     = 100.0   # absolute per-trade dollar cap (half-Kelly formula)
CRYPTO_15M_DIR_MIN_POSITION_USD =   5.0   # minimum viable trade size
CRYPTO_15M_DIR_DAILY_BACKSTOP_ENABLED = False   # Phase 2: disabled — CB is daily guardrail
CRYPTO_15M_MAX_SPREAD        = 25     # DATA COLLECTION: 25c max spread (was 15)
CRYPTO_15M_THIN_MARKET_RATIO = 0.01   # DATA COLLECTION: 1% of 30d avg vol (was 0.05)
CRYPTO_15M_MIN_CONVICTION    = 0.05   # DATA COLLECTION: min |raw_score| (was hardcoded 0.15)
CRYPTO_15M_LIQUIDITY_FLOOR   = 20.0   # DATA COLLECTION: absolute floor $20 (was $50/$100)
CRYPTO_15M_ENTRY_CUTOFF_SECS    = 800    # Max elapsed secs to allow entry (was 720 = 12 min); 800 = 13.3 min — captures WS reconnect close-calls
CRYPTO_15M_EARLY_WINDOW_SECS    = 90     # Min elapsed secs before entry allowed (was hardcoded 120); 90s re-admits 90-120s band
CRYPTO_15M_SECONDARY_START_SECS = 480    # Elapsed secs where secondary (tighter) window begins (was hardcoded 480)
CRYPTO_15M_FALLBACK_MIN_REMAINING = 180  # Fallback stops firing if < this many secs remain before close (was hardcoded 120)

# ── Daily Crypto Above/Below (crypto_1d: KXBTCD / KXETHD / KXSOLD) ──────────
# Separate cap pool from crypto_15m. Trades daily above/below at 09:30 ET (primary)
# and 13:30 ET (secondary, gated by global exposure).
CRYPTO_1D_DAILY_CAP_PCT            = 0.15   # 15% of capital/day total across all crypto_1d
CRYPTO_1D_WINDOW_CAP_PCT           = 0.05   # 5% of capital per single entry
CRYPTO_1D_PER_ASSET_CAP_PCT        = 0.03   # 3% of capital per asset per day
CRYPTO_1D_MAX_POSITION_USD         = 200.0  # hard cap per entry (liquidity constraint)
CRYPTO_1D_MIN_EDGE                 = 0.08   # primary window minimum edge (8%)
CRYPTO_1D_SECONDARY_MIN_EDGE       = 0.12   # 1.5× minimum edge for secondary window entries
CRYPTO_1D_SECONDARY_MAX_EXPOSURE_PCT = 0.50 # skip secondary window if global exposure >= 50%
# Batch-3 config keys (previously hardcoded in crypto_1d.py)
CRYPTO_1D_MIN_POSITION_USD         = 10.0   # minimum viable trade size
CRYPTO_1D_MAX_DISCOVERY_SPREAD     = 12     # max spread (cents) during market discovery
CRYPTO_1D_MIN_BOOK_DEPTH_USD       = 300    # minimum book depth ($) to allow entry
CRYPTO_1D_HIGH_VOL_BTC             = 0.03   # ATR high-vol threshold for BTC
CRYPTO_1D_HIGH_VOL_ETH             = 0.04   # ATR high-vol threshold for ETH
CRYPTO_1D_HIGH_VOL_SOL             = 0.05   # ATR high-vol threshold for SOL

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
# Batch-3 config keys (previously hardcoded in crypto_long_horizon.py)
LONG_HORIZON_MAX_POSITION_USD   = 50.0   # hard $ cap per long-horizon trade
LONG_HORIZON_VOL_MULT_BULL      = 1.2    # vol multiplier in bull regime
LONG_HORIZON_VOL_MULT_NEUTRAL   = 1.0    # vol multiplier in neutral regime
LONG_HORIZON_VOL_MULT_BEAR      = 1.4    # vol multiplier in bear regime
LONG_HORIZON_BARRIER_BOOST      = 1.5    # barrier reflection principle boost cap
LONG_HORIZON_FAT_TAIL_ADDEND    = 0.03   # additive fat-tail correction for extreme strikes

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

# ── T-Type Weather Markets ────────────────────────────────────────────────────
# Margin-based signal thresholds (°F from threshold)
TTYPE_MARGIN_NO_TRADE = 2.0    # Below this margin: skip (coin flip territory)
TTYPE_MARGIN_WEAK     = 5.0    # Below this: weak confidence
TTYPE_MARGIN_STRONG   = 8.0    # Above this: strong confidence

# Confidence levels per margin tier
TTYPE_CONF_WEAK       = 0.50   # 2–5°F margin → 50% confidence
TTYPE_CONF_STANDARD   = 0.75   # 5–8°F margin → 75% confidence
TTYPE_CONF_STRONG     = 0.90   # ≥8°F margin → 90% confidence

# Sizing — DEMO data collection phase
TTYPE_PER_TRADE_SIZE      = 50.0    # $50 per T-type trade
TTYPE_MAX_DAILY           = 500.0   # $500/day hard cap across all T-type trades
TTYPE_PER_CITY_DAILY_MAX  = 100.0   # $100/city/day (across upper + lower threshold)

# Enable T-type in DEMO (set False to disable without code changes)
TTYPE_ENABLED = True

# ── T-Type Soft Prior (edge_detector.py) ─────────────────────────────────────
# Batch-3 config keys (previously hardcoded in edge_detector.py)
TTYPE_SOFT_PRIOR_EDGE_THRESHOLD = 0.30   # apply soft prior when |edge| <= this value
TTYPE_SOFT_PRIOR_NO_MULT        = 1.15   # confidence multiplier for NO side (longshot bias boost)
TTYPE_SOFT_PRIOR_YES_MULT       = 0.85   # confidence multiplier for YES side (longshot bias penalty)

# ── Weather Ensemble (edge_detector.py) ──────────────────────────────────────
WEATHER_MIN_ENSEMBLE_CONFIDENCE = 0.5    # minimum ensemble confidence to proceed
WEATHER_NWS_CONFIDENCE_PENALTY  = 0.15  # subtract this from confidence when NWS unavailable

# ── Capital Fallback ─────────────────────────────────────────────────────────
CAPITAL_FALLBACK = 10000.0  # fallback capital when API unavailable

# ── Position Exit Thresholds ─────────────────────────────────────────────────
EXIT_95C_THRESHOLD = 95     # cents — auto-exit YES position if bid >= this
EXIT_GAIN_PCT      = 0.90   # fraction of max upside — auto-exit at this gain (Phase 2; was 0.70)

# Reversal exit thresholds (edge collapse from entry)
EXIT_REVERSAL_FULL = 0.35   # full exit if edge collapsed by this much
EXIT_REVERSAL_HALF = 0.20   # half exit if edge collapsed by this much
EXIT_REVERSAL_TRIM = 0.10   # trim (25%) exit if edge collapsed by this much

# Reversal exit fractions (portion of position to close)
EXIT_REVERSAL_FULL_FRACTION = 1.0    # 100% of position
EXIT_REVERSAL_HALF_FRACTION = 0.50   # 50% of position
EXIT_REVERSAL_TRIM_FRACTION = 0.25   # 25% of position

# Add-on confidence delta gates
ADD_DELTA_HIGH = 0.50   # confidence delta >= this: full add scale
ADD_DELTA_MID  = 0.25   # confidence delta >= this: mid add scale
ADD_DELTA_MIN  = 0.10   # minimum confidence delta to allow add-on at all

# Add-on scale factors (fraction of remaining allocation)
ADD_SCALE_HIGH = 1.00   # 100% of remaining when delta >= ADD_DELTA_HIGH
ADD_SCALE_MID  = 0.50   # 50% of remaining when delta >= ADD_DELTA_MID
ADD_SCALE_MIN  = 0.25   # 25% of remaining when delta >= ADD_DELTA_MIN

# ── Market Impact Ceiling ─────────────────────────────────────────────────────
MARKET_IMPACT_SPREAD_LIQUID   = 3      # cents — spread at or below = liquid market, full size
MARKET_IMPACT_SPREAD_THIN     = 7      # cents — spread above = thin market, hard cap
MARKET_IMPACT_THIN_SIZE_CAP   = 25.0   # max $ size for thin markets
MARKET_IMPACT_MODERATE_SCALE  = 0.5    # size scale factor for moderate spread (4–7c)
MARKET_IMPACT_OI_CAP_PCT      = 0.05   # OI cap: max 5% of open interest

# ── Minimum Viable Trade ──────────────────────────────────────────────────────
MIN_VIABLE_TRADE_USD          = 5.0    # hard floor in dollars
MIN_VIABLE_TRADE_POSITION_PCT = 0.10   # or 10% of the per-trade cap, whichever is larger

# ── Settlement Guard ──────────────────────────────────────────────────────────
# When yes_bid = 0 fires a NO exit, if we are within this many seconds of the
# contract's close_time, call REST to verify the actual result before executing.
# Prevents phantom wins from orderbook-cleared settlement messages.
SETTLEMENT_GUARD_WINDOW_SECS = 90   # seconds before/after close_time to guard

# ── Minimum Edge per Module (strategy gate) ───────────────────────────────────
# These are the STRATEGY GATE minimums — a secondary check in should_enter().
# Individual modules may also have local edge gates (e.g. CRYPTO_15M_MIN_EDGE).
MIN_EDGE_WEATHER_BAND               = 0.12
MIN_EDGE_WEATHER_THRESHOLD          = 0.12
MIN_EDGE_CRYPTO_BAND_DAILY          = 0.12   # applies to crypto_band_daily_* modules
MIN_EDGE_CRYPTO_DIR_15M             = 0.12   # strategy gate; local gate = CRYPTO_15M_MIN_EDGE (0.02)
MIN_EDGE_CRYPTO_THRESHOLD_DAILY     = 0.08   # applies to crypto_threshold_daily_* modules
MIN_EDGE_GEO                        = 0.15
MIN_EDGE_ECON_CPI                   = 0.12
MIN_EDGE_ECON_UNEMPLOYMENT          = 0.12
MIN_EDGE_ECON_FED_RATE              = 0.12
MIN_EDGE_ECON_RECESSION             = 0.12

# ── Strategy Gate Scalars ─────────────────────────────────────────────────────
STRATEGY_MIN_CONFIDENCE_FLOOR = 0.25   # universal fallback when module not in MIN_CONFIDENCE dict
STRATEGY_MIN_HOURS_ADD        =  2.0   # min hours to settlement to allow add-on
DAILY_CAP_RATIO               =  0.70  # max fraction of capital deployable per day (also: global exposure cap)

# ── Confidence-Tiered Kelly Fractions ─────────────────────────────────────────
# Higher confidence → larger Kelly fraction. Optimizer owns these values.
# All tiers compressed (vs full Kelly) — unvalidated calibration phase.
KELLY_TIER_80 = 0.16   # 80%+ confidence
KELLY_TIER_70 = 0.14   # 70–80%
KELLY_TIER_60 = 0.12   # 60–70%
KELLY_TIER_50 = 0.10   # 50–60%
KELLY_TIER_40 = 0.07   # 40–50%
KELLY_TIER_25 = 0.05   # 25–40% (data accumulation floor)

# ── 1h Band Circuit Breaker ───────────────────────────────────────────────────
CRYPTO_1H_CIRCUIT_BREAKER_N        = 3      # consecutive complete-loss windows before halt
CRYPTO_1H_CIRCUIT_BREAKER_ADVISORY = False  # False = hard stop; True = log only


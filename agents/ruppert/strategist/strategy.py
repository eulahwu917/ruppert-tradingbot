"""
Trading Strategy Layer — Module-Agnostic Capital Deployment

This module is the single source of truth for ALL sizing, entry, add-on, and
exit decisions. Market modules (weather, crypto, etc.) return *signals*; they
never touch dollar amounts. Strategy converts signals → dollar decisions.

Signal dict contract (produced by each module):
    {
        'edge':                float,   # model_prob - market_implied_prob
        'win_prob':            float,   # model's estimated win probability
        'confidence':          float,   # 0–1 model confidence score
        'hours_to_settlement': float,   # hours until market settles
        'module':              str,     # 'weather' | 'crypto'
        'vol_ratio':           float,   # optional; 1.0 = normal vol (default)
    }
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

import config as _cfg
import config

# ---------------------------------------------------------------------------
# Module-specific thresholds (mirrors config.py constants)
# ---------------------------------------------------------------------------
MIN_EDGE = {
    'weather':    0.12,   # lowered from 0.30 (Post-Brier review: recalibrated)
    'crypto':     0.12,
    'crypto_15m': getattr(config, 'CRYPTO_15M_MIN_EDGE', 0.08),
    'geo':        0.15,   # Phase 4: higher than crypto — geo harder to model (LLM-estimated)
    'econ':       0.12,   # Phase 5: economics/CPI — matches config.ECON_MIN_EDGE
    'fed':        0.12,   # Phase 5: Fed rate — matches fed_client.FED_MIN_EDGE
}
MIN_CONFIDENCE   = 0.25          # universal minimum confidence to enter (Post-Brier review)
MIN_HOURS_ENTRY  = 0.5           # must be ≥ 30 min from settlement to open
MIN_HOURS_ADD    = 2.0           # must be ≥ 2 h from settlement to add
DAILY_CAP_RATIO  = 0.70          # max fraction of total capital deployable per day
# MAX_POSITION_CAP = 50.0        # removed: replaced by MAX_POSITION_PCT in config.py
# PCT_CAPITAL_CAP  = 0.025       # removed: replaced by MAX_POSITION_PCT in config.py
KELLY_FRACTION   = 0.16          # max fractional Kelly multiplier (80%+ confidence tier)


# ---------------------------------------------------------------------------
# 0. Confidence-tiered Kelly fraction
# ---------------------------------------------------------------------------

def kelly_fraction_for_confidence(confidence: float) -> float:
    """
    Return the fractional Kelly multiplier appropriate for a given confidence level.

    Higher confidence -> larger fraction of the Kelly-optimal bet.
    6-tier structure for DEMO data accumulation phase (2026-03-26).
    Low confidence tiers (25-50%) added to maximize trade volume in DEMO.

    Tiers:
        80%+    -> 0.16  (compressed from 0.25 -- unvalidated calibration)
        70-80%  -> 0.14
        60-70%  -> 0.12
        50-60%  -> 0.10
        40-50%  -> 0.07
        25-40%  -> 0.05  (minimum -- data accumulation only)

    Post-Brier review: recalibrate all tiers against actual calibration data.
    """
    if confidence >= 0.80:
        return 0.16
    if confidence >= 0.70:
        return 0.14
    if confidence >= 0.60:
        return 0.12
    if confidence >= 0.50:
        return 0.10
    if confidence >= 0.40:
        return 0.07
    return 0.05  # 25-40% confidence band


# ---------------------------------------------------------------------------
# 1a. Market Impact Ceiling (Phase 1 — bid/ask spread proxy)
# ---------------------------------------------------------------------------

def apply_market_impact_ceiling(
    base_size: float,
    yes_ask: int,
    yes_bid: int,
    open_interest: float | None = None,
) -> tuple[float, str]:
    """
    Apply market impact ceiling to a proposed trade size via bid/ask spread proxy.

    Phase 1 (zero extra API cost): wide spread = thin market = reduced size.
    Phase 2 (OI cap): optional additional ceiling when open_interest is provided.

    Tiers:
        spread ≤ 3¢  → liquid, full size
        spread 4–7¢  → moderate, cap at 50% of base size
        spread > 7¢  → thin, floor at $25 hard minimum

    OI cap (Phase 2): if open_interest provided, cap at 5% of OI.
    This protects against entering thin markets and is module-agnostic.

    Args:
        base_size:      Kelly-sized dollar amount before impact adjustment.
        yes_ask:        YES ask price in cents (0-100).
        yes_bid:        YES bid price in cents (0-100).
        open_interest:  Optional open interest in dollars for OI cap (Phase 2).

    Returns:
        (adjusted_size: float, reason: str)
    """
    spread = yes_ask - yes_bid  # cents

    if spread <= 3:
        size = base_size
        reason = "liquid"
    elif spread <= 7:
        size = base_size * 0.5
        reason = f"moderate_spread({spread}c)"
    else:
        size = min(base_size, 25.0)
        reason = f"thin_spread({spread}c)_floored"

    # Phase 2: OI cap (when open_interest available)
    if open_interest is not None and open_interest > 0:
        oi_cap = open_interest * 0.05
        if size > oi_cap:
            size = oi_cap
            reason += f"_oi_cap({oi_cap:.0f})"

    return round(size, 2), reason


# ---------------------------------------------------------------------------
# 1. Position Sizing
# ---------------------------------------------------------------------------

def calculate_position_size(edge: float, win_prob: float, capital: float,
                             vol_ratio: float = 1.0,
                             confidence: float = 0.80) -> float:
    """
    Compute a dollar position size using confidence-tiered fractional Kelly.

    Args:
        edge:       Estimated edge = model_prob − market_implied_prob.
        win_prob:   Model's estimated probability of winning (0 < p < 1).
        capital:    Total available capital in dollars.
        vol_ratio:  Volatility ratio vs baseline; >1.0 = higher vol → smaller
                    position.  Defaults to 1.0 (no adjustment).
        confidence: Model confidence score (0–1); selects Kelly tier.
                    Defaults to 0.80 (max tier) for backward compatibility.

    Returns:
        Dollar amount to deploy (float).  Always ≥ 0.

    Formula:
        kf          = kelly_fraction_for_confidence(confidence)  ← tiered
        f           = edge / (1 − win_prob)    ← Kelly fraction
        kelly_size  = kf * f * capital
        kelly_size *= 1 / vol_ratio            ← vol shrinkage
        size        = min(kelly_size, MAX_POSITION_PCT % of capital)

    Cap:
        Hard cap = capital * config.MAX_POSITION_PCT (default 0.01 = 1%).
        At $1,000 capital this is $10 max per trade.
        To change the cap, update config.MAX_POSITION_PCT — do NOT edit this file.
    """
    if win_prob <= 0 or edge <= 0 or capital <= 0:
        return 0.0

    # Cap win_prob at 0.999 to avoid division-by-zero in Kelly formula
    # when NOAA gives 100% probability — these are our highest-edge trades.
    if win_prob >= 0.999:
        win_prob = 0.999

    kf = kelly_fraction_for_confidence(confidence)
    f = edge / (1.0 - win_prob)
    kelly_size = kf * f * capital

    # Vol adjustment: high vol → smaller position
    if vol_ratio > 0:
        kelly_size *= (1.0 / vol_ratio)

    # Hard cap: 1% of capital per trade (reads from config.MAX_POSITION_PCT)
    position_cap = capital * getattr(_cfg, 'MAX_POSITION_PCT', 0.01)
    size = min(kelly_size, position_cap)
    return round(max(0.0, size), 2)


# ---------------------------------------------------------------------------
# 2. Daily Capital Cap
# ---------------------------------------------------------------------------

def check_daily_cap(total_capital: float, deployed_today: float) -> float:
    """
    Return remaining dollar capacity for today under the daily cap rule.

    Max daily deployment = 70% of total capital.

    Args:
        total_capital:  Total portfolio capital in dollars.
        deployed_today: Dollars already committed today across all modules.

    Returns:
        Remaining dollars available to deploy today (≥ 0).
    """
    max_daily = total_capital * DAILY_CAP_RATIO
    remaining = max_daily - deployed_today
    return round(max(0.0, remaining), 2)


# ---------------------------------------------------------------------------
# 2b. Open Exposure Check (real-time 70% global cap)
# ---------------------------------------------------------------------------

def check_open_exposure(total_capital: float, open_position_value: float) -> bool:
    """
    Return True if it's safe to enter (open exposure < 70% of capital).
    Return False if adding any position would exceed the global cap.

    Args:
        total_capital:       Total portfolio capital in dollars.
        open_position_value: Current total value of all open positions.

    Returns:
        True = safe to enter, False = global cap reached.
    """
    max_exposure = total_capital * DAILY_CAP_RATIO  # reuses the 0.70 constant
    return open_position_value < max_exposure


# ---------------------------------------------------------------------------
# 3. Entry Decision
# ---------------------------------------------------------------------------

def should_enter(
    signal: dict,
    capital: float,
    deployed_today: float,
    *,
    module: str = None,
    module_deployed_pct: float = 0.0,
    traded_tickers: set = None,
) -> dict:
    """
    Decide whether to open a new position.

    Applies edge, confidence, time-to-settlement, and daily-cap filters
    before sizing.  All sizing logic lives here; the market module provides
    only the signal.

    Args:
        signal:              Signal dict (see module contract at top of file).
        capital:             Total available capital in dollars.
        deployed_today:      Dollars already deployed today.
        module:              Optional module name for per-module cap check.
        module_deployed_pct: Fraction of capital already deployed by this module today.
        traded_tickers:      Optional set of tickers already traded today (same-day re-entry block).

    Returns:
        {'enter': bool, 'size': float, 'reason': str}
    """
    signal_module     = signal.get('module', 'unknown')
    edge              = signal.get('edge', 0.0)
    win_prob          = signal.get('win_prob', 0.0)
    confidence        = signal.get('confidence', 0.0)
    hours             = signal.get('hours_to_settlement', 0.0)
    vol_ratio         = signal.get('vol_ratio', 1.0)

    # --- Time gate ---
    if hours < MIN_HOURS_ENTRY:
        return {'enter': False, 'size': 0.0,
                'reason': f'too_close_to_settlement ({hours:.2f}h < {MIN_HOURS_ENTRY}h)'}

    # --- Per-module confidence gate (single gate, replaces old dual-gate) ---
    # config.MIN_CONFIDENCE is a dict keyed by module name.
    # Falls back to module-level MIN_CONFIDENCE (0.25) for unlisted modules.
    # To allow a module with threshold < 0.25, add it to config.MIN_CONFIDENCE dict explicitly.
    _module_min_conf_map = getattr(config, 'MIN_CONFIDENCE', {})
    if isinstance(_module_min_conf_map, dict):
        _per_module_thresh = _module_min_conf_map.get(signal_module, MIN_CONFIDENCE)
    else:
        _per_module_thresh = MIN_CONFIDENCE  # safety: config.MIN_CONFIDENCE not a dict
    if confidence < _per_module_thresh:
        return {'enter': False, 'size': 0.0,
                'reason': f'low_confidence ({confidence:.2f} < {_per_module_thresh} for {signal_module})'}

    # --- Edge gate (module-specific) ---
    min_edge = MIN_EDGE.get(signal_module, MIN_EDGE['weather'])
    if edge < min_edge:
        return {'enter': False, 'size': 0.0,
                'reason': f'insufficient_edge ({edge:.3f} < {min_edge} for {signal_module})'}

    # --- Global open exposure cap (real-time 70% check) ---
    if 'open_position_value' not in signal:
        logger.error(
            "[Strategy] should_enter called without 'open_position_value' in signal — "
            "failing closed to protect global cap. Caller must provide this field."
        )
        return {'enter': False, 'size': 0.0,
                'reason': 'missing_open_position_value (caller bug — fail-closed)'}
    open_position_value = signal['open_position_value']
    if not check_open_exposure(capital, open_position_value):
        return {'enter': False, 'size': 0.0,
                'reason': 'global_exposure_cap_reached (70% of capital)'}

    # --- Per-module daily cap ---
    if module is not None:
        _module_key = module.upper() + '_DAILY_CAP_PCT'
        _module_cap = getattr(config, _module_key, None)
        if _module_cap is not None:
            # NOTE: Setting MODULE_DAILY_CAP_PCT = 0.0 will ALWAYS block the module (0.0 >= 0.0 is True).
            # To disable a module, set it to a very high value (e.g. 99.0) or remove the config key entirely.
            # cap=0 does NOT mean "unlimited" — it means "never trade".
            if module_deployed_pct >= _module_cap:
                return {
                    'enter': False,
                    'size': 0.0,
                    'reason': f'module_cap_exceeded ({module}: {module_deployed_pct:.1%} >= {_module_cap:.1%})'
                }
        else:
            logger.warning(
                f'should_enter: no daily cap config for module "{module}" '
                f'({_module_key} not in config). Allowing through.'
            )
            # NOTE: Callers should check result.get('warning') and send notifications
            # themselves. should_enter() is a pure decision function — no side effects.

    # --- Same-day re-entry block ---
    if traded_tickers is not None:
        _ticker = signal.get('ticker')
        if _ticker and _ticker in traded_tickers:
            return {
                'enter': False,
                'size': 0.0,
                'reason': f'same_day_reentry ({_ticker})'
            }

    # --- Daily cap gate ---
    room = check_daily_cap(capital, deployed_today)
    if room <= 0:
        return {'enter': False, 'size': 0.0, 'reason': 'daily_cap_reached'}

    # --- Size (Kelly) ---
    raw_size = calculate_position_size(edge, win_prob, capital, vol_ratio, confidence)

    # --- Market impact ceiling (Phase 1: spread proxy) ---
    # Applied AFTER Kelly sizing, BEFORE final min/max cap.
    # yes_ask / yes_bid must be present on the signal dict; skip gracefully if absent.
    market_impact_reason = "skipped_no_spread_data"
    yes_ask = signal.get('yes_ask')
    yes_bid = signal.get('yes_bid')
    impact_size = raw_size
    if yes_ask is not None and yes_bid is not None:
        open_interest = signal.get('open_interest')  # optional Phase 2
        impact_size, market_impact_reason = apply_market_impact_ceiling(
            base_size=raw_size,
            yes_ask=int(yes_ask),
            yes_bid=int(yes_bid),
            open_interest=open_interest,
        )

    # --- Final daily-room cap ---
    size = round(min(impact_size, room), 2)

    if size <= 0:
        return {'enter': False, 'size': 0.0, 'reason': 'kelly_size_zero',
                'market_impact_reason': market_impact_reason}

    # --- Minimum viable trade ---
    min_viable = round(max(5.0, capital * 0.01), 2)
    if size < min_viable:
        return {'enter': False, 'size': 0.0,
                'reason': f'below_min_viable (${size:.2f} < ${min_viable:.2f})',
                'market_impact_reason': market_impact_reason}

    kf = kelly_fraction_for_confidence(confidence)
    _result = {
        'enter':  True,
        'size':   size,
        'reason': f'ok (edge={edge:.3f}, conf={confidence:.2f}, '
                  f'kf={kf:.0%}, kelly=${raw_size:.2f}, impact=${impact_size:.2f}, capped=${size:.2f})',
        'market_impact_reason': market_impact_reason,
    }
    # Propagate warning flag if module had no cap config (so caller can notify)
    if module is not None:
        _module_key = module.upper() + '_DAILY_CAP_PCT'
        if getattr(config, _module_key, None) is None:
            _result['warning'] = f'no_daily_cap_config_for_{module} ({_module_key} missing from config)'
    return _result


# ---------------------------------------------------------------------------
# 4. Add-On Decision
# ---------------------------------------------------------------------------

def should_add(signal: dict, entry_signal: dict,
               current_allocation: float, max_allocation: float = None) -> dict:
    """
    Decide whether to add to an existing position.

    Uses confidence drift relative to the original entry signal to determine
    both *whether* and *how much* to add.

    Args:
        signal:             Latest signal from the module.
        entry_signal:       Signal that triggered the original entry.
        current_allocation: Dollars currently allocated to this position.
        max_allocation:     Maximum total allocation for this position ($).

    Returns:
        {'add': bool, 'size': float, 'reason': str}
    """
    # Resolve max_allocation from config if not explicitly provided by caller
    if max_allocation is None:
        max_allocation = getattr(_cfg, 'MAX_ADD_ALLOCATION', 50.0)

    hours             = signal.get('hours_to_settlement', 0.0)
    confidence_now    = signal.get('confidence', 0.0)
    confidence_entry  = entry_signal.get('confidence', 0.0)
    confidence_delta  = confidence_now - confidence_entry

    # --- Time gate ---
    if hours < MIN_HOURS_ADD:
        return {'add': False, 'size': 0.0,
                'reason': f'too_close_to_settlement ({hours:.2f}h < {MIN_HOURS_ADD}h)'}

    # --- Confidence drift gate ---
    if confidence_delta < 0.10:
        return {'add': False, 'size': 0.0, 'reason': 'drift_too_small'}

    remaining = max_allocation - current_allocation
    if remaining <= 0:
        return {'add': False, 'size': 0.0, 'reason': 'max_allocation_reached'}

    # --- Scale add size by confidence delta ---
    if confidence_delta >= 0.50:
        scale = 1.00       # 100% of remaining
        tier  = 'delta≥0.50'
    elif confidence_delta >= 0.25:
        scale = 0.50       # 50% of remaining
        tier  = 'delta≥0.25'
    else:
        scale = 0.25       # 25% of remaining (0.10–0.25 bucket)
        tier  = 'delta≥0.10'

    size = round(remaining * scale, 2)

    if size <= 0:
        return {'add': False, 'size': 0.0, 'reason': 'computed_size_zero'}

    return {
        'add':    True,
        'size':   size,
        'reason': f'confidence_drift ({tier}, Δ={confidence_delta:.3f}, '
                  f'scale={scale:.0%}, add=${size:.2f})',
    }


# ---------------------------------------------------------------------------
# 5. Exit Decision
# ---------------------------------------------------------------------------

def should_exit(current_bid: float, entry_price: float,
                signal: dict, entry_signal: dict,
                hours_to_settlement: float, module: str) -> dict:
    """
    Decide whether (and how much) of a position to exit.

    Rules are evaluated in strict priority order:

    1. 95¢ rule      — contract near certain; take full profit now.
    2. 70% gain rule — realised gain ≥ 70% of max upside; full exit.
    3. Near-settlement hold — < 30 min to settlement; let it ride.
    4. Reversal rule — edge collapsed vs entry; scale exit by severity.
    5. Default hold.

    Args:
        current_bid:         Current best bid in cents (0–100).
        entry_price:         Price paid at entry in cents (0–100).
        signal:              Latest signal from the module.
        entry_signal:        Signal that triggered the original entry.
        hours_to_settlement: Hours until market settles.
        module:              Module name ('weather'|'crypto') — reserved for
                             future module-specific overrides.

    Returns:
        {'exit': bool, 'fraction': float, 'reason': str}
        fraction: 0.0–1.0 portion of position to close.
    """
    # Rule 1 — 95¢ rule (PRIORITY)
    if current_bid >= 95:
        return {'exit': True, 'fraction': 1.0, 'reason': '95c_rule'}

    # Rule 2 — 70% gain on max upside
    max_upside = 100.0 - entry_price
    if max_upside > 0:
        gain = (current_bid - entry_price) / max_upside
        if gain >= 0.70:
            return {'exit': True, 'fraction': 1.0, 'reason': 'gain_70pct'}

    # Rule 3 — Near-settlement hold (let contract settle)
    if hours_to_settlement < 0.5:
        return {'exit': False, 'fraction': 0.0, 'reason': 'near_settlement_hold'}

    # Rule 4 — Reversal: edge has collapsed vs entry
    entry_edge  = entry_signal.get('edge', 0.0)
    current_edge = signal.get('edge', 0.0)
    reversal = entry_edge - current_edge

    if reversal >= 0.35:
        return {'exit': True,  'fraction': 1.0,  'reason': 'reversal_full'}
    if reversal >= 0.20:
        return {'exit': True,  'fraction': 0.50, 'reason': 'reversal_half'}
    if reversal >= 0.10:
        return {'exit': True,  'fraction': 0.25, 'reason': 'reversal_trim'}

    # Default — hold
    return {'exit': False, 'fraction': 0.0, 'reason': 'hold'}


# ---------------------------------------------------------------------------
# 6. Strategy Summary (for logging / audit)
# ---------------------------------------------------------------------------

def get_strategy_summary() -> dict:
    """
    Return all strategy thresholds and parameters as a dict.

    Intended for startup logging and audit trails so every run records
    exactly what rules were in effect.

    Returns:
        dict of parameter names → values.
    """
    return {
        'kelly_fraction_max':           KELLY_FRACTION,   # 80%+ confidence tier
        'kelly_fraction_tier_80plus':   0.16,
        'kelly_fraction_tier_70_80':    0.14,
        'kelly_fraction_tier_60_70':    0.12,
        'kelly_fraction_tier_50_60':    0.10,
        'kelly_fraction_tier_40_50':    0.07,
        'kelly_fraction_tier_25_40':    0.05,
        'max_position_pct':         getattr(_cfg, 'MAX_POSITION_PCT', 0.01),
        'pct_capital_cap':          getattr(_cfg, 'MAX_POSITION_PCT', 0.01),
        'daily_cap_ratio':          DAILY_CAP_RATIO,
        'min_edge_weather':         MIN_EDGE['weather'],
        'min_edge_crypto':          MIN_EDGE['crypto'],
        'min_edge_geo':             MIN_EDGE['geo'],
        'min_edge_econ':            MIN_EDGE['econ'],
        'min_edge_fed':             MIN_EDGE['fed'],
        'min_confidence':           MIN_CONFIDENCE,
        'min_hours_to_entry':       MIN_HOURS_ENTRY,
        'min_hours_to_add':         MIN_HOURS_ADD,
        'exit_95c_rule_threshold':  95,
        'exit_gain_threshold':      0.70,
        'reversal_full_threshold':  0.35,
        'reversal_half_threshold':  0.20,
        'reversal_trim_threshold':  0.10,
        'add_scale_100pct_delta':   0.50,
        'add_scale_50pct_delta':    0.25,
        'add_scale_25pct_delta':    0.10,
    }


# ---------------------------------------------------------------------------
# 7. Loss Circuit Breaker
# ---------------------------------------------------------------------------

def check_loss_circuit_breaker(capital: float) -> dict:
    """
    Check if today's realized losses exceed the circuit breaker threshold.
    Returns: {'tripped': bool, 'reason': str, 'loss_today': float}

    Threshold: config.LOSS_CIRCUIT_BREAKER_PCT (default 0.05 = 5% of capital)
    """
    threshold_pct = getattr(_cfg, 'LOSS_CIRCUIT_BREAKER_PCT', 0.05)
    threshold_dollars = capital * threshold_pct
    loss_today = 0.0

    from agents.ruppert.env_config import get_paths as _get_paths_cb
    trade_log = _get_paths_cb()['trades'] / f'trades_{date.today().isoformat()}.jsonl'
    if not trade_log.exists():
        return {'tripped': False, 'reason': 'no_trade_log', 'loss_today': 0.0}

    try:
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get('action') != 'exit':
                continue
            pnl = rec.get('realized_pnl')
            if pnl is not None and pnl < 0:
                loss_today += abs(pnl)
    except Exception as e:
        logger.error(f"[CircuitBreaker] Failed to read trade log: {e}. Failing closed.")
        return {'tripped': True, 'reason': f'log_read_error (fail-closed): {e}', 'loss_today': 0.0}

    if loss_today > threshold_dollars:
        return {
            'tripped': True,
            'reason': (f'Loss circuit breaker tripped: ${loss_today:.2f} losses today '
                       f'exceed {threshold_pct:.0%} of capital (${threshold_dollars:.2f})'),
            'loss_today': round(loss_today, 2),
        }

    return {'tripped': False, 'reason': 'within_threshold', 'loss_today': round(loss_today, 2)}


# ---------------------------------------------------------------------------
# __main__ — quick sanity tests
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import os, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 60)
    print("strategy.py - unit tests")
    print("=" * 60)

    CAPITAL = 1000.0

    # ------------------------------------------------------------------
    # 1. calculate_position_size
    # ------------------------------------------------------------------
    print("\n[1] calculate_position_size")

    s1 = calculate_position_size(edge=0.20, win_prob=0.70, capital=CAPITAL, confidence=0.85)
    print(f"  conf=0.85 (kf=0.25): edge=0.20, win_prob=0.70 -> ${s1}")

    s1b = calculate_position_size(edge=0.20, win_prob=0.70, capital=CAPITAL, confidence=0.75)
    print(f"  conf=0.75 (kf=0.20): edge=0.20, win_prob=0.70 -> ${s1b}  (should be ~80% of ${s1})")

    s1c = calculate_position_size(edge=0.20, win_prob=0.70, capital=CAPITAL, confidence=0.65)
    print(f"  conf=0.65 (kf=0.15): edge=0.20, win_prob=0.70 -> ${s1c}  (should be ~60% of ${s1})")

    s1d = calculate_position_size(edge=0.20, win_prob=0.70, capital=CAPITAL, confidence=0.55)
    print(f"  conf=0.55 (kf=0.10): edge=0.20, win_prob=0.70 -> ${s1d}  (should be ~40% of ${s1})")

    s2 = calculate_position_size(edge=0.20, win_prob=0.70, capital=CAPITAL, vol_ratio=2.0, confidence=0.85)
    print(f"  High vol x2 (conf=0.85):  -> ${s2}  (should be ~half of ${s1})")

    s3 = calculate_position_size(edge=0.50, win_prob=0.90, capital=CAPITAL, confidence=0.90)
    print(f"  High edge (conf=0.90):    edge=0.50, win_prob=0.90 -> ${s3}  (should be capped at 1% of capital = $10 on $1000)")

    s4 = calculate_position_size(edge=0.00, win_prob=0.70, capital=CAPITAL, confidence=0.85)
    print(f"  Zero edge:    -> ${s4}  (should be 0.0)")

    # ------------------------------------------------------------------
    # 2. check_daily_cap
    # ------------------------------------------------------------------
    print("\n[2] check_daily_cap")

    r1 = check_daily_cap(total_capital=CAPITAL, deployed_today=0.0)
    print(f"  No deployments: remaining=${r1}  (should be $700.0)")

    r2 = check_daily_cap(total_capital=CAPITAL, deployed_today=600.0)
    print(f"  $600 deployed:  remaining=${r2}  (should be $100.0)")

    r3 = check_daily_cap(total_capital=CAPITAL, deployed_today=750.0)
    print(f"  Over cap:       remaining=${r3}  (should be $0.0)")

    # ------------------------------------------------------------------
    # 3. should_enter
    # ------------------------------------------------------------------
    print("\n[3] should_enter")

    good_signal = {
        'edge': 0.20, 'win_prob': 0.70, 'confidence': 0.80,
        'hours_to_settlement': 6.0, 'module': 'weather', 'vol_ratio': 1.0,
    }
    e1 = should_enter(good_signal, CAPITAL, deployed_today=0.0)
    print(f"  Good weather signal:  {e1}")

    low_edge = {**good_signal, 'edge': 0.05}
    e2 = should_enter(low_edge, CAPITAL, deployed_today=0.0)
    print(f"  Low edge (0.05):      {e2}")

    close_settle = {**good_signal, 'hours_to_settlement': 0.2}
    e3 = should_enter(close_settle, CAPITAL, deployed_today=0.0)
    print(f"  Near settlement:      {e3}")

    cap_hit = should_enter(good_signal, CAPITAL, deployed_today=750.0)
    print(f"  Daily cap hit:        {cap_hit}")

    crypto_ok = {**good_signal, 'module': 'crypto', 'edge': 0.12}
    e4 = should_enter(crypto_ok, CAPITAL, deployed_today=0.0)
    print(f"  Crypto (edge=0.12):   {e4}  (should enter; min=0.12)")

    crypto_low = {**good_signal, 'module': 'crypto', 'edge': 0.08}
    e5 = should_enter(crypto_low, CAPITAL, deployed_today=0.0)
    print(f"  Crypto (edge=0.08):   {e5}  (should skip; min=0.12)")

    # ------------------------------------------------------------------
    # 4. should_add
    # ------------------------------------------------------------------
    print("\n[4] should_add")

    entry_sig = {**good_signal, 'confidence': 0.60}
    sig_drift_small  = {**good_signal, 'confidence': 0.65}   # Δ=0.05 < 0.10
    sig_drift_medium = {**good_signal, 'confidence': 0.75}   # Δ=0.15 → 25%
    sig_drift_large  = {**good_signal, 'confidence': 0.90}   # Δ=0.30 → 50%
    sig_drift_huge   = {**good_signal, 'confidence': 1.00}   # Δ=0.40 → 50%

    a1 = should_add(sig_drift_small,  entry_sig, current_allocation=20.0)
    print(f"  Drift 0.05 (too small):  {a1}")

    a2 = should_add(sig_drift_medium, entry_sig, current_allocation=20.0)
    print(f"  Drift 0.15 (25% scale):  {a2}")

    a3 = should_add(sig_drift_large,  entry_sig, current_allocation=20.0)
    print(f"  Drift 0.30 (50% scale):  {a3}")

    sig_close = {**sig_drift_large, 'hours_to_settlement': 1.0}
    a4 = should_add(sig_close, entry_sig, current_allocation=20.0)
    print(f"  1h to settlement:         {a4}")

    # ------------------------------------------------------------------
    # 5. should_exit
    # ------------------------------------------------------------------
    print("\n[5] should_exit")

    cur_sig   = {**good_signal, 'edge': 0.18}   # similar to entry
    entry_sig2 = {**good_signal, 'edge': 0.20}

    x1 = should_exit(96, 60, cur_sig, entry_sig2, 5.0, 'weather')
    print(f"  bid=96 (95¢ rule):      {x1}")

    x2 = should_exit(94, 60, cur_sig, entry_sig2, 5.0, 'weather')
    # gain = (94-60)/(100-60) = 34/40 = 0.85 ≥ 0.70
    print(f"  bid=94, entry=60 (70%): {x2}")

    x3 = should_exit(70, 60, cur_sig, entry_sig2, 0.2, 'weather')
    print(f"  0.2h to settlement:     {x3}  (near-settlement hold)")

    rev_sig = {**good_signal, 'edge': 0.00}   # reversal = 0.20
    x4 = should_exit(65, 60, rev_sig, entry_sig2, 3.0, 'weather')
    print(f"  Reversal 0.20 (half):   {x4}")

    rev_sig2 = {**good_signal, 'edge': -0.20}  # reversal = 0.40 → full
    x5 = should_exit(65, 60, rev_sig2, entry_sig2, 3.0, 'weather')
    print(f"  Reversal 0.40 (full):   {x5}")

    x6 = should_exit(65, 60, cur_sig, entry_sig2, 5.0, 'weather')
    print(f"  No exit trigger (hold): {x6}")

    # ------------------------------------------------------------------
    # 6. get_strategy_summary
    # ------------------------------------------------------------------
    print("\n[6] get_strategy_summary")
    summary = get_strategy_summary()
    for k, v in summary.items():
        print(f"  {k:<35} = {v}")

    print("\n[OK] All tests complete.")
    sys.exit(0)

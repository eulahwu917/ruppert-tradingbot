# Team Context — Ruppert Quant Trading System
_All sub-agents read this file first before starting any task._
_Last updated: 2026-03-11_

---

## Who We Are

**CEO**: Ruppert (Main agent) — orchestrates, reports to David, approves all logic changes
**SA-1**: Optimizer — **owns the algorithm**. All thresholds, sizing, edge parameters, loss limits are his domain. CEO and David can suggest and push back, but nothing algorithmic changes without Optimizer's recommendation.
**SA-2**: Researcher — quant research, new data sources, new market signals
**SA-3**: Developer — builds and tests code, git commits, never deploys without CEO approval
**SA-4**: QA — reviews all Developer output before CEO approval; reports pass/fail/warnings; never modifies code

**Reporting chain**: Developer builds → QA reviews → CEO approves → David (if real money)

## Workflow Rules (updated 2026-03-12)

- **Batch all work first**: Developer completes ALL queued tasks before sending to QA. QA reviews everything in one pass.
- **One QA pass**: If QA finds issues, send back to Developer to fix everything, then QA reviews again. No serial loops.
- **Git push schedule**:
  - **DEMO**: once per day, every night (EOD). Stage throughout the day, single push at end of session.
  - **LIVE**: Saturdays only, together with the planned LIVE code push. Never pushed mid-week.
- **Algorithm changes**: Optimizer owns all algo parameters. Flow: Optimizer recommends → CEO reviews → David signs off → Developer builds → QA reviews → push. No algo change bypasses Optimizer.
- **LIVE environment (`ruppert-tradingbot-live/`) is treated as production**: Every change — no matter how small — goes through Developer → QA → CEO. CEO must never edit LIVE files directly. No exceptions.
- **When LIVE is ON — no hotfixes**: Small issues go to backlog, fixed in DEMO first, batched, full pipeline, single planned push with pre-flight checklist. Critical issues (financial risk, unexpected trades, crashes) → emergency stop immediately, fix properly before re-activating. LIVE is stable by design.
- **LIVE pushes: Saturdays only.** All LIVE fixes batch through the week, deploy once on Saturday after pre-flight. No mid-week pushes to LIVE. Exception: emergency stop (disable tasks only, no code push).
- **CEO never writes code directly**: CEO scopes, reviews, approves only.

---

## The System

A fully automated Kalshi prediction market trading bot.

**Active modules**: Weather (fully auto) | Crypto (fully auto) | Economics/CPI (manual, David approves)
**Planned modules**: Jobs/Labor | Commodities | Real Estate

**Bot directory**: `C:\Users\David Wu\.openclaw\workspace\kalshi-bot\`
**Dashboard URL**: `http://192.168.4.31:8765`
**Mode**: DEMO (paper trading) until Friday 2026-03-14 review

---

## Architecture

```
Trading Strategy Layer (bot/strategy.py)   ← module-agnostic, owns all $ decisions
    ├── Weather Module (openmeteo_client.py + edge_detector.py)
    └── Crypto Module (crypto_client.py + crypto_scanner.py)
         └── Smart Money (Polymarket wallet tracking)

Position Monitor (bot/position_monitor.py) ← risk management, runs every 5-10 min
Main Loop (main.py)                        ← orchestrates scan cycles
Dashboard (dashboard/api.py + index.html)  ← web UI on port 8765
```

---

## Current Strategy Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Min edge (weather) | 12% | |
| Min edge (crypto) | 12% | |
| Min confidence | 50% | |
| Entry size | min($25, 2.5% capital) | Kelly-weighted |
| Max per ticker | $50 | $25 entry + up to $25 add-on |
| Daily cap | 70% of total capital | 30% always reserved |
| Fractional Kelly | 25% | Research-validated for prediction markets |
| Exit: 95¢ rule | yes_bid or no_bid ≥ 95¢ → sell all | Capital efficiency |
| Exit: 70% gain | Captured ≥ 70% of max profit → sell all | Risk/reward flip |
| Exit: stop-loss | 10-20% reversal trim 25%; 20-35% exit 50%; 35%+ exit 100% | |
| Settlement hold | < 30 min to expiry → hold | Don't exit near settlement |
| Add-on gate | < 2h to settlement → no adds | |

---

## Key Files

| File | Purpose |
|------|---------|
| `bot/strategy.py` | Trading Strategy Layer — ALL sizing/entry/exit logic |
| `openmeteo_client.py` | Weather signal (31-member GEFS ensemble) |
| `edge_detector.py` | Weather edge calculation |
| `crypto_client.py` | Crypto signal + smart money (Polymarket) |
| `crypto_scanner.py` | Crypto market scanner |
| `bot/position_monitor.py` | Risk monitor — 95¢ rule, stop-losses |
| `kalshi_client.py` | Kalshi API wrapper |
| `trader.py` | Trade execution |
| `main.py` | Main scan loop |
| `config.py` | Configuration constants |
| `risk.py` | Legacy risk module (being superseded by strategy.py) |
| `dashboard/api.py` | Dashboard API (port 8765) |
| `logs/trades_YYYY-MM-DD.jsonl` | Trade log |
| `logs/demo_deposits.jsonl` | Demo capital ($400 total) |
| `secrets/kalshi_config.json` | API keys (NEVER hardcode) |

---

## Recent Changes (2026-03-11)

- `bot/strategy.py` — NEW: Trading Strategy Layer (module-agnostic)
- `crypto_client.py` — Student's t-dist, EWMA vol, multi-TF RSI, magnitude momentum, expanded wallets
- `edge_detector.py` — T-market hard NO-only rule removed; replaced with soft confidence prior
- `bot/position_monitor.py` — NEW: Risk monitor with 95¢ rule + stop-loss ladder

---

## Pending / Known Issues

- `scipy` not installed → crypto uses pure-Python t-distribution fallback. Fix: `pip install scipy`
- Polymarket wallet placeholders (5 of 8 are fake) → need real addresses from leaderboard
- Miami NWS grid (MFL 110,37) returns 404 → NWS layer disabled for Miami
- Bias corrections (+2-4°F per city) based on limited backtest data — needs more validation
- `bot/strategy.py` not yet wired into `main.py` — pending
- `bot/position_monitor.py` in DEMO mode only (logs exits, does not execute)
- ECMWF ensemble upgrade deferred to post-Friday

---



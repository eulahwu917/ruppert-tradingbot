# Ruppert — Autonomous Kalshi Trading Bot

Ruppert is a fully automated multi-module prediction market trading system built on [Kalshi](https://kalshi.com). It runs continuous scan cycles, evaluates edges across multiple market types, manages risk, and executes trades autonomously in DEMO mode.

---

## Architecture

### Agent Org Chart

| Agent | Scripts Owned |
|-------|--------------|
| **CEO** | `ruppert_cycle.py` (orchestration only — delegates to Trader) |
| **Strategist** | `bot/strategy.py`, `edge_detector.py`, `optimizer.py` |
| **Data Scientist** | `data_agent.py`, `capital.py`, `dashboard/api.py`, `logger.py` |
| **Data Analyst** | `ghcnd_client.py`, `openmeteo_client.py`, `kalshi_client.py`, `ws_feed.py`, `fetch_smart_money.py`, `bot/wallet_updater.py` |
| **Researcher** | `research_agent.py`, `market_scanner.py` |
| **Trader** | `trader.py`, `post_trade_monitor.py`, `position_monitor.py`, `position_tracker.py`, `main.py`, `crypto_15m.py`, `crypto_client.py`, `crypto_long_horizon.py` |
| **Dev** | Pipeline only — no persistent scripts |
| **QA** | Pipeline only — no persistent scripts |

### Trading Modules
| Module | Markets | Signal Source |
|--------|---------|---------------|
| **Weather** | Temperature markets (KXHIGH*) | NOAA + Open-Meteo ensemble |
| **Crypto** | BTC/ETH/XRP/SOL/DOGE hourly | WS feed + Kraken prices + smart money wallets |
| **Crypto 15m** | BTC/ETH/XRP/DOGE 15-min | TFI + OBI + MACD + OI delta |
| **Economics** | CPI, PCE, Jobs, GDP, Unemployment | FRED data |
| **Fed** | Fed rate decisions | CME FedWatch + signal window |
| **Geo** | Geopolitical markets | GDELT + LLM pipeline |

---

## Infrastructure

- **Scan schedule**: 7AM, 3PM full cycles + crypto-only scans throughout the day (Task Scheduler)
- **WS feed**: Persistent Kalshi WebSocket for real-time price monitoring and sub-second exits
- **Dashboard**: FastAPI at `http://localhost:8765` — live P&L, trade history, positions
- **Exit system**: 95c rule + 70% gain exit, WS-driven (<1s latency)
- **Environment**: `DEMO` (paper trading) — LIVE requires explicit David approval

## Risk Controls
- Global 70% daily deployment cap
- Per-module daily caps (weather 7%, crypto 7%, geo 4%, econ 4%, fed 3%)
- Per-trade max: 1% of capital
- OI cap: max 5% of market open interest
- Quarter-Kelly sizing (25%)
- Same-day re-entry block per ticker
- Loss circuit breaker

---

## Project Structure

```
environments/
  demo/              ← Active trading environment
    ruppert_cycle.py ← Main orchestrator
    config.py        ← Config shim (reads from agents/)
    dashboard/       ← FastAPI dashboard
    audit/           ← Health checks, code audit, QA tooling
    logs/            ← Trade logs, price cache, cycle logs
agents/
  ruppert/
    strategist/      ← strategy.py, edge_detector.py, optimizer.py
    data_scientist/  ← capital.py, logger.py, data_agent.py
    data_analyst/    ← market_cache.py, ws_feed.py, kalshi_client.py
    trader/          ← trader.py, position_monitor.py, position_tracker.py
secrets/             ← API keys (not committed in production)
scripts/             ← ws_feed_watchdog.py, utilities
```

---

## Setup

### Prerequisites
- Python 3.12+
- Windows (Task Scheduler used for scheduling)
- Kalshi API credentials in `secrets/kalshi_config.json`

### Install dependencies
```bash
pip install -r environments/demo/requirements.txt
```

### Run a cycle manually
```powershell
$env:PYTHONPATH = "C:\path\to\workspace"
cd environments/demo
python ruppert_cycle.py check        # position check only (no trades)
python ruppert_cycle.py crypto_only  # crypto scan
python ruppert_cycle.py full         # full scan (all modules)
```

### Start dashboard
```powershell
$env:PYTHONPATH = "C:\path\to\workspace"
$env:RUPPERT_ENV = "demo"
cd environments/demo
python -m uvicorn dashboard.api:app --port 8765 --host 0.0.0.0
```

---

## Current Status
**DEMO** — all trades execute in Kalshi's paper trading environment. Capital: ~$10,000.

LIVE mode requires David's explicit approval and a passing pre-flight scorecard.

---

## Pipeline
All code changes follow: **CEO spec → Data Scientist/Strategist spec → Dev → QA → CEO → David**

LIVE trading requires 3 explicit David confirmations. See `environments/demo/docs/PIPELINE.md`.

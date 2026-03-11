# Ruppert Kalshi Weather Trading Bot

Automated weather market trading bot for Kalshi prediction markets.
Uses NOAA/NWS forecast data to find mispriced weather contracts.

## Setup

### 1. Install Python dependencies
```bash
cd kalshi-bot
pip install -r requirements.txt
```

### 2. Credentials (already configured)
- API key: stored in `../secrets/kalshi_config.json`
- Private key: stored in `../secrets/kalshi_private_key.pem`

### 3. Test the connection
```bash
python main.py --test
```

### 4. Run a single scan (dry run — no real trades)
```bash
python main.py
```

### 5. Run continuously (dry run)
```bash
python main.py --loop
```

### 6. Run with real trades on demo account
```bash
python main.py --live
```

## Risk Controls
- Max position size: $25 per trade
- Max daily exposure: $200
- Minimum edge threshold: 15%
- Kelly criterion position sizing (25% fractional)

## Files
- `main.py` — Entry point, run modes
- `kalshi_client.py` — Kalshi API wrapper
- `noaa_client.py` — NOAA weather data fetcher
- `edge_detector.py` — Compares NOAA vs Kalshi, finds edges
- `trader.py` — Order placement with risk checks
- `risk.py` — Kelly sizing and exposure limits
- `logger.py` — Trade and activity logging
- `config.py` — Configuration and risk settings
- `logs/` — Trade logs (created automatically)

## How It Works
1. Fetches active weather markets from Kalshi
2. For each market, gets NOAA forecast for the same city/date
3. Calculates probability from NOAA data
4. Compares to Kalshi market price
5. If gap > 15%, places a trade in the direction of NOAA's forecast
6. Logs everything to `logs/` folder

## Current Mode
**DEMO** — all trades go to Kalshi's paper trading environment.
To switch to live: change `environment` in `../secrets/kalshi_config.json` to `"production"`
(Only do this after validating the bot works correctly in demo!)

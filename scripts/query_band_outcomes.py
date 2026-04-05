"""
Query Kalshi API for settlement outcomes of 99 ENTER decisions in decisions_band.jsonl.
Uses raw HTTP with the Kalshi API key from secrets/kalshi_config.json.
"""
import json
import sys
import os
import time
import math
import base64
import requests
from pathlib import Path

# Workspace root
WORKSPACE = Path(__file__).parent.parent
SECRETS_FILE = WORKSPACE / 'secrets' / 'kalshi_config.json'

# Load credentials
with open(SECRETS_FILE, 'r') as f:
    cfg = json.load(f)

API_KEY_ID = cfg['api_key_id']
PRIVATE_KEY_PATH = cfg['private_key_path']
ENVIRONMENT = cfg.get('environment', 'demo')
HOST = 'https://api.elections.kalshi.com/trade-api/v2'

# Load private key for RSA signing
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

with open(PRIVATE_KEY_PATH, 'rb') as f:
    private_key = serialization.load_pem_private_key(f.read(), password=None)


def build_auth_headers(method: str, path: str) -> dict:
    timestamp = str(int(time.time() * 1000))
    msg = f"{timestamp}{method}{path}".encode()
    signature = private_key.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode()
    return {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }


def get_market(ticker: str) -> dict:
    """Fetch a single market by ticker, returns dict or {} on failure."""
    path = f'/trade-api/v2/markets/{ticker}'
    headers = build_auth_headers('GET', path)
    url = f"{HOST}/markets/{ticker}"
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('market', {}) or {}
            elif resp.status_code == 404:
                return {'_error': 'not_found', 'ticker': ticker}
            elif resp.status_code == 429:
                delay = float(resp.headers.get('Retry-After', 2.0 ** attempt))
                print(f"  [RateLimit] 429 for {ticker} — waiting {delay:.1f}s")
                time.sleep(delay)
            elif resp.status_code >= 500:
                print(f"  [ServerError] {resp.status_code} for {ticker} — retrying")
                time.sleep(2.0 ** attempt)
            else:
                print(f"  [HTTP {resp.status_code}] for {ticker}: {resp.text[:200]}")
                return {'_error': f'http_{resp.status_code}', 'ticker': ticker}
        except Exception as e:
            print(f"  [RequestError] {e} for {ticker} — retrying")
            time.sleep(2.0 ** attempt)
    return {'_error': 'exhausted', 'ticker': ticker}


# ── Load ENTER decisions ────────────────────────────────────────────────────
DECISIONS_FILE = WORKSPACE / 'environments' / 'demo' / 'logs' / 'decisions_band.jsonl'
decisions = []
with open(DECISIONS_FILE, 'r') as f:
    for line in f:
        row = json.loads(line.strip())
        if row.get('decision') == 'ENTER':
            decisions.append(row)

print(f"Loaded {len(decisions)} ENTER decisions")

# ── Get unique tickers ──────────────────────────────────────────────────────
unique_tickers = list(dict.fromkeys(d['ticker'] for d in decisions))
print(f"Unique tickers: {len(unique_tickers)}")
for t in unique_tickers:
    print(f"  {t}")

# ── Query Kalshi for each unique ticker ─────────────────────────────────────
print(f"\nQuerying Kalshi for {len(unique_tickers)} unique tickers...")
market_cache = {}
for i, ticker in enumerate(unique_tickers):
    print(f"  [{i+1}/{len(unique_tickers)}] {ticker}")
    market = get_market(ticker)
    market_cache[ticker] = market
    # Polite rate limit
    time.sleep(0.3)

# ── Match decisions to outcomes ─────────────────────────────────────────────
print("\n\n=== OUTCOME MATCHING ===\n")

wins = 0
losses = 0
unresolved = 0
errors = 0
brier_sum = 0.0
brier_count = 0

rows = []
for d in decisions:
    ticker = d['ticker']
    side = d.get('side', '').lower()  # 'yes' or 'no'
    model_prob = d.get('model_prob', None)
    edge = d.get('edge', None)
    ts = d.get('ts')
    
    market = market_cache.get(ticker, {})
    
    if '_error' in market:
        status = 'error'
        result = market.get('_error', 'unknown')
        outcome = 'ERROR'
        errors += 1
    else:
        status = market.get('status', 'unknown')
        result = market.get('result', None)
        
        if status == 'finalized' and result in ('yes', 'no'):
            # Determine win/loss
            # side=YES + result=yes → WIN (we bet YES, it resolved YES)
            # side=YES + result=no  → LOSS
            # side=NO  + result=no  → WIN (we bet NO, it resolved NO)
            # side=NO  + result=yes → LOSS
            if side == result:
                outcome = 'WIN'
                wins += 1
            else:
                outcome = 'LOSS'
                losses += 1
            
            # Brier score: (model_prob - actual_outcome)^2
            # model_prob is P(YES). actual = 1 if result=yes, 0 if result=no
            if model_prob is not None:
                actual = 1 if result == 'yes' else 0
                brier_sum += (model_prob - actual) ** 2
                brier_count += 1
        else:
            outcome = 'UNRESOLVED'
            unresolved += 1
    
    rows.append({
        'ticker': ticker,
        'ts': ts,
        'side': side,
        'model_prob': model_prob,
        'edge': edge,
        'status': status,
        'result': result,
        'outcome': outcome,
    })

# ── Print individual results ─────────────────────────────────────────────────
print(f"{'TICKER':<35} {'SIDE':<5} {'M_PROB':<8} {'EDGE':<6} {'STATUS':<12} {'RESULT':<8} {'OUTCOME'}")
print("-" * 100)
for r in rows:
    print(f"{r['ticker']:<35} {str(r['side']):<5} {str(r['model_prob']):<8} {str(r['edge']):<6} {str(r['status']):<12} {str(r['result']):<8} {r['outcome']}")

# ── Summary ─────────────────────────────────────────────────────────────────
total = len(decisions)
resolved = wins + losses
win_rate = wins / resolved if resolved > 0 else None
brier_score = brier_sum / brier_count if brier_count > 0 else None

print("\n\n=== SUMMARY ===\n")
print(f"Total ENTER decisions:    {total}")
print(f"Resolved (finalized):     {resolved}")
print(f"  Wins:                   {wins}")
print(f"  Losses:                 {losses}")
print(f"Unresolved (open/other):  {unresolved}")
print(f"Errors (API/not found):   {errors}")
print(f"")
print(f"Win Rate:                 {win_rate:.1%}" if win_rate is not None else "Win Rate: N/A")
print(f"Brier Score (log-normal): {brier_score:.4f}" if brier_score is not None else "Brier Score: N/A")
print(f"  (lower = better; 0.25 = random, 0.0 = perfect)")
print(f"  Brier count:            {brier_count}")

# ── Save results to file ─────────────────────────────────────────────────────
output_file = WORKSPACE / 'environments' / 'demo' / 'logs' / 'band_outcomes.json'
output = {
    'summary': {
        'total': total,
        'resolved': resolved,
        'wins': wins,
        'losses': losses,
        'unresolved': unresolved,
        'errors': errors,
        'win_rate': win_rate,
        'brier_score': brier_score,
        'brier_count': brier_count,
    },
    'decisions': rows,
    'market_cache': {k: {fk: fv for fk, fv in v.items() if fk not in ('subtitle', 'open_time', 'close_time', 'expected_expiration_time', 'expiration_time')} for k, v in market_cache.items()},
}
with open(output_file, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {output_file}")

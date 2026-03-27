"""Fetch Polymarket smart money signal — reads title/outcome directly from positions API."""
import sys, requests, json, time, os
from pathlib import Path
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}

WALLETS_FILE = Path(__file__).parent / 'logs' / 'smart_money_wallets.json'
STALE_THRESHOLD_HOURS = 25

CRYPTO_KW = ['bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol', 'xrp', 'ripple', 'doge']


def _load_wallets() -> dict:
    """Load wallets from logs/smart_money_wallets.json written by wallet_updater."""
    if not WALLETS_FILE.exists():
        print('WARNING: smart_money_wallets.json not found — run wallet_updater first')
        return {}
    try:
        data = json.loads(WALLETS_FILE.read_text(encoding='utf-8'))
        raw = data.get('wallets', [])
        if not raw or not isinstance(raw, list):
            print('WARNING: smart_money_wallets.json has no wallets list')
            return {}

        # Staleness check
        updated_at = data.get('updated_at', '')
        if updated_at:
            try:
                updated_dt = datetime.fromisoformat(updated_at)
                age_hours = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
                if age_hours > STALE_THRESHOLD_HOURS:
                    print(f'WARNING: smart_money: wallet list is stale (>{STALE_THRESHOLD_HOURS}h), consider re-running wallet_updater')
            except Exception:
                pass

        return {addr[:8]: addr for addr in raw}
    except Exception as e:
        print(f'WARNING: failed to read smart_money_wallets.json: {e}')
        return {}


WALLETS = _load_wallets()

if not WALLETS:
    print('smart_money: no wallets available — returning neutral signal')
    result = {
        'direction':        'neutral',
        'bull_pct':         0.5,
        'up_value':         0.0,
        'down_value':       0.0,
        'traders_sampled':  0,
        'active_positions': 0,
        'positions':        [],
        'timestamp':        int(time.time()),
        'note':             'Neutral — no wallet list available',
    }
    out = Path('logs/crypto_smart_money.json')
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    print(f'Saved neutral to {out}')
    sys.exit(0)

up_value   = 0.0
down_value = 0.0
positions_detail = []

for name, wallet in WALLETS.items():
    try:
        r = requests.get(
            f'https://data-api.polymarket.com/positions?user={wallet}&limit=100',
            headers=HEADERS, timeout=8
        )
        if r.status_code != 200:
            print(f'{name}: HTTP {r.status_code}')
            continue

        positions = r.json()
        crypto = [p for p in positions if any(k in p.get('title','').lower() for k in CRYPTO_KW)]
        print(f'{name}: {len(positions)} positions total, {len(crypto)} crypto')

        for p in crypto:
            title   = p.get('title', '')
            outcome = p.get('outcome', '').lower()   # "up" or "down"
            cur_val = p.get('currentValue', 0)
            cur_price = p.get('curPrice', 0)

            # Skip near-zero value positions (essentially expired/losing side)
            if cur_val < 1.0:
                continue

            is_bullish = outcome in ('up', 'yes', 'higher', 'above')
            is_bearish = outcome in ('down', 'no', 'lower', 'below')

            if is_bullish:
                up_value += cur_val
            elif is_bearish:
                down_value += cur_val

            direction = 'UP' if is_bullish else 'DOWN' if is_bearish else '?'
            print(f'  [{name}] {title[:55]} | {direction} | val=${cur_val:.2f}')
            positions_detail.append({
                'trader': name,
                'title': title,
                'outcome': outcome,
                'direction': 'bullish' if is_bullish else 'bearish',
                'value': round(cur_val, 2),
            })

    except Exception as e:
        print(f'{name}: ERROR {e}')

# Compute aggregate signal
total = up_value + down_value
bull_pct = up_value / total if total > 0 else 0.5

if bull_pct >= 0.60:
    signal = 'bullish'
elif bull_pct <= 0.40:
    signal = 'bearish'
else:
    signal = 'neutral'

print(f'\n=== SIGNAL: {signal.upper()} | bull {bull_pct:.0%} | up=${up_value:.0f} down=${down_value:.0f} ===')
print(f'    Active crypto positions: {len(positions_detail)}')

result = {
    'direction':        signal,
    'bull_pct':         round(bull_pct, 3),
    'up_value':         round(up_value, 2),
    'down_value':       round(down_value, 2),
    'traders_sampled':  len(WALLETS),
    'active_positions': len(positions_detail),
    'positions':        positions_detail[:20],
    'timestamp':        int(time.time()),
    'note':             f'{signal.capitalize()} — ${up_value:.0f} up vs ${down_value:.0f} down across top traders',
}

out = Path('logs/crypto_smart_money.json')
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
print(f'Saved to {out}')

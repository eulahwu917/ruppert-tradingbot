"""
Configuration loader — reads credentials from secrets folder.
Never hardcodes API keys.
"""
import json
import os

# Paths
SECRETS_DIR = os.path.join(os.path.dirname(__file__), '..', 'secrets')
CONFIG_FILE = os.path.join(SECRETS_DIR, 'kalshi_config.json')

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

# Risk settings — Weather / Economics
MAX_POSITION_SIZE = 25.00      # Max $ per single trade
MAX_DAILY_EXPOSURE = 200.00    # Max $ total per day (weather + econ)
MIN_EDGE_THRESHOLD = 0.12      # Min edge (12%) to trigger a trade
MIN_MARKET_LIQUIDITY = 100.00  # Min $ volume in market to trade

# Risk settings — Crypto (separate budget, FULLY AUTO like weather)
CRYPTO_MAX_POSITION_SIZE = 25.00   # Max $ per single crypto trade
CRYPTO_MAX_DAILY_EXPOSURE = 200.00 # Separate $200 daily budget for crypto
CRYPTO_MIN_EDGE_THRESHOLD = 0.12   # 12% min edge (consistent with weather)

# Auto-trade settings
# Weather + Crypto = fully autonomous (no notification, no approval)
# Geo + Gaming + Economics = manual approval required
WEATHER_AUTO_TRADE  = True   # Bot executes without asking
CRYPTO_AUTO_TRADE   = True   # Bot executes without asking
GEO_AUTO_TRADE      = False  # David approves
GAMING_AUTO_TRADE   = False  # David approves
ECONOMICS_AUTO_TRADE = True  # Auto-execute high-conviction trades (edge >= ECON_HIGH_CONVICTION_EDGE)
ECON_HIGH_CONVICTION_EDGE = 0.20  # 20%+ edge = auto-execute; below = still alert David

# Bot settings
CHECK_INTERVAL_HOURS = 6       # How often to scan for opportunities
SAME_DAY_SKIP_AFTER_HOUR = 14  # skip same-day weather markets after 2pm local

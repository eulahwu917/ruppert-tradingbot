"""
env_config.py — Environment resolver for Ruppert agents.

Agents import paths from here. At runtime:
  1. Check RUPPERT_ENV environment variable
  2. If not set, default to 'demo'
  3. Resolve all paths relative to that environment root

Usage in agent code:
    from agents.ruppert.env_config import get_paths
    paths = get_paths()
    truth_dir = paths['truth']
    logs_dir = paths['logs']
"""

import os
import json
from pathlib import Path

# Workspace root (fixed)
WORKSPACE_ROOT = Path(os.environ.get(
    'OPENCLAW_WORKSPACE',
    Path.home() / '.openclaw' / 'workspace'
))

ENVIRONMENTS_DIR = WORKSPACE_ROOT / 'environments'
SECRETS_DIR = WORKSPACE_ROOT / 'secrets'

# Default environment
_DEFAULT_ENV = 'demo'


def get_current_env() -> str:
    """
    Return the active environment name.
    Priority:
      1. RUPPERT_ENV environment variable
      2. 'demo' (default)
    """
    return os.environ.get('RUPPERT_ENV', _DEFAULT_ENV)


def get_env_root(env: str = None) -> Path:
    """Get the root path for an environment."""
    env = env or get_current_env()
    return ENVIRONMENTS_DIR / env


def is_live_enabled() -> bool:
    """
    Check if live trading is explicitly enabled.
    Reads environments/live/mode.json → {"enabled": true|false}
    Default: False (read-only)
    """
    live_mode_file = ENVIRONMENTS_DIR / 'live' / 'mode.json'
    if not live_mode_file.exists():
        return False
    try:
        data = json.loads(live_mode_file.read_text(encoding='utf-8'))
        return data.get('enabled', False) is True
    except Exception:
        return False


def get_paths(env: str = None) -> dict:
    """
    Return a dict of all standard paths for the given environment.
    Agents should use this to locate logs, truth files, reports, etc.
    """
    env = env or get_current_env()
    root = get_env_root(env)

    return {
        'env': env,
        'root': root,
        'logs': root / 'logs',
        'raw': root / 'logs' / 'raw',
        'trades': root / 'logs' / 'trades',
        'truth': root / 'logs' / 'truth',
        'audits': root / 'logs' / 'audits',
        'proposals': root / 'logs' / 'proposals',
        'reports': root / 'reports',
        'memory': root / 'memory',
        'config': root / 'config',
        'specs': root / 'specs',
        'mode_file': root / 'mode.json',
        # Shared secrets (workspace-level)
        'secrets': SECRETS_DIR,
    }


def get_both_truth_paths() -> dict:
    """
    Return truth paths for BOTH environments.
    Used by Data Scientist for cross-environment comparison.
    """
    return {
        'demo': ENVIRONMENTS_DIR / 'demo' / 'logs' / 'truth',
        'live': ENVIRONMENTS_DIR / 'live' / 'logs' / 'truth',
    }


def is_dry_run() -> bool:
    """
    Check if current environment is in dry-run mode.
    - demo → always dry run
    - live → dry run unless enabled=true
    """
    env = get_current_env()
    if env == 'demo':
        return True
    if env == 'live':
        return not is_live_enabled()
    return True  # default safe


def require_live_enabled():
    """
    Gate function — call before any live write operation.
    Raises RuntimeError if live is not enabled.
    """
    if get_current_env() == 'live' and not is_live_enabled():
        raise RuntimeError(
            "LIVE TRADING DISABLED. "
            "Set 'enabled': true in environments/live/mode.json to proceed."
        )

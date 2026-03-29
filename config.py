"""
config.py - Workspace-level config shim for agents.ruppert.* modules.
Auto-detects RUPPERT_ENV and loads config from the appropriate environment.

This file sits at workspace root so 'import config' works when CWD=workspace.
Agents and ruppert_cycle.py import from here; actual config lives in environments/.
"""
import os
import sys
from pathlib import Path

# Determine active environment
_ENV = os.environ.get('RUPPERT_ENV', 'demo')
_WORKSPACE = Path(__file__).parent
_ENV_ROOT = _WORKSPACE / 'environments' / _ENV

# Add env root to path so env-specific config.py is importable
if str(_ENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENV_ROOT))

# Now import everything from the env-specific config
# Use exec to avoid circular import issues
_env_config_path = _ENV_ROOT / 'config.py'
if _env_config_path.exists():
    with open(_env_config_path, 'r', encoding='utf-8') as _f:
        exec(compile(_f.read(), str(_env_config_path), 'exec'), globals())
else:
    raise ImportError(
        f"No config.py found for environment '{_ENV}' at {_env_config_path}. "
        f"Check RUPPERT_ENV environment variable."
    )

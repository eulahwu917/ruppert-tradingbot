# ARCHIVED: 2026-03-29 per CEO spec CEO-L3
# run_exit_scan() was deprecated in main.py. Exits are handled by ws_feed.py + post_trade_monitor.py.
# This file is read-only historical reference. Do not import or call from production code.
__all__ = []


def run_exit_scan(dry_run=True):
    """
    DEPRECATED: Exits are owned by ws_feed.py (position_tracker) + post_trade_monitor.py.
    This function is a no-op stub kept to avoid ImportError from any external caller.
    Do not call this function. It will be removed in a future cleanup.
    """
    import warnings
    warnings.warn(
        "run_exit_scan() is deprecated and is a no-op. Exits are handled by WS feed / position_tracker.",
        DeprecationWarning, stacklevel=2,
    )
    log_activity("[ExitScan] DEPRECATED run_exit_scan() called — no-op. Check caller.")
    if not dry_run:
        raise RuntimeError("run_exit_scan() is deprecated and must not run in live mode.")

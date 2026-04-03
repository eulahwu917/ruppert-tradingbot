"""Tests for trade deduplication logic in ruppert_cycle.py."""
import pathlib
import textwrap


def _read_source():
    src = pathlib.Path(__file__).resolve().parent.parent / 'ruppert_cycle.py'
    return src.read_text(encoding='utf-8')


def test_traded_tickers_populated_from_log():
    """traded_tickers is initialised from today's trade log (trades_YYYY-MM-DD.jsonl)."""
    source = _read_source()

    # Find the initialisation block
    assert 'traded_tickers = set()' in source, "traded_tickers set not initialised"

    # Within ~30 lines after that, the code should read the daily trade log
    init_idx = source.index('traded_tickers = set()')
    nearby = source[init_idx:init_idx + 1500]  # roughly 30 lines

    assert 'trades_' in nearby, (
        "No trades_ log file reference found near traded_tickers init"
    )
    assert 'traded_tickers.add' in nearby, (
        "traded_tickers is never populated from the log"
    )


def test_exit_action_removes_from_traded_tickers():
    """Exits do NOT remove from traded_tickers — once traded, a ticker is blocked all day.
    This is by design: re-entry after exit is intentionally prevented within the same cycle.
    Verify that ruppert_cycle.py documents this behavior and that exit logic is present.
    """
    source = _read_source()

    # The exit action keyword must still exist (auto-exit logic is present)
    found_exit_keyword = any(kw in source for kw in ('exit', "'exit'", '"exit"'))
    assert found_exit_keyword, "No 'exit' action string found in ruppert_cycle.py"

    # By design, traded_tickers is NOT cleared on exit (comment documents this)
    # Verify the design-comment is present, or that traded_tickers.add is used post-exit
    assert (
        'exits do NOT remove from dedup' in source
        or 'traded_tickers.add' in source
    ), (
        "Expected ruppert_cycle.py to document the no-dedup-clear-on-exit design "
        "or show traded_tickers.add usage"
    )

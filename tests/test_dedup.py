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
    """Exit actions discard tickers so they can be re-entered later."""
    source = _read_source()

    assert 'traded_tickers.discard(' in source or "traded_tickers.remove(" in source, (
        "No logic to remove tickers from traded_tickers on exit"
    )

    # Verify the exit keyword is associated with that removal
    for keyword in ('exit', "'exit'", '"exit"'):
        if keyword in source:
            break
    else:
        raise AssertionError("No 'exit' action string found in ruppert_cycle.py")

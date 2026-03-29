import pytest

@pytest.fixture
def sample_market():
    return {
        'ticker': 'KXHIGHNY-26MAR27-T62',
        'yes_ask': 15, 'no_ask': 87,
        'yes_bid': 14, 'no_bid': 86,
        'status': 'active',
        'close_time': '2026-03-27T20:00:00Z',
    }

@pytest.fixture
def sample_signal():
    return {
        'edge': 0.25, 'win_prob': 0.75, 'confidence': 0.70,
        'hours_to_settlement': 18.0, 'module': 'weather',
        'vol_ratio': 1.0, 'yes_ask': 15, 'yes_bid': 14,
        'open_position_value': 0.0,
    }

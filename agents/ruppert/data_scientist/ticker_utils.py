"""ticker_utils.py — Shared ticker classification utilities.

Extracted from environments/demo/dashboard/api.py to avoid circular imports.
"""
import re
from datetime import date, datetime, timedelta


def is_settled_ticker(ticker: str) -> bool:
    """Return True if ticker contains a past date/time (market already settled).

    Handles both date-only (26MAR11) and date+time (26MAR1117 or 26MAR111300) formats.
    Uses EDT (UTC-4) for intraday comparison, matching the existing dashboard logic.
    """
    months = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
    }
    today = date.today()
    parts = ticker.upper().split('-')
    for part in parts:
        m = re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2}|\d{4})?$', part)
        if m:
            yy, mon, dd = m.group(1), m.group(2), m.group(3)
            month_num = months.get(mon)
            if not month_num:
                continue
            try:
                mkt_date = date(2000 + int(yy), month_num, int(dd))
                if mkt_date < today:
                    return True
                if mkt_date == today and m.group(4):
                    time_str = m.group(4)
                    now_edt = datetime.utcnow() - timedelta(hours=4)
                    if len(time_str) == 2:
                        settle_edt = datetime(mkt_date.year, mkt_date.month, mkt_date.day,
                                              int(time_str))
                    else:
                        settle_edt = datetime(mkt_date.year, mkt_date.month, mkt_date.day,
                                              int(time_str[:2]), int(time_str[2:]))
                    if now_edt >= settle_edt:
                        return True
            except Exception:
                pass
    return False

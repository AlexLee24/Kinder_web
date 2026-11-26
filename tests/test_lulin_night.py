"""Daily Trigger bar: tonight's astronomical night at Lulin (app/services/lab_calendar.lulin_night)."""
from datetime import date

from app.services import lab_calendar as cal


def test_astronomical_night_sits_inside_sunset_and_sunrise():
    n = cal.lulin_night(date(2026, 11, 26))
    assert n['sunset'] < n['dark_start'] < n['dark_end'] < n['sunrise']
    assert n['sunset'].date() == date(2026, 11, 26) and n['sunrise'].date() == date(2026, 11, 27)
    # late November at 23.5° N: twilight ~75 min, sunset ~17:10 UTC+8
    assert 60 <= (n['dark_start'] - n['sunset']).total_seconds() / 60 <= 90
    assert '17:00' <= n['sunset'].strftime('%H:%M') <= '17:20'
    assert n['sunset'] == cal.lulin_sunset(date(2026, 11, 26))      # the same sunset as the duty push

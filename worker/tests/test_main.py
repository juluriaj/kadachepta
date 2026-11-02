import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from kc_worker.__main__ import stop_time  # noqa: E402


def test_the_stop_time_is_the_next_time_the_clock_shows_it():
    evening = datetime(2026, 11, 1, 19, 30)
    assert stop_time("06:00", evening) == datetime(2026, 11, 2, 6, 0)  # overnight: tomorrow morning
    assert stop_time("06:00", datetime(2026, 11, 2, 3, 15)) == datetime(2026, 11, 2, 6, 0)  # after midnight
    assert stop_time("19:30", evening) == datetime(2026, 11, 2, 19, 30)  # exactly now: a day later, not at once
    assert stop_time("", evening) is None
    for bad in ("6", "25:00", "6pm"):
        with pytest.raises(ValueError):
            stop_time(bad, evening)

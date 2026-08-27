"""Tests for Jalali calendar conversion."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("LLM_API_KEY", "test-key")

from app.utils.jalali import (
    gregorian_to_jalali,
    jalali_to_gregorian,
    is_leap_jalali,
    jalali_month_length,
    format_jalali,
)


def test_known_conversions():
    # Known dates from jalaali-js tests
    # 2023-03-21 = 1402-01-01
    assert gregorian_to_jalali(2023, 3, 21) == (1402, 1, 1)
    assert gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1)
    # 2025-08-27 should be 1404-06-05 (approx)
    jy, jm, jd = gregorian_to_jalali(2025, 8, 27)
    assert jy == 1404
    # Check roundtrip
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    assert (gy, gm, gd) == (2025, 8, 27)


def test_roundtrip_random():
    for gy, gm, gd in [(2000, 1, 1), (2020, 6, 15), (1990, 12, 31), (2010, 2, 28)]:
        jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
        gy2, gm2, gd2 = jalali_to_gregorian(jy, jm, jd)
        assert (gy, gm, gd) == (gy2, gm2, gd2)


def test_leap_year():
    # 1403 is leap (Esfand 30 days)
    assert is_leap_jalali(1403) is True
    assert jalali_month_length(1403, 12) == 30
    # 1402 is not leap
    assert is_leap_jalali(1402) is False
    assert jalali_month_length(1402, 12) == 29


def test_month_length():
    assert jalali_month_length(1404, 1) == 31
    assert jalali_month_length(1404, 6) == 31
    assert jalali_month_length(1404, 7) == 30
    assert jalali_month_length(1404, 11) == 30


def test_format():
    s = format_jalali(1404, 6, 5, with_weekday=False)
    assert "۵" in s and "شهریور" in s and "۱۴۰۴" in s

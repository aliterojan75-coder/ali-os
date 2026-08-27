"""Jalali (Shamsi / Persian) calendar conversion — dependency-free.

Implementation based on jalaali-python (which ports jalaali-js) —
algorithm by Kazimierz M. Borkowski.

Provides gregorian_to_jalali and jalali_to_gregorian with Persian formatting helpers.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Tuple

# Tehran timezone: UTC+3:30, no DST
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
JALALI_MONTHS_SHORT = [
    "فرو", "ارد", "خرد", "تیر", "مرد", "شهر",
    "مهر", "آبا", "آذر", "دی", "بهم", "اسف",
]

JALALI_WEEKDAYS = [
    "شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه",
]
_GREG_TO_JALALI_WEEKDAY = [2, 3, 4, 5, 6, 0, 1]

FA_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"]


def fa_num(n) -> str:
    if n is None:
        return "—"
    return str(n).translate(str.maketrans("0123456789", "".join(FA_DIGITS)))


def _div(a: int, b: int) -> int:
    return int(a / b)


def _mod(a: int, b: int) -> int:
    return a - _div(a, b) * b


_BREAKS = [
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
    1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178,
]


def _jal_cal(jy: int):
    bl = len(_BREAKS)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0

    if jy < jp or jy >= _BREAKS[bl - 1]:
        raise ValueError(f"Invalid Jalaali year {jy}")

    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j = leap_j + _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm

    n = jy - jp
    leap_j = leap_j + _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1

    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g

    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4

    return {"leap": leap, "gy": gy, "march": march}


def _is_leap_jalali(jy: int) -> bool:
    return _jal_cal(jy)["leap"] == 0


def _g2d(gy: int, gm: int, gd: int) -> int:
    d = _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) + _div(153 * _mod(gm + 9, 12) + 2, 5) + gd - 34840408
    d = d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752
    return d


def _d2g(jdn: int) -> Tuple[int, int, int]:
    j = 4 * jdn + 139361631 + _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(_mod(j, 1461), 4) * 5 + 308
    gd = _div(_mod(i, 153), 5) + 1
    gm = _mod(_div(i, 153), 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def _j2d(jy: int, jm: int, jd: int) -> int:
    r = _jal_cal(jy)
    return _g2d(r["gy"], 3, r["march"]) + (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1


def _d2j(jdn: int) -> Tuple[int, int, int]:
    gy, _, _ = _d2g(jdn)
    jy = gy - 621
    r = _jal_cal(jy)
    jdn1f = _g2d(gy, 3, r["march"])
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            jm = 1 + _div(k, 31)
            jd = _mod(k, 31) + 1
            return jy, jm, jd
        else:
            k -= 186
    else:
        jy -= 1
        k += 179
        if r["leap"] == 1:
            k += 1
    jm = 7 + _div(k, 30)
    jd = _mod(k, 30) + 1
    return jy, jm, jd


# ── Public API ───────────────────────────────────────────────────────────────

def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    return _d2j(_g2d(gy, gm, gd))


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> Tuple[int, int, int]:
    return _d2g(_j2d(jy, jm, jd))


def is_leap_jalali(jy: int) -> bool:
    return _is_leap_jalali(jy)


def jalali_month_length(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap_jalali(jy) else 29


def now_tehran() -> datetime:
    return datetime.now(TEHRAN_TZ)


def today_jalali() -> Tuple[int, int, int]:
    dt = now_tehran()
    return gregorian_to_jalali(dt.year, dt.month, dt.day)


def timestamp_to_jalali(ts: float) -> Tuple[int, int, int]:
    dt = datetime.fromtimestamp(ts, TEHRAN_TZ)
    return gregorian_to_jalali(dt.year, dt.month, dt.day)


def jalali_weekday(jy: int, jm: int, jd: int) -> int:
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    from datetime import date
    try:
        wd = date(gy, gm, gd).weekday()
    except ValueError:
        wd = 0
    return _GREG_TO_JALALI_WEEKDAY[wd]


def format_jalali(jy: int, jm: int, jd: int, *, with_weekday: bool = True, with_month_name: bool = True) -> str:
    parts = []
    if with_weekday:
        try:
            wd = jalali_weekday(jy, jm, jd)
            parts.append(JALALI_WEEKDAYS[wd])
        except Exception:
            pass
    parts.append(fa_num(jd))
    if with_month_name:
        if 1 <= jm <= 12:
            parts.append(JALALI_MONTHS[jm - 1])
        else:
            parts.append(fa_num(jm))
    else:
        parts.append(fa_num(jm))
    parts.append(fa_num(jy))
    return " ".join(parts)


def format_timestamp_fa(ts: float, *, with_weekday: bool = True) -> str:
    try:
        jy, jm, jd = timestamp_to_jalali(ts)
        return format_jalali(jy, jm, jd, with_weekday=with_weekday)
    except Exception:
        return ""


def jalali_today_str() -> str:
    jy, jm, jd = today_jalali()
    return format_jalali(jy, jm, jd, with_weekday=True)


def gregorian_today_str() -> str:
    dt = now_tehran()
    return dt.strftime("%Y-%m-%d")


def parse_due_hint_to_timestamp(hint: str | None) -> float | None:
    if not hint:
        return None
    hint = hint.strip().lower()
    now = now_tehran()
    if any(w in hint for w in ["امروز", "today"]):
        return now.replace(hour=23, minute=59, second=0, microsecond=0).timestamp()
    if "فردا" in hint or "tomorrow" in hint:
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=23, minute=59, second=0, microsecond=0).timestamp()
    if "این هفته" in hint or "this week" in hint:
        wd = now.weekday()
        days_ahead = (4 - wd) % 7
        if days_ahead == 0:
            days_ahead = 7
        end_week = now + timedelta(days=days_ahead)
        return end_week.replace(hour=23, minute=59, second=0, microsecond=0).timestamp()
    if "هفته بعد" in hint or "next week" in hint:
        end_next = now + timedelta(days=14)
        return end_next.replace(hour=23, minute=59, second=0, microsecond=0).timestamp()
    return None

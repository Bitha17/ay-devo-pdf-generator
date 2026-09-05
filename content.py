"""Helpers for turning a parsed devotion into web-publishable metadata."""
import re
from datetime import date

ID_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
}


def parse_id_date(date_str):
    """'Minggu, 25 Januari 2026' -> date(2026, 1, 25); None if unparseable."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", date_str or "")
    if not m:
        return None
    month = ID_MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def slugify(text):
    """'Week 4 Jan 2026' -> 'week-4-jan-2026'."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def make_slug(week, month):
    """Build the stable URL slug from the parser's week + month fields."""
    base = f"{week} {month}".strip()
    return slugify(base) or "devotion"


def extract_title(raw_text):
    """The weekly theme sits after ' - ' on the first content line, e.g.
    'Week 4 Jan 2026 - Kabar Baik untuk Orang Miskin'.
    Returns the theme, or '' if not found."""
    for line in raw_text.splitlines():
        line = line.strip().lstrip("﻿")
        if not line:
            continue
        if " - " in line:
            return line.split(" - ", 1)[1].strip()
        return ""
    return ""


ID_MONTHS_NAME = {v: k.capitalize() for k, v in ID_MONTHS.items()}

DAY_NAMES_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def format_id_date(d, day_name=None):
    """date(2026, 9, 7) -> '7 September 2026' (or 'Senin, 7 September 2026'
    when day_name is given), matching the AY parser's date field format."""
    text = f"{d.day} {ID_MONTHS_NAME[d.month]} {d.year}"
    return f"{day_name}, {text}" if day_name else text


def format_period(start, end):
    """Two dates -> the AY-style period string, e.g. '7-13 September 2026',
    '29 September - 5 Oktober 2026', or '29 Desember 2026 - 4 Januari 2027'."""
    if start.year == end.year:
        if start.month == end.month:
            return f"{start.day}-{end.day} {ID_MONTHS_NAME[start.month]} {start.year}"
        return (f"{start.day} {ID_MONTHS_NAME[start.month]} - "
                f"{end.day} {ID_MONTHS_NAME[end.month]} {start.year}")
    return (f"{start.day} {ID_MONTHS_NAME[start.month]} {start.year} - "
            f"{end.day} {ID_MONTHS_NAME[end.month]} {end.year}")


def make_slug_umum(start_date):
    """Stable URL slug for a Umum week, keyed by its start date."""
    return f"umum-{start_date.isoformat()}"

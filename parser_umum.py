"""Parser for the Umum division's weekly devotion .docx.

Unlike the AY .txt (which carries explicit field labels like THEME:/M1:/M4:),
the Umum source is a plain Word doc: a title paragraph, then one block per day
made of a day name, a theme, a bible reference, and three labelled sections
(Konteks / Firman Kristus / Pertanyaan). It has no per-day calendar dates —
the admin supplies the week's start date and days are dated in document order.

Bold/italic runs in Konteks, Firman Kristus and Pertanyaan are preserved as
inline <b>/<i> tags — the same convention the AY .txt uses — so both the PDF
(reportlab's Paragraph markup) and the web view (via the `markup` filter)
render them.
"""
from datetime import timedelta

from content import DAY_NAMES_ID, ID_MONTHS_NAME, format_id_date, format_period
from docx_utils import extract_docx_paragraphs

_DAY_NAMES_LOWER = {d.lower() for d in DAY_NAMES_ID}
_HEADINGS = {"konteks", "firman kristus", "pertanyaan"}


def _split_day_blocks(paragraphs):
    """Split paragraphs (after the title) into one list per day, each
    starting with the day-name paragraph."""
    blocks = []
    current = None
    for para in paragraphs:
        if para["plain"].lower() in _DAY_NAMES_LOWER:
            current = [para]
            blocks.append(current)
        elif current is not None:
            current.append(para)
    return blocks


def _collect_until(paras, i, stop_headings):
    """From paras[i:], collect non-empty paragraphs' rich text until a
    heading in stop_headings (or the end) is hit. Returns (joined_text, next_index)."""
    collected = []
    while i < len(paras) and paras[i]["plain"].lower() not in stop_headings:
        if paras[i]["plain"]:
            collected.append(paras[i]["rich"])
        i += 1
    return "\n".join(collected), i


def _parse_day_block(block, day_date):
    lines = block[1:]  # drop the day-name paragraph itself
    i = 0

    theme, verse = "", ""
    non_empty = [l for l in lines if l["plain"]]
    if non_empty:
        theme = non_empty[0]["plain"]
    if len(non_empty) > 1:
        verse = non_empty[1]["plain"]

    # Skip ahead to the "Konteks" heading.
    while i < len(lines) and lines[i]["plain"].lower() != "konteks":
        i += 1
    i += 1  # past the heading itself
    context, i = _collect_until(lines, i, _HEADINGS)

    while i < len(lines) and lines[i]["plain"].lower() != "firman kristus":
        i += 1
    i += 1
    firman_kristus, i = _collect_until(lines, i, _HEADINGS)

    while i < len(lines) and lines[i]["plain"].lower() != "pertanyaan":
        i += 1
    i += 1
    questions_text, i = _collect_until(lines, i, _HEADINGS)
    questions = [q for q in questions_text.split("\n") if q.strip()]

    return {
        "date": format_id_date(day_date, block[0]["plain"]),
        "theme": theme,
        "verse": verse,
        "context": context,
        "firman_kristus": firman_kristus,
        "questions": questions,
    }


def parse_docx_file(path, start_date):
    """Parse the Umum .docx into the same shape the reader/PDF expect:
    {title, week, month, period, days: [...]}. `start_date` is the Monday
    (or otherwise first day) of the week, supplied by the admin."""
    paragraphs = extract_docx_paragraphs(path)
    non_empty = [p for p in paragraphs if p["plain"]]
    title = non_empty[0]["plain"] if non_empty else ""

    blocks = _split_day_blocks(paragraphs)
    days = [
        _parse_day_block(block, start_date + timedelta(days=i))
        for i, block in enumerate(blocks)
    ]

    end_date = start_date + timedelta(days=max(len(blocks) - 1, 0))
    period = format_period(start_date, end_date)
    month = f"{ID_MONTHS_NAME[start_date.month]} {start_date.year}"

    return {"title": title, "week": "", "month": month, "period": period, "days": days}

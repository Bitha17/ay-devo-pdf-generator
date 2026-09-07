"""Parser for the Umum division's weekly devotion .docx.

Unlike the AY .txt (which carries explicit field labels like THEME:/M1:/M4:),
the Umum source is a plain Word doc: one block per day made of a day header,
a theme, a bible reference, and three labelled sections (Konteks / Firman
Kristus / Pertanyaan). Two day-header styles are supported:

  - Bare day name ("Senin"), with no per-day dates of its own — the admin
    supplies the week's start date and days are dated in document order.
    A dedicated title paragraph normally precedes the first day.
  - "Senin | 7 September 2026" — the day's own explicit date, so no start
    date is needed. This style is also commonly preceded by a one-line
    author byline for each day (e.g. "Thrasya"), isolated by a blank line
    on both sides; there's no dedicated week-title paragraph.

Bold/italic runs in Konteks and Firman Kristus are preserved as inline
<b>/<i> tags — the same convention the AY .txt uses — so both the PDF
(reportlab's Paragraph markup) and the web view (via the `markup` filter)
render them. Pertanyaan (and every other field) is a short structured line
where inline formatting isn't meaningful, so it's kept plain even if it was
formatted in the source doc.
"""
from datetime import timedelta

from content import (
    DAY_NAMES_ID, ID_MONTHS_NAME, format_id_date, format_period, parse_id_date,
)
from docx_utils import extract_docx_paragraphs, strip_bi_tags

_DAY_NAMES_LOWER = {d.lower() for d in DAY_NAMES_ID}
_HEADINGS = {"konteks", "firman kristus", "pertanyaan"}


def _day_header_parts(plain):
    """If `plain` is a day-header line — a bare day name, or "<day> | <date>"
    — return (day_name, date_str_or_None); else None."""
    name, sep, rest = plain.partition("|")
    name = name.strip()
    if name.lower() in _DAY_NAMES_LOWER:
        return name, (rest.strip() if sep else None)
    return None


def _split_day_blocks(paragraphs):
    """Split lines into one block per day: {"day_name", "date_str", "author",
    "lines"}. When a day header carries its own date ("<day> | <date>"), the
    isolated non-empty line right before it — itself preceded by a blank
    line (or the very start of the doc), so it can't be mistaken for the
    previous day's last Pertanyaan answer — is taken as that day's author
    byline. Bare day-name headers (the format with no per-day dates) never
    have an author line, since that's not how that format's source docs are
    written."""
    blocks = []
    for idx, para in enumerate(paragraphs):
        parts = _day_header_parts(para["plain"])
        if parts is None:
            if blocks:
                blocks[-1]["lines"].append(para)
            continue

        day_name, date_str = parts
        author = ""
        if date_str is not None and idx >= 1 and paragraphs[idx - 1]["plain"]:
            preceding_is_blank = idx < 2 or not paragraphs[idx - 2]["plain"]
            if preceding_is_blank:
                author = paragraphs[idx - 1]["plain"]
                if blocks and blocks[-1]["lines"] and blocks[-1]["lines"][-1] is paragraphs[idx - 1]:
                    blocks[-1]["lines"].pop()

        blocks.append({"day_name": day_name, "date_str": date_str, "author": author, "lines": []})
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
    lines = block["lines"]
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
    questions = [strip_bi_tags(q) for q in questions_text.split("\n") if q.strip()]

    return {
        "date": format_id_date(day_date, block["day_name"]),
        "author": block["author"],
        "theme": theme,
        "verse": verse,
        "context": context,
        "firman_kristus": firman_kristus,
        "questions": questions,
    }


def parse_docx_file(path, start_date=None):
    """Parse the Umum .docx into the same shape the reader/PDF expect:
    {title, week, month, period, days: [...]}. `start_date` is the Monday
    (or otherwise first day) of the week — only needed as a fallback for a
    day header with no date of its own (the bare-day-name format); a doc
    where every day header carries its own date doesn't need it at all."""
    paragraphs = extract_docx_paragraphs(path)
    non_empty = [p for p in paragraphs if p["plain"]]
    title = non_empty[0]["plain"] if non_empty else ""

    blocks = _split_day_blocks(paragraphs)
    if not blocks:
        raise ValueError(
            "No day sections found — expected day headers like 'Senin' or "
            "'Senin | 7 September 2026'."
        )

    # This format has no dedicated title paragraph — its first line is
    # actually the first day's author byline. Leave title blank so the
    # admin's own title (or the upload form's fallback) takes over.
    if blocks[0]["author"] and title == blocks[0]["author"]:
        title = ""

    resolved_dates = []
    for i, block in enumerate(blocks):
        d = parse_id_date(block["date_str"]) if block["date_str"] else None
        if d is None:
            if start_date is None:
                raise ValueError(
                    f"Could not determine the date for '{block['day_name']}' "
                    "— provide a week start date."
                )
            d = start_date + timedelta(days=i)
        resolved_dates.append(d)

    days = [_parse_day_block(block, d) for block, d in zip(blocks, resolved_dates)]

    start, end = resolved_dates[0], resolved_dates[-1]
    period = format_period(start, end)
    month = f"{ID_MONTHS_NAME[start.month]} {start.year}"

    return {
        "title": title, "week": "", "month": month, "period": period,
        "days": days, "start_date": start.isoformat(),
    }

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
import zipfile
from datetime import timedelta
from xml.etree import ElementTree as ET

from content import DAY_NAMES_ID, ID_MONTHS_NAME, format_id_date, format_period

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DAY_NAMES_LOWER = {d.lower() for d in DAY_NAMES_ID}
_HEADINGS = {"konteks", "firman kristus", "pertanyaan"}


def _run_is_on(rpr, tag):
    """A <w:b/> or <w:i/> run property means "on" unless explicitly turned
    off with w:val="0"/"false"."""
    el = rpr.find(f"{_W}{tag}") if rpr is not None else None
    if el is None:
        return False
    val = el.get(f"{_W}val")
    return val not in ("0", "false")


def _paragraph_texts(p):
    """A paragraph's plain text (for structural matching) and its "rich"
    text with bold/italic runs wrapped in <b>/<i> tags (for content)."""
    plain_parts, rich_parts = [], []
    for r in p.iter(f"{_W}r"):
        text = "".join(t.text or "" for t in r.iter(f"{_W}t"))
        if not text:
            continue
        plain_parts.append(text)
        rpr = r.find(f"{_W}rPr")
        wrapped = text
        if _run_is_on(rpr, "i"):
            wrapped = f"<i>{wrapped}</i>"
        if _run_is_on(rpr, "b"):
            wrapped = f"<b>{wrapped}</b>"
        rich_parts.append(wrapped)
    return "".join(plain_parts).strip(), "".join(rich_parts).strip()


def _extract_paragraphs(path):
    """Read a .docx and return one {plain, rich} dict per paragraph (empty
    ones kept, so callers can use them as spacing cues)."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for p in root.iter(f"{_W}p"):
        plain, rich = _paragraph_texts(p)
        paragraphs.append({"plain": plain, "rich": rich})
    return paragraphs


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
    paragraphs = _extract_paragraphs(path)
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

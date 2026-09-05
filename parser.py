import re


DAYS_PATTERN = r"(?:Minggu|Senin|Selasa|Rabu|Kamis|Jumat|Sabtu),\s+\d{1,2}\s+\w+\s+\d{4}"

# Looser than DAYS_PATTERN — just a day name starting its own line, whether
# or not a full date follows. Used only to find chunk boundaries, so an
# incomplete/placeholder day header (e.g. an unfinished "Sabtu, 2026 -"
# template) still splits off its own chunk instead of bleeding into the
# previous day's fields; DAYS_PATTERN then decides which chunks are real.
_DAY_NAME_LINE_RE = r"^(?:Minggu|Senin|Selasa|Rabu|Kamis|Jumat|Sabtu),"


# ----------------------------
# Helpers
# ----------------------------
def extract(pattern, text):
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_list(pattern, text):
    return [x.strip() for x in re.findall(pattern, text)]


def extract_items(block):
    """A numbered list ('1. ...', '2. ...'), or — if the source doesn't
    number items itself (e.g. a docx with one paragraph per question, no
    manual numbering) — one item per non-empty line."""
    numbered = extract_list(r"\d+\.\s*(.*)", block)
    if numbered:
        return numbered
    return [line.strip() for line in block.splitlines() if line.strip()]


# ----------------------------
# Week & Month
# ----------------------------
def extract_week_info(text):
    week = extract(r"(Week\s+\d+)", text)
    month = extract(r"Week\s+\d+\s+([A-Za-z]+\s+\d{4})", text)
    period = re.search(r"\d{1,2}(?:\s+[A-Za-z]+)?\s*-\s*\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})", text).group(0)
    return week, month, period


# ----------------------------
# Split into days
# ----------------------------
def split_days(text):
    day_re = re.compile(DAYS_PATTERN)
    chunks = re.split(rf"(?={_DAY_NAME_LINE_RE})", text, flags=re.MULTILINE)
    # Keep only chunks whose header is a real, complete day date — drops the
    # week/month/period header (when a separator is missing) and any
    # incomplete/placeholder day header, without letting either bleed into
    # an adjacent real day's fields.
    return [c.strip() for c in chunks if c.strip() and day_re.match(c.strip())]


# ----------------------------
# Parse one day
# ----------------------------
def parse_day(day_text):
    data = {
        "date": "",
        "author": "",
        "theme": "",
        "verse": "",
        "key_message": "",
        "context": "",
        "firman_kristus": "",
        "m1": "",
        "m3": "",
        "m4": "",
        "questions": [],
        "aplikasi": []
    }

    lines = [l.strip() for l in day_text.splitlines() if l.strip()]

    # Header line: "Minggu, 25 Januari 2026 - Author"
    header = lines[0]
    if " - " in header:
        data["date"], data["author"] = header.split(" - ", 1)
    else:
        data["date"] = header

    full_text = "\n".join(lines)

    data["theme"] = extract(r"THEME\s*:\s*(.*?)(?=Ayat Bacaan)", full_text)
    data["verse"] = extract(r"Ayat Bacaan\s*:\s*(.*?)(?=M1:|Key Message)", full_text)
    data["key_message"] = extract(r"Key Message\s*:\s*(.*?)(?=Segment 1:|Pertanyaan)", full_text)

    data["m1"] = extract(r"M1:\s*(.*?)(Key Message)", full_text)

    questions_block = extract(
        r"Pertanyaan Perenungan Ayat\s*:\s*(.*?)(?=Segment 1:|M2:|Segment 2:)",
        full_text
    )
    data["questions"] = extract_items(questions_block)

    data["context"] = extract(
        r"Segment 1:.*?\n(.*?)(?=Segment 2:)",
        full_text
    )
    data["firman_kristus"] = extract(
        r"Segment 2:.*?\n(.*?)(?=Aplikasi)",
        full_text
    )

    aplikasi_block = extract(
        r"Aplikasi\s*:\s*(.*?)(?=M3:)",
        full_text
    )
    data["aplikasi"] = extract_items(aplikasi_block)


    data["m3"] = extract(r"M3: Yang saya akan lakukan setelah menerima Firman Kristus ini adalah…\s*(.*?)(?=M4:|$)", full_text)
    data["m4"] = extract(r"M4:\s*(.*?)(?=____|$)", full_text)

    return data


# ----------------------------
# Main parser
# ----------------------------
def parse_text(text):
    week, month, period = extract_week_info(text)

    # Remove header before first line of underscores
    parts = re.split(r"_{5,}", text, maxsplit=1)
    if len(parts) > 1:
        text = parts[1]

    days_raw = split_days(text)
    # split_days should already guarantee every chunk has a real date, but
    # skip anything that slips through without one anyway (blank/malformed
    # day header), the same way a .txt source never produces such a day.
    days = [d for d in (parse_day(day) for day in days_raw) if d.get("date")]

    return {
        "week": week,
        "month": month,
        "period": period,
        "days": days
    }


def parse_txt_file(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    return parse_text(text)


# Only these fields keep a docx's Bold/Italic formatting; every other field
# is a short structured line (theme, verse, a question, …) where inline
# formatting isn't meaningful, so it's stripped back to plain text.
_DOCX_RICH_FIELDS = {"context", "firman_kristus"}

# Structural marker lines (field labels, day headers, underscore separators)
# must stay plain even if bold/italic was applied to them in Word: the
# parser locates fields by searching for this literal text, and admins
# often bold a heading like "Segment 2:" for visual emphasis in the doc.
# If that got wrapped in <b>, the tag would land right before the label —
# leaking an unclosed <b> onto the end of whatever field's regex capture
# stops at that label (via a lookahead), since the closing </b> (after the
# label) falls outside that capture and is silently discarded. Forcing
# these lines to plain text avoids the leak entirely.
_STRUCTURAL_LINE_RE = re.compile(
    r"^(?:_{3,}"
    r"|(?:THEME|Ayat Bacaan|M1|Key Message|Pertanyaan Perenungan Ayat"
    r"|M2|Segment 1|Segment 2|Aplikasi|M3|M4)\s*:"
    rf"|{_DAY_NAME_LINE_RE})"
)


def parse_docx_paragraphs(paragraphs):
    """Same field-label format as the .txt (THEME:, Ayat Bacaan:, M1:, …),
    but sourced from a Word doc's paragraphs. Bold/italic runs come in
    pre-wrapped as <b>/<i> tags (see docx_utils), so this reconstructs a
    line-per-paragraph blob and reuses the exact same regex-based parsing
    the .txt format uses — meaning field labels (THEME:, Segment 1:, …) and
    day headers are always read as plain text (see _STRUCTURAL_LINE_RE)
    regardless of their own formatting. Bold/italic is then kept only for
    Segment 1 (context) and Segment 2 (firman_kristus); every other field
    is stripped back to plain text even if it was formatted in the source
    doc."""
    from docx_utils import strip_bi_tags

    text = "\n".join(
        p["plain"] if _STRUCTURAL_LINE_RE.match(p["plain"]) else p["rich"]
        for p in paragraphs
    )
    parsed = parse_text(text)
    for day in parsed["days"]:
        for key, value in day.items():
            if key in _DOCX_RICH_FIELDS:
                continue
            if isinstance(value, str):
                day[key] = strip_bi_tags(value)
            elif isinstance(value, list):
                day[key] = [strip_bi_tags(v) for v in value]
    return parsed


def parse_docx_file(path):
    from docx_utils import extract_docx_paragraphs
    return parse_docx_paragraphs(extract_docx_paragraphs(path))


# ----------------------------
# Test
# ----------------------------
if __name__ == "__main__":
    data = parse_txt_file("input.txt")

    print("WEEK:", data["week"])
    print("MONTH:", data["month"])
    print("PERIOD:", data["period"])
    print("FIRST DAY SAMPLE:\n")
    print("date", data["days"][0]["date"])
    print("author", data["days"][0]["author"])
    print("theme", data["days"][0]["theme"])
    print("verse", data["days"][0]["verse"])
    print("key message", data["days"][0]["key_message"])
    print("m1", data["days"][0]["m1"])
    print("pertanyaan", data["days"][0]["questions"])
    print("context", data["days"][0]["context"])
    print("firman kristus", data["days"][0]["firman_kristus"])
    print("aplikasi", data["days"][0]["aplikasi"])
    print("m3", data["days"][0]["m3"])
    print("m4", data["days"][0]["m4"])

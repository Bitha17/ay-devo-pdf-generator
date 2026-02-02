import re


DAYS_PATTERN = r"(?:Minggu|Senin|Selasa|Rabu|Kamis|Jumat|Sabtu),\s+\d{1,2}\s+\w+\s+\d{4}"


# ----------------------------
# Helpers
# ----------------------------
def extract(pattern, text):
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_list(pattern, text):
    return [x.strip() for x in re.findall(pattern, text)]


# ----------------------------
# Week & Month
# ----------------------------
def extract_week_info(text):
    week = extract(r"(Week\s+\d+)", text)
    month = extract(r"Week\s+\d+\s+([A-Za-z]+\s+\d{4})", text)
    period = re.search(r"\d{1,2}\s*-\s*\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})", text).group(0)
    return week, month, period


# ----------------------------
# Split into days
# ----------------------------
def split_days(text):
    pattern = rf"(?={DAYS_PATTERN})"
    chunks = re.split(pattern, text)
    return [c.strip() for c in chunks if c.strip()]


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
    data["questions"] = extract_list(r"\d+\.\s*(.*)", questions_block)

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
    data["aplikasi"] = extract_list(r"\d+\.\s*(.*)", aplikasi_block)


    data["m3"] = extract(r"M3: Yang saya akan lakukan setelah menerima Firman Kristus ini adalah…\s*(.*?)(?=M4:|$)", full_text)
    data["m4"] = extract(r"M4:\s*(.*?)(?=____)", full_text)

    return data


# ----------------------------
# Main parser
# ----------------------------
def parse_txt_file(path):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()

    week, month, period = extract_week_info(text)

    # Remove header before first line of underscores
    parts = re.split(r"_{5,}", text, maxsplit=1)
    if len(parts) > 1:
        text = parts[1]

    days_raw = split_days(text)
    days = [parse_day(day) for day in days_raw]

    return {
        "week": week,
        "month": month,
        "period": period,
        "days": days
    }


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

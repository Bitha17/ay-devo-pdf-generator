"""Shared .docx paragraph extraction, used by both the AY and Umum parsers.

Reads a Word document with the standard library only (no python-docx
dependency) and returns one {plain, rich} pair per paragraph: `plain` is
the bare text (for structural matching — headers, labels, day names),
`rich` is the same text with bold/italic runs wrapped in <b>/<i> tags,
matching the inline-markup convention the AY .txt format already uses.
"""
import re
import zipfile
from xml.etree import ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_BI_TAG_RE = re.compile(r"</?[bi]>", re.IGNORECASE)


def strip_bi_tags(text):
    """Remove <b>/<i> markup, leaving the plain text — for fields where a
    docx's Bold/Italic formatting shouldn't carry through."""
    return _BI_TAG_RE.sub("", text)


def _run_is_on(rpr, tag):
    """A <w:b/> or <w:i/> run property means "on" unless explicitly turned
    off with w:val="0"/"false"."""
    el = rpr.find(f"{_W}{tag}") if rpr is not None else None
    if el is None:
        return False
    val = el.get(f"{_W}val")
    return val not in ("0", "false")


def _wrap(text, rpr):
    if _run_is_on(rpr, "i"):
        text = f"<i>{text}</i>"
    if _run_is_on(rpr, "b"):
        text = f"<b>{text}</b>"
    return text


def _paragraph_lines(p):
    """A paragraph's text, split into one (plain, rich) pair per line — a
    Word paragraph can itself contain manual line breaks (<w:br/>, a
    "soft return" from Shift+Enter) rather than starting a new paragraph,
    and those need to be treated the same as an actual paragraph break for
    line-based structural matching (day headers, field labels, …)."""
    lines = []
    plain_parts, rich_parts = [], []
    for r in p.iter(f"{_W}r"):
        rpr = r.find(f"{_W}rPr")
        for child in r:
            tag = child.tag
            if tag == f"{_W}t":
                text = child.text or ""
                if text:
                    plain_parts.append(text)
                    rich_parts.append(_wrap(text, rpr))
            elif tag in (f"{_W}br", f"{_W}cr"):
                lines.append(("".join(plain_parts).strip(), "".join(rich_parts).strip()))
                plain_parts, rich_parts = [], []
            elif tag == f"{_W}tab":
                plain_parts.append("\t")
                rich_parts.append("\t")
    lines.append(("".join(plain_parts).strip(), "".join(rich_parts).strip()))
    return lines


def extract_docx_paragraphs(path):
    """Read a .docx and return one {"plain": ..., "rich": ...} dict per
    line (empty ones kept, so callers can use them as spacing cues). A
    Word paragraph normally produces one line; a paragraph containing
    manual line breaks (Shift+Enter) produces one per line."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    return [
        {"plain": plain, "rich": rich}
        for p in root.iter(f"{_W}p")
        for plain, rich in _paragraph_lines(p)
    ]

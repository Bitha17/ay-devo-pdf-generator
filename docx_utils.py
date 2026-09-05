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


def _paragraph_texts(p):
    """A paragraph's plain text and its "rich" text with bold/italic runs
    wrapped in <b>/<i> tags."""
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


def extract_docx_paragraphs(path):
    """Read a .docx and return one {"plain": ..., "rich": ...} dict per
    paragraph (empty ones kept, so callers can use them as spacing cues)."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    return [
        dict(zip(("plain", "rich"), _paragraph_texts(p)))
        for p in root.iter(f"{_W}p")
    ]

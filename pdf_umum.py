"""PDF generator for the Umum division — same weekly-devotion shape as the AY
generator (pdf.py), but far fewer components: a supplied cover page, then
plain white content pages with just a heading, day/date + verse, and three
sections (Konteks / Firman Kristus / Pertanyaan). No content-page background,
no key-message/M1/M3/M4/Aplikasi boxes.

Each day must fit on exactly one page, so its font size is picked per day:
built at the largest size first, then shrunk step by step until a trial
layout (see `_fits_one_page`) confirms it fits — days with little content
render large (filling the page), long ones shrink just enough to still fit.
"""
import os
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas as PDFCanvas
from reportlab.platypus import (
    Frame, HRFlowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "icons", "abbalove_logo.png")

# Reuse the same TTF files as the AY generator, under their own font names so
# this module has no load-order dependency on pdf.py.
pdfmetrics.registerFont(TTFont("UmumBody", os.path.join(BASE_DIR, "fonts", "Outfit", "Outfit-Regular.ttf")))
pdfmetrics.registerFont(TTFont("UmumBody-Bold", os.path.join(BASE_DIR, "fonts", "Outfit", "Outfit-Bold.ttf")))
pdfmetrics.registerFont(TTFont("UmumBody-Italic", os.path.join(BASE_DIR, "fonts", "Inter", "Inter_18pt-Italic.ttf")))
pdfmetrics.registerFont(TTFont("UmumBody-BoldItalic", os.path.join(BASE_DIR, "fonts", "Inter", "Inter_18pt-BoldItalic.ttf")))
pdfmetrics.registerFontFamily(
    "UmumBody",
    normal="UmumBody", bold="UmumBody-Bold",
    italic="UmumBody-Italic", boldItalic="UmumBody-BoldItalic",
)

_TEXT_COLOR = colors.HexColor("#1A1A1A")

# (fontSize, leading, spaceBefore, spaceAfter) at scale 1.0 — the largest,
# most-content-fills-the-page size a short day renders at.
_BASE_SIZES = {
    "heading": (20, 24, 0, 0),
    "dayverse": (14, 18, 0, 0),
    "section": (15, 19, 12, 8),
    "body": (14, 20, 0, 10),
    "question": (14, 20, 0, 8),
}

# Tried largest first; the first one whose rendered content fits on one page
# wins. The smallest is a last-resort floor — an extremely long day still
# renders (just tight) rather than silently overflowing to a second page.
_SCALE_STEPS = [1.0, 0.93, 0.86, 0.79, 0.72, 0.65, 0.58, 0.5]


def _styles_for_scale(scale):
    def sized(key):
        fs, ld, sb, sa = _BASE_SIZES[key]
        return fs * scale, ld * scale, sb * scale, sa * scale

    heading_fs, heading_ld, _, _ = sized("heading")
    dayverse_fs, dayverse_ld, _, _ = sized("dayverse")
    section_fs, section_ld, section_sb, section_sa = sized("section")
    body_fs, body_ld, _, body_sa = sized("body")
    question_fs, question_ld, _, question_sa = sized("question")

    dayverse = ParagraphStyle(
        name="UmumDayVerse", fontName="UmumBody-Bold", fontSize=dayverse_fs,
        leading=dayverse_ld, textColor=_TEXT_COLOR,
    )
    question_indent = question_fs * 1.15
    return {
        "heading": ParagraphStyle(
            name="UmumHeading", fontName="UmumBody-Bold", fontSize=heading_fs,
            leading=heading_ld, textColor=_TEXT_COLOR,
        ),
        "dayverse": dayverse,
        "dayverse_right": ParagraphStyle(
            name="UmumDayVerseRight", parent=dayverse, alignment=TA_RIGHT,
        ),
        "section": ParagraphStyle(
            name="UmumSectionLabel", fontName="UmumBody-Bold", fontSize=section_fs,
            leading=section_ld, textColor=_TEXT_COLOR,
            spaceBefore=section_sb, spaceAfter=section_sa,
        ),
        "body": ParagraphStyle(
            name="UmumBody", fontName="UmumBody", fontSize=body_fs, leading=body_ld,
            alignment=TA_JUSTIFY, textColor=_TEXT_COLOR, spaceAfter=body_sa,
        ),
        "question": ParagraphStyle(
            name="UmumQuestion", fontName="UmumBody", fontSize=question_fs,
            leading=question_ld, alignment=TA_JUSTIFY, textColor=_TEXT_COLOR,
            leftIndent=question_indent, firstLineIndent=-question_indent,
            spaceAfter=question_sa,
        ),
    }


def _day_flowables(day, styles, content_width):
    flow = []

    header_table = Table(
        [[
            Image(LOGO_PATH, width=28, height=28),
            Paragraph(day["theme"].upper(), styles["heading"]),
        ]],
        colWidths=[36, content_width - 36],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    flow.append(header_table)
    flow.append(Spacer(1, 8))
    flow.append(HRFlowable(width="100%", thickness=1, color=_TEXT_COLOR))
    flow.append(Spacer(1, 14))

    dayverse_table = Table(
        [[
            Paragraph(day["date"].upper(), styles["dayverse"]),
            Paragraph(day["verse"].upper(), styles["dayverse_right"]),
        ]],
        colWidths=[content_width * 0.6, content_width * 0.4],
    )
    dayverse_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    flow.append(dayverse_table)
    flow.append(Spacer(1, 16))

    if day["context"]:
        flow.append(Paragraph("KONTEKS", styles["section"]))
        for para in day["context"].split("\n"):
            if para.strip():
                flow.append(Paragraph(para, styles["body"]))

    if day["firman_kristus"]:
        flow.append(Paragraph("FIRMAN KRISTUS", styles["section"]))
        for para in day["firman_kristus"].split("\n"):
            if para.strip():
                flow.append(Paragraph(para, styles["body"]))

    if day["questions"]:
        flow.append(Paragraph("PERTANYAAN", styles["section"]))
        for i, q in enumerate(day["questions"], start=1):
            flow.append(Paragraph(f"{i}. {q}", styles["question"]))

    return flow


def _fits_one_page(flowables, width, height):
    """Lay `flowables` out in a single throwaway Frame the size of one page's
    content area (no real drawing is kept — the canvas is discarded) and
    report whether all of them fit without needing a second page."""
    frame = Frame(0, 0, width, height, leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    remaining = list(flowables)
    frame.addFromList(remaining, PDFCanvas(BytesIO()))
    return not remaining


def _day_story(day, doc):
    # SimpleDocTemplate's default frame has a 6pt padding on every side.
    content_width = doc.width - 12
    content_height = doc.height - 12
    for scale in _SCALE_STEPS:
        styles = _styles_for_scale(scale)
        flow = _day_flowables(day, styles, content_width)
        if _fits_one_page(flow, content_width, content_height):
            return flow
    return flow  # smallest size tried — best effort if still too long


def draw_bg(canvas, doc, bg_path):
    width, height = A4
    canvas.drawImage(bg_path, 0, 0, width=width, height=height)


def generate_pdf_umum(docx_path, cover_path, start_date):
    """Parse a .docx and render it. Thin wrapper around generate_pdf_from_data_umum."""
    from parser_umum import parse_docx_file
    return generate_pdf_from_data_umum(parse_docx_file(docx_path, start_date), cover_path)


def generate_pdf_from_data_umum(data, cover_path):
    buffer = BytesIO()

    title = data["title"]
    period = data["period"]
    days = data["days"]

    pdf_name = f"{title} - Umum - {period}.pdf"
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )

    story = []
    for day in days:
        story.append(PageBreak())
        story.extend(_day_story(day, doc))

    doc.build(
        story,
        onFirstPage=lambda canvas, doc: draw_bg(canvas, doc, cover_path),
        onLaterPages=lambda canvas, doc: None,
    )

    buffer.seek(0)
    return buffer, pdf_name

"""PDF generator for the Umum division — same weekly-devotion shape as the AY
generator (pdf.py), but far fewer components: a supplied cover page, then
plain white content pages with just a heading, day/date + verse, and three
sections (Konteks / Firman Kristus / Pertanyaan). No content-page background,
no key-message/M1/M3/M4/Aplikasi boxes.
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
from reportlab.platypus import (
    HRFlowable, Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
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

HEADING_STYLE = ParagraphStyle(
    name="UmumHeading", fontName="UmumBody-Bold", fontSize=16, leading=20,
    textColor=colors.HexColor("#1A1A1A"),
)

DAYVERSE_STYLE = ParagraphStyle(
    name="UmumDayVerse", fontName="UmumBody-Bold", fontSize=12, leading=16,
    textColor=colors.HexColor("#1A1A1A"),
)

DAYVERSE_RIGHT_STYLE = ParagraphStyle(
    name="UmumDayVerseRight", parent=DAYVERSE_STYLE, alignment=TA_RIGHT,
)

SECTION_LABEL_STYLE = ParagraphStyle(
    name="UmumSectionLabel", fontName="UmumBody-Bold", fontSize=12, leading=16,
    textColor=colors.HexColor("#1A1A1A"), spaceBefore=10, spaceAfter=6,
)

BODY_STYLE = ParagraphStyle(
    name="UmumBody", fontName="UmumBody", fontSize=11, leading=15,
    alignment=TA_JUSTIFY, textColor=colors.HexColor("#1A1A1A"), spaceAfter=8,
)

QUESTION_STYLE = ParagraphStyle(
    name="UmumQuestion", fontName="UmumBody", fontSize=11, leading=15,
    alignment=TA_JUSTIFY, textColor=colors.HexColor("#1A1A1A"),
    leftIndent=14, firstLineIndent=-14, spaceAfter=6,
)


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

        header_table = Table(
            [[
                Image(LOGO_PATH, width=28, height=28),
                Paragraph(day["theme"].upper(), HEADING_STYLE),
            ]],
            colWidths=[36, doc.width - 36],
        )
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1A1A1A")))
        story.append(Spacer(1, 14))

        dayverse_table = Table(
            [[
                Paragraph(day["date"].upper(), DAYVERSE_STYLE),
                Paragraph(day["verse"].upper(), DAYVERSE_RIGHT_STYLE),
            ]],
            colWidths=[doc.width * 0.6, doc.width * 0.4],
        )
        dayverse_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(dayverse_table)
        story.append(Spacer(1, 16))

        if day["context"]:
            story.append(Paragraph("KONTEKS", SECTION_LABEL_STYLE))
            for para in day["context"].split("\n"):
                if para.strip():
                    story.append(Paragraph(para, BODY_STYLE))

        if day["firman_kristus"]:
            story.append(Paragraph("FIRMAN KRISTUS", SECTION_LABEL_STYLE))
            for para in day["firman_kristus"].split("\n"):
                if para.strip():
                    story.append(Paragraph(para, BODY_STYLE))

        if day["questions"]:
            story.append(Paragraph("PERTANYAAN", SECTION_LABEL_STYLE))
            for i, q in enumerate(day["questions"], start=1):
                story.append(Paragraph(f"{i}. {q}", QUESTION_STYLE))

    doc.build(
        story,
        onFirstPage=lambda canvas, doc: draw_bg(canvas, doc, cover_path),
        onLaterPages=lambda canvas, doc: None,
    )

    buffer.seek(0)
    return buffer, pdf_name

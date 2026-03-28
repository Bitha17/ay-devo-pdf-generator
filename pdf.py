from parser import parse_txt_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import Image, KeepInFrame, ListFlowable, ListItem, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from io import BytesIO
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------------------
# Register Fonts
# ----------------------------
pdfmetrics.registerFont(TTFont("TitleFont", os.path.join(BASE_DIR, "fonts", "PoynterOldStyle","PoynterOldstyleText-Roman.ttf")))
pdfmetrics.registerFont(TTFont("BodyFont", os.path.join(BASE_DIR, "fonts", "Outfit","Outfit-Regular.ttf")))
pdfmetrics.registerFont(TTFont("BodyFont-Bold", os.path.join(BASE_DIR, "fonts", "Outfit","Outfit-Bold.ttf")))
pdfmetrics.registerFont(TTFont("BodyFont-Italic", os.path.join(BASE_DIR, "fonts", "Inter","Inter_18pt-Italic.ttf")))
pdfmetrics.registerFont(TTFont("BodyFont-BoldItalic", os.path.join(BASE_DIR, "fonts", "Inter","Inter_18pt-BoldItalic.ttf")))
pdfmetrics.registerFont(TTFont("Body2Font", os.path.join(BASE_DIR, "fonts", "Outfit","Outfit-SemiBold.ttf")))
pdfmetrics.registerFont(TTFont("HeadingFont", os.path.join(BASE_DIR, "fonts", "BiondiSans","biondi-sans-bd.ttf")))
pdfmetrics.registerFont(TTFont("PageFont", os.path.join(BASE_DIR, "fonts", "BiondiSans","biondi-sans-rg.ttf")))

pdfmetrics.registerFontFamily(
    "BodyFont",
    normal="BodyFont",
    bold="BodyFont-Bold",
    italic="BodyFont-Italic",
    boldItalic="BodyFont-BoldItalic"
)

# ----------------------------
# Styles
# ----------------------------

def fit_font_size(text, font_name, max_width, max_size=18, min_size=10):
    size = max_size
    while size > min_size:
        text_width = pdfmetrics.stringWidth(text, font_name, size)
        if text_width <= max_width:
            return size
        size -= 0.5
    return min_size

DATE_STYLE = ParagraphStyle(
    name="DateHeader",
    fontName="BodyFont",
    fontSize=10,
    spaceAfter=12,
    leftIndent=6,
    textColor=colors.HexColor("#FFFFFF")
)

WEEK_STYLE = ParagraphStyle(
    name="WeekHolder",
    fontName="BodyFont",
    fontSize=10,
    spaceAfter=12,
    textColor=colors.HexColor("#FFFFFF"),
    alignment=TA_RIGHT
)

THEME_STYLE = ParagraphStyle(
    name="Heading",
    fontName="TitleFont",
    fontSize=25,
    leading=32,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#FFFFFF"),
)

VERSE_STYLE = ParagraphStyle(
    name="VerseHolder",
    fontName="BodyFont",
    fontSize=12,
    spaceAfter=12,
    textColor=colors.HexColor("#FFFFFF"),
    alignment=TA_CENTER
)

KEY_STYLE = ParagraphStyle(
    name="KeyHolder",
    fontName="BodyFont",
    fontSize=14,
    leading=18,
    textColor=colors.HexColor("#FFFFFF"),
    alignment=TA_CENTER
)

HEADING_STYLE = ParagraphStyle(
    name="Heading",
    fontName="HeadingFont",
    fontSize=13,
    textColor=colors.HexColor("#204170"),
    alignment=TA_RIGHT
)

M1_STYLE = ParagraphStyle(
    name="M1",
    fontName="BodyFont",
    fontSize=11,
    leading=13,
    textColor=colors.HexColor("#FFFFFF"),
    alignment=TA_JUSTIFY
)

QUEST_STYLE = ParagraphStyle(
    name="Body",
    fontName="BodyFont",
    fontSize=10,
    leading=12,
    leftIndent=122,
    firstLineIndent=-12,
    alignment=TA_JUSTIFY,
)

AP_STYLE = ParagraphStyle(
    name="Body",
    fontName="BodyFont",
    fontSize=10,
    leading=12,
    leftIndent=12,
    firstLineIndent=-12,
    alignment=TA_JUSTIFY,
)

BODY_STYLE = ParagraphStyle(
    name="Body",
    fontName="BodyFont",
    fontSize=11,
    leading=11,
    spaceAfter=8,
    alignment=TA_JUSTIFY,
)

BODY2_STYLE = ParagraphStyle(
    name="Body2",
    fontName="Body2Font",
    fontSize=10,
    leading=12,
    spaceAfter=8,
    alignment=TA_JUSTIFY,
    textColor=colors.HexColor("#FFFFFF")
)

PAGE_STYLE = ParagraphStyle(
    name="Page",
    fontName="PageFont",
    fontSize=15,
    alignment=TA_RIGHT,
    textColor=colors.white
)

# ----------------------------
# Helpers
# ----------------------------
def draw_bg(canvas, doc, bg_path):
    width, height = A4
    canvas.drawImage(bg_path, 0, 0, width=width, height=height)

def white_box_bullet(text, style, text_width):
    bullet_box = Table(
        [[""]],
        colWidths=6,
        rowHeights=6
    )

    bullet_box.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ("GRID", (0,0), (-1,-1), 0.5, colors.white),
    ]))

    return Table(
        [[bullet_box, Paragraph(text, style)]],
        colWidths=[10, text_width],
        style=TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (0,0), 4),
            ("TOPPADDING", (1,0), (1,0), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ])
    )

# ----------------------------
# Main Generator
# ----------------------------
def generate_pdf(txt_path, title_path, bg_path):
    
    bg_path = os.path.join(BASE_DIR, bg_path)
    buffer = BytesIO()

    data = parse_txt_file(txt_path)
    week = data["week"]
    month = data["month"]
    period = data["period"]
    days = data["days"]

    pdf_path = f"Devotion AbbaYouth_{period}.pdf"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=1.5 * cm,
        topMargin=1 * cm,
        bottomMargin=0.1 * cm
    )

    story = []

    page = 1

    # -------- DAILY CONTENT --------
    for day in days:
        story.append(PageBreak())

        header_table = Table(
            [[
                Paragraph(day["date"].upper(), DATE_STYLE),
                Paragraph(f"{week.upper()} | {month.upper()}", WEEK_STYLE)
            ]],
            colWidths=[doc.width * 0.6, doc.width * 0.4]
        )

        header_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),

            # column 0 (date)
            ("LEFTPADDING", (0,0), (0,0), 15),
            ("RIGHTPADDING", (0,0), (0,0), 6),

            # column 1 (week) 
            ("LEFTPADDING", (1,0), (1,0), 20),
            ("RIGHTPADDING", (1,0), (1,0), 0),
        ]))

        story.append(header_table)
        story.append(Spacer(1, 20))

        theme_text = day["theme"].upper()
        theme_para = Paragraph(theme_text, THEME_STYLE)

        theme_frame = KeepInFrame(
            maxWidth=doc.width * 0.75,
            maxHeight=50,
            content=[theme_para],
            mode="shrink",
        )

        theme_table = Table(
            [[theme_frame]],
            colWidths=[doc.width * 0.8],
            rowHeights=[50]    
        )

        theme_table.setStyle(TableStyle([
            ("ALIGN", (0,0), (-1,-1), "CENTER"),   
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),  
            ("LEFTPADDING", (0,0), (-1,-1), 20),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))

        story.append(theme_table)

        verse_para = Paragraph(day["verse"].upper(), VERSE_STYLE)

        verse_frame = KeepInFrame(
            maxWidth=doc.width * 0.34,
            maxHeight=25,
            content=[verse_para],
            mode="shrink",
        )

        verse_table = Table(
            [[(),(verse_frame),()]],
            colWidths=[doc.width * 0.49, doc.width * 0.36, doc.width * 0.15],
            rowHeights=[25],
        )

        verse_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),

            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 0)
        ]))

        story.append(verse_table)
        story.append(Spacer(1,20))

        key_text = day["key_message"]
        key_para = Paragraph(key_text, KEY_STYLE)

        key_frame = KeepInFrame(
            maxWidth=doc.width * 0.9,
            maxHeight=58,
            content=[key_para],
            mode="shrink",
        )

        key_table = Table(
            [[key_frame]],
            colWidths=[doc.width * 0.95],
            rowHeights=[58]    
        )

        key_table.setStyle(TableStyle([
            ("ALIGN", (0,0), (-1,-1), "CENTER"),   
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),  
            ("LEFTPADDING", (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 30),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))

        story.append(key_table)

        m1_para = Paragraph(day["m1"], M1_STYLE)

        m1_frame = KeepInFrame(
            maxWidth=doc.width * 0.8,
            maxHeight=40,
            content=[m1_para],
            mode="shrink",
        )

        m1_table = Table(
            [[(),(m1_frame)]],
            colWidths=[doc.width * 0.2, doc.width * 0.8],
            rowHeights=[40],
        )

        m1_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),

            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 2)
        ]))

        story.append(m1_table)

        story.append(Spacer(1,5))
        
        box_flow = []

        content_flow = []
        # quest_box =[]
        question_icon = Image(os.path.join(BASE_DIR, "icons", "PP.png"), width=10, height=15)
        question_table = Table(
            [[(Paragraph("PERTANYAAN PERENUNGAN", HEADING_STYLE)),(question_icon)]],
            colWidths=[doc.width * 0.7, doc.width * 0.3],
            rowHeights=[20],
        )

        question_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),

            ("LEFTPADDING", (0,0), (-1,-1), 3),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 2)
        ]))

        content_flow.append(question_table)

        if day["questions"]:
            for i, q in enumerate(day["questions"], start=1):
                content_flow.append(Paragraph(f"{i}. {q}", QUEST_STYLE))

        # quest_frame = KeepInFrame(
        #     maxWidth=doc.width,
        #     maxHeight=70,
        #     content=quest_box,
        #     mode="shrink"
        # )

        content_flow.append(Spacer(1,3))
        # box_flow.append(quest_frame)


        # CONTEXT
        context_icon = Image(os.path.join(BASE_DIR, "icons", "K.png"), width=15.2*1.1, height=16.9*1.1)
        context_table = Table(
            [[(Paragraph("KONTEKS", HEADING_STYLE)),(context_icon)]],
            colWidths=[doc.width * 0.55, doc.width * 0.45],
            rowHeights=[20],
        )

        context_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),

            ("LEFTPADDING", (0,0), (-1,-1), 3),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 2)
        ]))

        content_flow.append(context_table)
        content_flow.append(
            Paragraph(day["context"].replace("\n","<br/><br/>"), BODY_STYLE)
        )
        content_flow.append(Spacer(1,6))

        # FIRMAN KRISTUS
        fk_icon = Image(os.path.join(BASE_DIR, "icons", "FK.png"), width=13.1*1.1, height=15.4*1.1)
        fk_table = Table(
            [[(Paragraph("FIRMAN KRISTUS", HEADING_STYLE)),(fk_icon)]],
            colWidths=[doc.width * 0.6, doc.width * 0.4],
            rowHeights=[20],
        )

        fk_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),

            ("LEFTPADDING", (0,0), (-1,-1), 3),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 2)
        ]))

        content_flow.append(fk_table)
        content_flow.append(
            Paragraph(day["firman_kristus"].replace("\n","<br/><br/>"), BODY_STYLE)
        )
        content_flow.append(Spacer(1,6))

        # APLIKASI
        ap_icon = Image(os.path.join(BASE_DIR, "icons","AP.png"), width=17.2*1.1, height=16.3*1.1)
        ap_table = Table(
            [[(Paragraph("APLIKASI", HEADING_STYLE)),(ap_icon)]],
            colWidths=[doc.width * 0.55, doc.width * 0.45],
            rowHeights=[20],
        )

        ap_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),

            ("LEFTPADDING", (0,0), (-1,-1), 3),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 2)
        ]))

        content_flow.append(ap_table)
        for i, a in enumerate(day["aplikasi"], start=1):
            content_flow.append(Paragraph(f"{i}. {a}", AP_STYLE))

        boxed_frame = KeepInFrame(
            maxWidth=doc.width,
            maxHeight=370,
            content=content_flow,
            mode="shrink"
        )

        box_flow.append(boxed_frame)

        boxed_table = Table(
            [[box_flow]],
            colWidths=doc.width,
            rowHeights=370
        )

        boxed_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
        ]))
        story.append(boxed_table)

        m3_para = Paragraph(day["m3"], BODY2_STYLE)

        m3_frame = KeepInFrame(
            maxWidth=doc.width * 0.29,
            maxHeight=80,
            content=[m3_para],
            mode="shrink",
        )

        m4_flow = []

        for line in day["m4"].split("\n"):
            line = line.strip()
            if line:
                m4_flow.append(
                    white_box_bullet(
                        line,
                        BODY2_STYLE,
                        text_width=doc.width * 0.27
                    )
                )

        m4_frame = KeepInFrame(
            maxWidth=doc.width * 0.3,
            maxHeight=165,
            content=m4_flow,
            mode="shrink",
        )

        m34_table = Table(
            [[m3_frame, m4_frame]],
            colWidths=[doc.width * 0.5, doc.width * 0.5],
            rowHeights=[165],
        )

        m34_table.setStyle(TableStyle([
            # ("GRID", (0,0), (-1,-1), 1, "RED"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ALIGN", (0,0), (-1,-1), "RIGHT"),

            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (0,0), 20),
            ("RIGHTPADDING", (1,0), (1,0), 0),
            ("TOPPADDING", (0,0), (0,0), 100),
            ("TOPPADDING", (1,0), (1,0), 20),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0)
        ]))

        story.append(m34_table)
        page_text = str(page)
        story.append(Paragraph(page_text, PAGE_STYLE))
        page += 1

    doc.build(
        story,
        onFirstPage=lambda canvas, doc: draw_bg(canvas, doc, title_path),
        onLaterPages=lambda canvas, doc: draw_bg(canvas, doc, bg_path)
    )

    buffer.seek(0)
    return buffer, pdf_path

# ----------------------------
# Run
# ----------------------------
# import sys

# txt_path = sys.argv[1]
# title_bg = sys.argv[2]
# content_bg = sys.argv[3]

# generate_pdf(txt_path, title_bg, content_bg)

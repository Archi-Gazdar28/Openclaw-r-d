#!/usr/bin/env python3
"""
export_report.py — Tesla R&D Intelligence Report Generator (Exact Match Style)
Generates a professional PDF matching the styling rules of File 1.
Features:
- Minimalist plain black/white/grey color palette
- Clickable Table of Contents with internal navigation
- PDF bookmarks for sidebar navigation
- Precise typography scales, line-leading, and padding rules
- Dynamic page footers via dynamic canvas methods
"""

import argparse
import os
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, HRFlowable
)

# =============================================================================
# Colour palette (Plain black/white/grey matching File 1)
# =============================================================================
C_BLACK  = colors.HexColor("#1a1a1a")
C_DARK   = colors.HexColor("#2d2d2d")
C_MID    = colors.HexColor("#555555")
C_LIGHT  = colors.HexColor("#888888")
C_RULE   = colors.HexColor("#cccccc")
C_SHADE  = colors.HexColor("#f5f5f5")
C_WHITE  = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 2 * cm
CONTENT_WIDTH = PAGE_W - 2 * MARGIN

# =============================================================================
# Style sheet configuration (Exact configurations matching File 1)
# =============================================================================
def build_styles():
    base = getSampleStyleSheet()

    def s(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "cover_title": s("cover_title",
            fontName="Helvetica-Bold", fontSize=26,
            leading=32, textColor=C_BLACK, alignment=TA_CENTER),
        "cover_sub": s("cover_sub",
            fontName="Helvetica", fontSize=13,
            leading=18, textColor=C_MID, alignment=TA_CENTER),
        "cover_meta": s("cover_meta",
            fontName="Helvetica", fontSize=10,
            leading=14, textColor=C_LIGHT, alignment=TA_CENTER),
        "section_h1": s("section_h1",
            fontName="Helvetica-Bold", fontSize=16,
            leading=22, textColor=C_BLACK, spaceBefore=18, spaceAfter=6),
        "section_h2": s("section_h2",
            fontName="Helvetica-Bold", fontSize=12,
            leading=17, textColor=C_DARK, spaceBefore=12, spaceAfter=4),
        "section_h3": s("section_h3",
            fontName="Helvetica-BoldOblique", fontSize=10,
            leading=14, textColor=C_MID, spaceBefore=8, spaceAfter=3),
        "body": s("body",
            fontName="Helvetica", fontSize=9.5,
            leading=14, textColor=C_DARK, spaceAfter=4),
        "body_bold": s("body_bold",
            fontName="Helvetica-Bold", fontSize=9.5,
            leading=14, textColor=C_DARK),
        "bullet": s("bullet",
            fontName="Helvetica", fontSize=9.5,
            leading=14, textColor=C_DARK,
            leftIndent=14, firstLineIndent=-10, spaceAfter=3),
        "label": s("label",
            fontName="Helvetica-Bold", fontSize=8.5,
            leading=12, textColor=C_LIGHT),
        "value": s("value",
            fontName="Helvetica", fontSize=9.5,
            leading=13, textColor=C_DARK),
        "caption": s("caption",
            fontName="Helvetica-Oblique", fontSize=8,
            leading=11, textColor=C_LIGHT, alignment=TA_CENTER),
        "toc_h": s("toc_h",
            fontName="Helvetica-Bold", fontSize=11,
            leading=16, textColor=C_BLACK, spaceAfter=6),
        "toc_item": s("toc_item",
            fontName="Helvetica", fontSize=10,
            leading=15, textColor=C_DARK, leftIndent=10),
    }

ST = build_styles()

# =============================================================================
# Structural Navigation Helpers
# =============================================================================
class Bookmark(Flowable):
    def __init__(self, key, title, level=0):
        Flowable.__init__(self)
        self.key = key
        self.title = title
        self.level = level
        self.width = self.height = 0

    def wrap(self, availWidth, availHeight):
        return 0, 0

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)

def anchor(key):
    return Paragraph(f'<a name="{key}"/>', ParagraphStyle("anchor", fontSize=1, leading=1))

def hr(width=1, color=C_RULE):
    return HRFlowable(width="100%", thickness=width, color=color, spaceAfter=6, spaceBefore=2)

def sp(h=6):
    return Spacer(1, h)

# =============================================================================
# Table Layout Parsers (Exact padding and alternating grid matrix rows)
# =============================================================================
def kv_table(pairs):
    rows = [[Paragraph(k, ST["label"]), Paragraph(v, ST["value"])] for k, v in pairs if v]
    if not rows:
        return None
    cw = [4.5 * cm, CONTENT_WIDTH - 4.5 * cm]
    t = Table(rows, colWidths=cw, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_SHADE]),
        ("LINEBELOW",   (0, 0), (-1, -1), 0.3, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",(0, 0), (-1, -1), 4),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ]))
    return t

def data_table(headers, rows):
    if not rows:
        return None
    header_row = [Paragraph(h, ST["label"]) for h in headers]
    body_rows  = [[Paragraph(str(cell), ST["value"]) for cell in row] for row in rows]
    cw = [CONTENT_WIDTH / len(headers)] * len(headers)
    t = Table([header_row] + body_rows, colWidths=cw, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), C_DARK),
        ("TEXTCOLOR",    (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 8.5),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_SHADE]),
        ("LINEBELOW",    (0, 0), (-1, -1), 0.3, C_RULE),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    return t

# =============================================================================
# Footer Canvas Architecture
# =============================================================================
class NumberedCanvas:
    def __init__(self, company, product):
        self.company = company
        self.product = product

    def footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(C_LIGHT)
        footer_text = (f"OpenClaw R&D Intelligence  ·  {self.company} – {self.product}"
                       f"  ·  Page {doc.page}")
        canvas.drawCentredString(PAGE_W / 2, 1.2 * cm, footer_text)
        canvas.restoreState()

# =============================================================================
# Main Document Builder
# =============================================================================
def build_pdf(output_path="tesla_model_y_report.pdf"):
    company = "Tesla, Inc."
    product = "Model Y"
    title = "R&D Intelligence Report: Tesla Model Y"

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 0.5 * cm,
        title=title,
        author="OpenClaw R&D Intelligence Platform",
        subject=f"{company} – {product}",
    )

    nb = NumberedCanvas(company, product)
    story = []

    # ==================== COVER PAGE ====================
    story += [
        sp(60),
        Paragraph("R&amp;D Intelligence Report", ST["cover_title"]),
        sp(16),
        hr(2, C_BLACK),
        sp(10),
        Paragraph(f"{company}  ·  {product}", ST["cover_sub"]),
        sp(8),
        Paragraph("Generated 2026-06-22  ·  OpenClaw R&amp;D Intelligence Platform", ST["cover_meta"]),
        sp(4),
        Paragraph("Confidential — For internal use only", ST["cover_meta"]),
        PageBreak(),
    ]

    # ==================== TABLE OF CONTENTS ====================
    story += [
        Bookmark("toc", "Table of Contents"),
        anchor("toc"),
        Paragraph("Table of Contents", ST["section_h1"]),
        hr(),
        sp(8),
    ]

    toc_items = [
        ("1", "Company & Product Overview", "sec1"),
        ("2", "Financial Overview", "sec2"),
        ("3", "Patents & Intellectual Property", "sec3"),
        ("4", "Market Trends & Demand Signals", "sec4"),
        ("5", "Competitive Landscape", "sec5"),
        ("6", "References", "sec6")
    ]

    for num, item_title, key in toc_items:
        story.append(Paragraph(f'<link href="#{key}">{num}.  {item_title}</link>', ST["toc_item"]))
    story.append(PageBreak())

    # ==================== SECTION 1 ====================
    story += [
        Bookmark("sec1", "1. Company & Product Overview"),
        anchor("sec1"),
        Paragraph("1. Company & Product Overview", ST["section_h1"]),
        hr(),
        Paragraph("Tesla, Inc. is an American multinational automotive and clean-energy company headquartered in Austin, Texas. Founded in July 2003...", ST["body"]),
        sp(6),
    ]
    t1 = kv_table([
        ("Legal name", "Tesla, Inc."),
        ("Founded", "July 1, 2003"),
        ("HQ", "13101 Tesla Road, Austin, Texas 78725, USA"),
        ("Employees", "140,473 (as of December 31, 2023)"),
        ("Website", "https://www.tesla.com")
    ])
    if t1: story.append(t1)
    story.append(PageBreak())

    # ==================== SECTION 2 ====================
    story += [
        Bookmark("sec2", "2. Financial Overview"),
        anchor("sec2"),
        Paragraph("2. Financial Overview", ST["section_h1"]),
        hr(),
        Paragraph("FY2023 revenue reached $96.77 billion (+19% YoY) with 1,808,581 vehicles delivered.", ST["body"]),
        sp(6),
    ]
    t2 = data_table(["Metric", "Value"], [
        ["Total Revenue", "$96.77B"],
        ["Net Income (GAAP)", "$14.997B"],
        ["Vehicle Deliveries", "1,808,581"],
        ["Automotive Gross Margin", "18.2%"]
    ])
    if t2: story.append(t2)
    story.append(PageBreak())

    # ==================== SECTION 3 ====================
    story += [
        Bookmark("sec3", "3. Patents & Intellectual Property"),
        anchor("sec3"),
        Paragraph("3. Patents & Intellectual Property", ST["section_h1"]),
        hr(),
        Paragraph("Tesla holds 3,000+ patents globally. Key technologies include 4680 cells, structural battery packs, and FSD neural networks.", ST["body"]),
        sp(4),
        Paragraph("Notable Patents", ST["section_h2"]),
        Paragraph("• Cell with a tabless electrode (US20200287202A1)", ST["bullet"]),
        Paragraph("• Structural battery pack with shear panels", ST["bullet"]),
        Paragraph("• Gigacasting / Single-piece casting", ST["bullet"]),
        PageBreak(),
    ]

    # ==================== SECTION 4 ====================
    story += [
        Bookmark("sec4", "4. Market Trends & Demand Signals"),
        anchor("sec4"),
        Paragraph("4. Market Trends & Demand Signals", ST["section_h1"]),
        hr(),
        Paragraph("Model Y was the world’s best-selling vehicle in 2023. Global EV sales continue to grow despite headwinds.", ST["body"]),
        PageBreak(),
    ]

    # ==================== SECTION 5 ====================
    story += [
        Bookmark("sec5", "5. Competitive Landscape"),
        anchor("sec5"),
        Paragraph("5. Competitive Landscape", ST["section_h1"]),
        hr(),
        Paragraph("BYD overtook Tesla in quarterly BEV sales in late 2023. Intense competition from Chinese OEMs continues.", ST["body"]),
        PageBreak(),
    ]

    # ==================== REFERENCES ====================
    story += [
        Bookmark("sec6", "6. References"),
        anchor("sec6"),
        Paragraph("6. References", ST["section_h1"]),
        hr(),
        Paragraph("• Tesla, Inc. SEC 10-K Filings (2023–2024)", ST["bullet"]),
        Paragraph("• Google Patents Database", ST["bullet"]),
        Paragraph("• EV-Volumes.com and Counterpoint Research", ST["bullet"]),
        Paragraph("• OpenClaw R&D Intelligence Pipeline v2.1", ST["bullet"]),
        sp(20),
        hr(2),
        Paragraph("End of Report", ST["caption"])
    ]

    doc.build(story, onFirstPage=nb.footer, onLaterPages=nb.footer)
    print(f"[export_report] PDF written → {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Tesla R&D Report PDF")
    parser.add_argument("--output", default="tesla_model_y_report.pdf", help="Output PDF filename")
    args = parser.parse_args()
    build_pdf(args.output)

#!/usr/bin/env python3
"""
export_report.py — Tesla R&D Intelligence Report Generator (Exact Match Style)
Generates a professional PDF matching the provided Tesla Model Y sample.
Features:
- Professional cover page
- Clickable Table of Contents with internal navigation
- PDF bookmarks for sidebar navigation
- Clean tables, no overlapping text
- References section
"""

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, HRFlowable
)

# =============================================================================
# Configuration & Styles (Tesla-like blue theme)
# =============================================================================
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_WIDTH = PAGE_W - 2 * MARGIN

BLUE = colors.HexColor("#0a3d8f")
DARK = colors.HexColor("#1f2a44")
GRAY = colors.HexColor("#555555")
LIGHT_GRAY = colors.HexColor("#e5e5e5")

_styles = getSampleStyleSheet()

STYLE_TITLE = ParagraphStyle("Title", parent=_styles["Title"], fontName="Helvetica-Bold",
                             fontSize=26, leading=30, textColor=BLUE, alignment=TA_CENTER, spaceAfter=8)
STYLE_SUBTITLE = ParagraphStyle("Subtitle", parent=_styles["Normal"], fontSize=14,
                                leading=18, textColor=DARK, alignment=TA_CENTER, spaceAfter=40)
STYLE_H1 = ParagraphStyle("H1", parent=_styles["Heading1"], fontName="Helvetica-Bold",
                          fontSize=15, leading=20, textColor=BLUE, spaceBefore=18, spaceAfter=10)
STYLE_H2 = ParagraphStyle("H2", parent=_styles["Heading2"], fontName="Helvetica-Bold",
                          fontSize=12.5, leading=16, textColor=DARK, spaceBefore=12, spaceAfter=6)
STYLE_BODY = ParagraphStyle("Body", parent=_styles["Normal"], fontName="Helvetica",
                            fontSize=10.2, leading=14.5, textColor=DARK, spaceAfter=7)
STYLE_TOC = ParagraphStyle("TOC", parent=STYLE_BODY, fontSize=12, leading=20, textColor=BLUE)

# =============================================================================
# Bookmark Flowable for Clickable TOC & PDF Outline
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

# =============================================================================
# Table Helpers
# =============================================================================
def kv_table(pairs):
    rows = [[Paragraph(k, STYLE_BODY), Paragraph(v, STYLE_BODY)] for k, v in pairs if v]
    if not rows:
        return None
    t = Table(rows, colWidths=[65*mm, CONTENT_WIDTH - 65*mm])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#f4f6f9")),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    return t

def data_table(headers, rows):
    if not rows:
        return None
    header_style = ParagraphStyle("Header", parent=STYLE_BODY, fontName="Helvetica-Bold", fontSize=10, textColor=colors.white)
    hcells = [Paragraph(h, header_style) for h in headers]
    body_rows = [[Paragraph(str(cell), STYLE_BODY) for cell in row] for row in rows]
    t = Table([hcells] + body_rows, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BLUE),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    return t

# =============================================================================
# Main PDF Builder
# =============================================================================
def build_pdf(output_path="tesla_model_y_report.pdf"):
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN
    )

    story = []

    # ==================== COVER PAGE ====================
    story.append(Spacer(1, 40*mm))
    story.append(Paragraph("R&amp;D Intelligence Report", STYLE_TITLE))
    story.append(Paragraph("Tesla, Inc. - Model Y", STYLE_SUBTITLE))
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("A comprehensive overview of company profile, financials, intellectual property, market trends, competitive landscape and research literature.", STYLE_BODY))
    story.append(Spacer(1, 20*mm))
    story.append(Paragraph("Pipeline: rnd-company-intelligence v2.1 · Generated 2026-06-22", STYLE_BODY))
    story.append(PageBreak())

    # ==================== TABLE OF CONTENTS ====================
    story.append(Bookmark("toc", "Table of Contents"))
    story.append(anchor("toc"))
    story.append(Paragraph("Table of Contents", STYLE_H1))
    story.append(Spacer(1, 8*mm))

    toc_items = [
        ("1", "Company & Product Overview", "sec1"),
        ("2", "Financial Overview", "sec2"),
        ("3", "Patents & Intellectual Property", "sec3"),
        ("4", "Market Trends & Demand Signals", "sec4"),
        ("5", "Competitive Landscape", "sec5"),
        ("6", "References", "sec6")
    ]

    for num, title, key in toc_items:
        story.append(Paragraph(f'<link href="#{key}">{num}. {title}</link>', STYLE_TOC))
        story.append(Spacer(1, 4*mm))
    story.append(PageBreak())

    # ==================== SECTION 1 ====================
    story.extend([
        Bookmark("sec1", "1. Company & Product Overview"),
        anchor("sec1"),
        Paragraph("1. Company & Product Overview", STYLE_H1),
        HRFlowable(width="100%", thickness=1.2, color=GRAY),
        Paragraph("Tesla, Inc. is an American multinational automotive and clean-energy company headquartered in Austin, Texas. Founded in July 2003...", STYLE_BODY),
        Spacer(1, 8*mm),
        kv_table([
            ("Legal name", "Tesla, Inc."),
            ("Founded", "July 1, 2003"),
            ("HQ", "13101 Tesla Road, Austin, Texas 78725, USA"),
            ("Employees", "140,473 (as of December 31, 2023)"),
            ("Website", "https://www.tesla.com")
        ])
    ])
    story.append(PageBreak())

    # ==================== SECTION 2 ====================
    story.extend([
        Bookmark("sec2", "2. Financial Overview"),
        anchor("sec2"),
        Paragraph("2. Financial Overview", STYLE_H1),
        HRFlowable(width="100%", thickness=1.2, color=GRAY),
        Paragraph("FY2023 revenue reached $96.77 billion (+19% YoY) with 1,808,581 vehicles delivered.", STYLE_BODY),
        Spacer(1, 6*mm),
        data_table(["Metric", "Value"], [
            ["Total Revenue", "$96.77B"],
            ["Net Income (GAAP)", "$14.997B"],
            ["Vehicle Deliveries", "1,808,581"],
            ["Automotive Gross Margin", "18.2%"]
        ])
    ])
    story.append(PageBreak())

    # ==================== SECTION 3 ====================
    story.extend([
        Bookmark("sec3", "3. Patents & Intellectual Property"),
        anchor("sec3"),
        Paragraph("3. Patents & Intellectual Property", STYLE_H1),
        HRFlowable(width="100%", thickness=1.2, color=GRAY),
        Paragraph("Tesla holds 3,000+ patents globally. Key technologies include 4680 cells, structural battery packs, and FSD neural networks.", STYLE_BODY),
        Spacer(1, 6*mm),
        Paragraph("Notable Patents:", STYLE_H2),
        Paragraph("• Cell with a tabless electrode (US20200287202A1)", STYLE_BODY),
        Paragraph("• Structural battery pack with shear panels", STYLE_BODY),
        Paragraph("• Gigacasting / Single-piece casting", STYLE_BODY),
    ])
    story.append(PageBreak())

    # ==================== SECTION 4 ====================
    story.extend([
        Bookmark("sec4", "4. Market Trends & Demand Signals"),
        anchor("sec4"),
        Paragraph("4. Market Trends & Demand Signals", STYLE_H1),
        HRFlowable(width="100%", thickness=1.2, color=GRAY),
        Paragraph("Model Y was the world’s best-selling vehicle in 2023. Global EV sales continue to grow despite headwinds.", STYLE_BODY),
    ])
    story.append(PageBreak())

    # ==================== SECTION 5 ====================
    story.extend([
        Bookmark("sec5", "5. Competitive Landscape"),
        anchor("sec5"),
        Paragraph("5. Competitive Landscape", STYLE_H1),
        HRFlowable(width="100%", thickness=1.2, color=GRAY),
        Paragraph("BYD overtook Tesla in quarterly BEV sales in late 2023. Intense competition from Chinese OEMs continues.", STYLE_BODY),
    ])
    story.append(PageBreak())

    # ==================== REFERENCES ====================
    story.extend([
        Bookmark("sec6", "6. References"),
        anchor("sec6"),
        Paragraph("6. References", STYLE_H1),
        HRFlowable(width="100%", thickness=1.2, color=GRAY),
        Paragraph("• Tesla, Inc. SEC 10-K Filings (2023–2024)", STYLE_BODY),
        Paragraph("• Google Patents Database", STYLE_BODY),
        Paragraph("• EV-Volumes.com and Counterpoint Research", STYLE_BODY),
        Paragraph("• OpenClaw R&D Intelligence Pipeline v2.1", STYLE_BODY),
    ])

    doc.build(story)
    print(f"✅ PDF generated successfully: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Tesla R&D Report PDF")
    parser.add_argument("--output", default="tesla_model_y_report.pdf", help="Output PDF filename")
    args = parser.parse_args()
    build_pdf(args.output)

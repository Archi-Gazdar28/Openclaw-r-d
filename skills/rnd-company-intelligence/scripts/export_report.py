#!/usr/bin/env python3
"""
export_report.py — Tesla R&D Intelligence Report Generator (Exact Match Style)
Generates a professional PDF matching the typography and dataset layout
of the provided Tesla Model Y source text, complete with automated data charts.

Features:
- Minimalist plain black/white/grey color palette (Grayscale branding)
- Completely synchronized 8-Section Table of Contents with working internal hyperlinks
- Dynamic inline Matplotlib vector graph generation matching the text dataset
- Integrated PDF Bookmarks for native sidebar document outlines
- Strict grid table margins, zero text collisions, and custom itemized listings
- Dynamic single-pass footer construction with dynamic canvas page counts
"""

import argparse
import os
import sys
from pathlib import Path

# Set Matplotlib backend to headless Agg prior to importing pyplot
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, HRFlowable, Image
)

# =============================================================================
# Colour Palette Matrix (Plain black/white/grey strictly from File 1 rules)
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
# Structural Style Sheet Blueprint
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
        "toc_item": s("toc_item",
            fontName="Helvetica", fontSize=10,
            leading=15, textColor=C_DARK, leftIndent=10),
    }

ST = build_styles()

# =============================================================================
# Document Flow & Navigational Meta-Elements
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
# Automated Dynamic Chart Generation (Grayscale / Minimalist)
# =============================================================================
def generate_report_charts():
    """Generates the text matching figures and saves them as local temp files."""
    # Apply global clean layout configs
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Helvetica', 'Arial']
    plt.rcParams['text.color'] = '#2d2d2d'
    plt.rcParams['axes.labelcolor'] = '#2d2d2d'
    plt.rcParams['xtick.color'] = '#555555'
    plt.rcParams['ytick.color'] = '#555555'

    # Chart 1: Tesla Annual Revenue
    years = ['2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024E']
    revenue = [11.8, 21.5, 24.6, 31.5, 53.8, 81.5, 96.8, 97.7]
    fig, ax = plt.subplots(figsize=(6.5, 2.3))
    bars = ax.bar(years, revenue, color='#2d2d2d', edgecolor='#1a1a1a', width=0.6)
    ax.set_ylabel('Revenue ($B)', fontsize=9)
    ax.set_title('Tesla Annual Revenue (USD)', fontsize=10, fontweight='bold', pad=8)
    ax.grid(axis='y', linestyle=':', alpha=0.6, color='#cccccc')
    ax.set_axisbelow(True)
    for bar in bars:
        yval = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, yval + 2, f"${yval}B", ha='center', va='bottom', fontsize=7.5)
    ax.set_ylim(0, 115)
    plt.tight_layout()
    plt.savefig("chart_revenue.png", dpi=300)
    plt.close()

    # Chart 2: Annual Vehicle Deliveries
    deliv_years = ['2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024']
    deliveries = [103, 246, 368, 500, 936, 1314, 1809, 1789]
    fig, ax = plt.subplots(figsize=(6.5, 2.3))
    ax.plot(deliv_years, deliveries, color='#1a1a1a', marker='o', linewidth=2, markersize=5)
    ax.fill_between(deliv_years, deliveries, color='#f5f5f5', alpha=1.0)
    ax.set_ylabel('Vehicles (Thousands)', fontsize=9)
    ax.set_title('Tesla Annual Vehicle Deliveries', fontsize=10, fontweight='bold', pad=8)
    ax.grid(axis='y', linestyle=':', alpha=0.6, color='#cccccc')
    for i, txt in enumerate(deliveries):
        ax.annotate(f"{txt}K", (deliv_years[i], deliveries[i]), textcoords="offset points", xytext=(0,6), ha='center', fontsize=7.5, fontweight='bold')
    ax.set_ylim(0, 2050)
    plt.tight_layout()
    plt.savefig("chart_deliveries.png", dpi=300)
    plt.close()

    # Chart 3: Global BEV Market Share 2024
    companies = ['BYD', 'Tesla', 'VW Group', 'SAIC', 'Geely', 'Hyundai-Kia', 'BMW Group', 'Stellantis']
    shares = [21.1, 17.6, 5.8, 5.0, 4.5, 3.8, 3.4, 2.9]
    fig, ax = plt.subplots(figsize=(6.5, 2.5))
    y_pos = range(len(companies))
    ax.barh(y_pos, shares, color=['#1a1a1a' if x in ['BYD','Tesla'] else '#555555' for x in companies], edgecolor='#1a1a1a', height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(companies, fontsize=8.5)
    ax.invert_yaxis()  # Top-down tracking
    ax.set_xlabel('Share of global BEV sales (%)', fontsize=9)
    ax.set_title('Global BEV Market Share — 2024 (Top Players)', fontsize=10, fontweight='bold', pad=8)
    ax.grid(axis='x', linestyle=':', alpha=0.6, color='#cccccc')
    ax.set_axisbelow(True)
    for i, v in enumerate(shares):
        ax.text(v + 0.5, i, f"{v}%", va='center', fontsize=8, fontweight='bold')
    ax.set_xlim(0, 25)
    plt.tight_layout()
    plt.savefig("chart_market_share.png", dpi=300)
    plt.close()

# =============================================================================
# Table System Format Mechanics (File 1 Alternating Layout Rules)
# =============================================================================
def kv_table(pairs, label_width=4.5 * cm):
    rows = [[Paragraph(k, ST["label"]), Paragraph(v, ST["value"])] for k, v in pairs if v]
    if not rows:
        return None
    cw = [label_width, CONTENT_WIDTH - label_width]
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

def data_table(headers, rows, custom_widths=None):
    if not rows:
        return None
    header_row = [Paragraph(h, ST["label"]) for h in headers]
    body_rows  = [[Paragraph(str(cell), ST["value"]) for cell in row] for row in rows]
    
    if custom_widths:
        cw = custom_widths
    else:
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
# Custom Canvas Footer Engine
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
# Complete Structural Report Constructor
# =============================================================================
def build_pdf(output_path="tesla_model_y_report.pdf"):
    # Trigger image pre-generation
    generate_report_charts()

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
        ("6", "Research & Academic Literature", "sec6"),
        ("7", "SWOT Analysis", "sec7"),
        ("8", "Data Quality & Sources", "sec8"),
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
        Paragraph("<b>Executive Summary:</b> Tesla, Inc. (NASDAQ: TSLA) is an American multinational automotive and clean-energy company founded on July 1, 2003 by Martin Eberhard and Marc Tarpenning, with Elon Musk joining as Chairman and lead investor in February 2004 and becoming CEO in October 2008. Tesla is the world's most valuable automaker by market capitalization (~$800B-$1.1T) and was the largest BEV manufacturer globally until being overtaken on quarterly volume by BYD in Q4 2023. Tesla's flagship Model Y compact SUV became the world's #1 best-selling vehicle of any powertrain in 2023—the first electric vehicle ever to top global sales charts.", ST["body"]),
        Paragraph("Tesla operates six Gigafactories globally (Nevada, New York, Shanghai, Berlin, Texas, and Mexico) and is vertically integrated across battery cell chemistry, electric motors, vehicle software, charging infrastructure, AI training hardware (Dojo D1 chip), and increasingly raw materials (Nevada lithium refinery operational 2025). Tesla's NACS connector became the de facto US charging standard during 2023-2024 after adoption by Ford, GM, Rivian, Hyundai-Kia, Volvo, Polestar, Mercedes-Benz, BMW, Honda, Toyota, Nissan, and Stellantis.", ST["body"]),
        Paragraph("The company holds $29.1B in cash and investments, generated $4.4B of free cash flow in 2023, and continues to lead the industry in software/OTA capabilities - including the transformative FSD V12 end-to-end neural network released in March 2024. However, FY2024 marked Tesla's first annual delivery decline (1,789,226 units vs. 1,808,581 in 2023), reflecting aggressive price cuts that began in January 2023 to defend market share against Chinese competition. Automotive gross margin (excluding regulatory credits) compressed from 30%+ in 2022 to approximately 16% by mid-2024.", ST["body"]),
        sp(6),
    ]
    
    t1 = kv_table([
        ("Legal name", "Tesla, Inc."),
        ("Website", "https://www.tesla.com"),
        ("Headquarters", "13101 Tesla Road, Austin, Texas 78725, USA (relocated from Palo Alto, California in December 2021)"),
        ("Founded", "July 1, 2003"),
        ("Stock ticker", "NASDAQ: TSLA (member of S&P 500 since December 2020)"),
        ("Market cap", "Approximately $800B to $1.1T depending on market conditions (mid-2024 through 2025 range)"),
        ("Employees (FY23)", "140,473 (as of December 31, 2023, per 10-K filing)")
    ], label_width=4.5*cm)
    if t1: story.append(t1)
    
    story += [
        sp(6),
        Paragraph("Key Leadership", ST["section_h2"]),
    ]
    t1_leaders = data_table(["Name", "Role/Description"], [
        ["Elon Musk", "CEO, Product Architect & Chairman; joined 2004 as Chairman, became CEO in October 2008."],
        ["Vaibhav Taneja", "Chief Financial Officer (CFO) since August 2023; previously Corporate Controller."],
        ["Tom Zhu", "Senior Vice President, Automotive - Global Manufacturing & Sales."],
        ["Robyn Denholm", "Chair of the Board of Directors since November 2018, replacing Elon Musk per SEC settlement."],
        ["Lars Moravy", "Vice President, Vehicle Engineering; leads vehicle program development including Cybertruck."],
        ["Franz von Holzhausen", "Chief Designer since 2008. Responsible for Model S, 3, X, Y, and Cybertruck styling."],
        ["Ashok Elluswamy", "Director of Autopilot Software; leads FSD neural network development."],
        ["Milan Kovac", "Director of Engineering, Optimus humanoid robot program."],
        ["Mike Snyder", "Vice President of Energy Engineering; oversees Megapack and Powerwall grid-scale deployments."]
    ], custom_widths=[4.5*cm, CONTENT_WIDTH - 4.5*cm])
    if t1_leaders: story.append(t1_leaders)

    story += [
        sp(6),
        Paragraph("Manufacturing Footprint (Gigafactories)", ST["section_h2"]),
        Paragraph("• <b>Gigafactory Nevada (Reno, NV):</b> Opened 2016, joint venture with Panasonic. Produces 2170 battery cells, battery packs, drive units, Semi truck final assembly. Largest building in the world by footprint (5.4M sq ft).", ST["bullet"]),
        Paragraph("• <b>Gigafactory New York (Buffalo, NY):</b> Opened 2017. Originally for Solar Roof; now also produces Supercharger components and Autopilot/Dojo hardware. ~1,500 employees.", ST["bullet"]),
        Paragraph("• <b>Gigafactory Shanghai (China):</b> Opened January 2020. Tesla's first wholly-owned plant outside the US. Produces Model 3/Y. Highest output per square meter globally (~950k capacity).", ST["bullet"]),
        Paragraph("• <b>Gigafactory Berlin-Brandenburg (Germany):</b> Opened March 2022. Produces Model Y for European market. Current capacity ~500,000 vehicles/year.", ST["bullet"]),
        Paragraph("• <b>Gigafactory Texas (Austin, TX):</b> Opened April 2022. Global headquarters and main US Model Y plant. Also produces Cybertruck, 4680 cells, and serves as main R&D campus.", ST["bullet"]),
        Paragraph("• <b>Gigafactory Mexico (Santa Catarina):</b> Announced March 2023 but construction paused in mid-2024 pending trade policy clarity.", ST["bullet"]),
    ]
    story.append(PageBreak())

    # ==================== SECTION 2 ====================
    story += [
        Bookmark("sec2", "2. Financial Overview"),
        anchor("sec2"),
        Paragraph("2. Financial Overview", ST["section_h1"]),
        hr(),
        Paragraph("Tesla has grown revenue ~4x from $24.6B (2019) to $96.8B (2023), with a CAGR of approximately 41% over the four-year window. Vehicle deliveries grew nearly 5x over the same period, hitting 1.81M units in 2023. FY2024 delivery numbers came in at 1.79M, the first annual decline in Tesla's history, reflecting heavy price cuts and intensifying global competition.", ST["body"]),
        sp(4),
    ]

    # Append Generated Financial Vector Graph Blocks
    if os.path.exists("chart_revenue.png"):
        story += [Image("chart_revenue.png", width=CONTENT_WIDTH, height=2.3*cm), sp(2)]
    if os.path.exists("chart_deliveries.png"):
        story += [Image("chart_deliveries.png", width=CONTENT_WIDTH, height=2.3*cm), sp(4)]

    story += [
        Paragraph("Key FY2023 Financial Metrics", ST["section_h2"]),
    ]
    
    t2_metrics = kv_table([
        ("Total revenue", "$96.77B (+19% YoY)"),
        ("Gross margin", "18.2% (down from 25.6% in 2022; price cuts drove compression)"),
        ("Auto GM ex-credits", "16.3% (industry benchmark)"),
        ("Operating margin", "9.2% (down from 16.8% in 2022)"),
        ("Net income (GAAP)", "$14.997B GAAP (includes one-time $5.9B tax benefit from deferred valuation allowance reversal); adjusted ~$10.0B"),
        ("Free cash flow", "$4.4B (down from $7.6B in 2022)"),
        ("Cash & equivalents", "$29.1B cash + investments at year-end"),
        ("R&D spend", "$3.969B (~4.1% of revenue, significantly higher than industry average of ~3.5%)"),
        ("Capex 2023", "$8.9B (Austin, Berlin expansion, 4680, Cybertruck tooling)"),
        ("EPS (GAAP diluted)", "$4.30 (GAAP, including one-time tax benefit)")
    ], label_width=4.5*cm)
    if t2_metrics: story.append(t2_metrics)

    story += [
        sp(6),
        Paragraph("FY2023 Revenue Mix by Segment", ST["section_h2"]),
    ]
    t2_mix = data_table(["Segment", "Revenue", "% of Total"], [
        ["Automotive sales", "$78.5B", "81.1%"],
        ["Automotive regulatory credits", "$1.79B", "1.9%"],
        ["Automotive leasing", "$2.12B", "2.2%"],
        ["Energy generation and storage", "$6.04B", "6.2%"],
        ["Services and other", "$8.32B", "8.6%"]
    ])
    if t2_mix: story.append(t2_mix)

    story += [
        sp(6),
        Paragraph("FY2023 Revenue by Geography", ST["section_h2"]),
    ]
    t2_geo = data_table(["Region", "Revenue", "% of Total"], [
        ["United States", "$45.0B", "46.5%"],
        ["China", "$21.7B", "22.4%"],
        ["Other International (incl. Europe)", "$30.0B", "31.1%"]
    ])
    if t2_geo: story.append(t2_geo)
    story.append(PageBreak())

    # ==================== SECTION 3 ====================
    story += [
        Bookmark("sec3", "3. Patents & Intellectual Property"),
        anchor("sec3"),
        Paragraph("3. Patents & Intellectual Property", ST["section_h1"]),
        hr(),
        Paragraph("Tesla holds 3,000+ patents and patent applications globally spanning battery cell chemistry, electric motors, autonomous driving, charging infrastructure, manufacturing processes, and energy software. Despite famously opening its portfolio via the June 2014 open-patent pledge ('All Our Patent Are Belong To You'), Tesla continues to file aggressively, averaging 200-400 applications per year. Recent focus spans 4680 cells, Optimus actuators, Dojo training architecture, and end-to-end vision models.", ST["body"]),
        sp(4),
        Paragraph("Strategic Innovations & Patents Portfolio", ST["section_h2"]),
    ]
    
    patents_data = [
        ("Cell with a tabless electrode", "US20200287202A1", "Enables higher current capability and reduced internal resistance. Forms the baseline of the 4680 cell design to deliver 6x more power output."),
        ("Structural battery pack with shear panels", "US20210107360A1", "Cells are bonded directly into the structure using polyurethane adhesive, replacing the floor pan entirely. Reduces mass by 10% and updates stiffness by 18%."),
        ("Single-piece casting rear underbody", "US20210245814A1", "Gigacasting design utilizing a custom aluminum alloy ('Tesla Alloy') that cuts out 70+ parts and eliminates post-cast heat treatment cycles."),
        ("Vehicle summon to a target", "US20190332106A1", "Smart Summon mapping/path-planning architectures allowing the vehicle to navigate private driveways and low-speed parking spaces via app control."),
        ("Dry electrode coating method", "US20210408515A1", "Solvent-free calendar processing inherited via the Maxwell acquisition. Removes energy-intensive drying ovens from factories to hit a target 56% reduction in $/kWh."),
        ("Heat pump with octovalve", "US20200376927A1", "Central thermal grid looping battery, motor, and cabin via an 8-port valve. Boosts sub-freezing sub-zero operational driving range metrics by 10-30%."),
        ("Neural network for perception", "US20220237405A1", "Multi-camera HydraNet layout outputting a unified vector space representation directly from 8 visual feeds without radar or LiDAR infrastructure."),
        ("Optimus robot actuator system", "US20230289437A1", "Integrated custom motor-gearbox-encoder assembly using localized harmonic drives across 40+ dynamic joints to scale degrees of freedom."),
        ("Unboxed manufacturing process", "US20230069437A1", "Parallel vehicle manufacturing flow modules (front, rear, side panels) snapped together in final sequence to lower footprints by 40%.")
    ]
    
    for title_pat, code_pat, desc_pat in patents_data:
        story += [
            Paragraph(f"<b>{title_pat}</b> ({code_pat})", ST["section_h3"]),
            Paragraph(desc_pat, ST["body"]),
            sp(2)
        ]
        
    story.append(PageBreak())

    # ==================== SECTION 4 ====================
    story += [
        Bookmark("sec4", "4. Market Trends & Demand Signals"),
        anchor("sec4"),
        Paragraph("4. Market Trends & Demand Signals", ST["section_h1"]),
        hr(),
        Paragraph("Global plug-in vehicle sales reached approximately 17.1 million units worldwide in 2024 (~10.8M BEVs + 6.3M PHEVs), showing ongoing growth though hypergrowth speed from 2021-2022 has leveled off. Tesla's current slice sits around 12-14% of the global BEV market space due to BYD's aggressive volume expansions.", ST["body"]),
        Paragraph("While the Model Y clinched the title of the world's #1 best-selling automobile of any powertrain setup in 2023 with 1.23M sales, it shifted to #2 in 2024 as alternative powertrains regained traction. Headwinds include steep retail pricing cuts (dropping base MSRP variants from a 2022 peak of $65,990 down to ~$44,990 by mid-2024), shifting policy subsidy grids across the EU and US, and competitive price positioning from Chinese manufacturers.", ST["body"]),
        sp(4),
        Paragraph("Top Accelerating Query Signals", ST["section_h2"]),
        Paragraph("• <i>Model Y Juniper 2025 / Refresh Interior:</i> High search tracking surrounding the visual updates.", ST["bullet"]),
        Paragraph("• <i>Tesla Model Y NACS adapter:</i> Technical discovery queries following universal standard switches.", ST["bullet"]),
        Paragraph("• <i>Model Y BYD comparison:</i> Consumer cross-shopping indexing against localized products.", ST["bullet"]),
        PageBreak(),
    ]

    # ==================== SECTION 5 ====================
    story += [
        Bookmark("sec5", "5. Competitive Landscape"),
        anchor("sec5"),
        Paragraph("5. Competitive Landscape", ST["section_h1"]),
        hr(),
        Paragraph("Chinese developers led by BYD held over half of international BEV deliveries through 2024. Concurrently, legacy Western automakers continue closing technical execution gaps across scalable premium platform lines.", ST["body"]),
        sp(4),
    ]

    # Append Generated Horizontal Bar Chart for Market Share Breakdown
    if os.path.exists("chart_market_share.png"):
        story += [Image("chart_market_share.png", width=CONTENT_WIDTH, height=2.5*cm), sp(4)]
    
    t5_share = data_table(["Company Rank", "Share %", "BEV Volume (Millions)"], [
        ["1. BYD", "21.1%", "1.76"],
        ["2. Tesla", "17.6%", "1.79"],
        ["3. Volkswagen Group", "5.8%", "0.74"],
        ["4. SAIC", "5.0%", "0.65"],
        ["5. Geely Holding", "4.5%", "0.58"],
        ["6. Hyundai-Kia", "3.8%", "0.49"],
        ["7. BMW Group", "3.4%", "0.44"],
        ["8. Stellantis", "2.9%", "0.37"]
    ])
    if t5_share: story.append(t5_share)
    
    story += [
        sp(6),
        Paragraph("Detailed Competitor Profiles", ST["section_h2"]),
        Paragraph("• <b>BYD Company Limited:</b> Fully vertically-integrated NEV maker. Produces internal Blade LFP battery stacks, custom logic chip systems, and assemblies. Overtook Tesla on pure BEV volume late 2023.", ST["bullet"]),
        Paragraph("• <b>Volkswagen Group:</b> Scaled via multi-brand MEB and premium PPE EV architectures. Invested $5B into a Rivian joint software architecture partnership to upgrade foundational software systems.", ST["bullet"]),
        Paragraph("• <b>Hyundai Motor Group:</b> Technology leader utilizing the native 800V E-GMP layout pattern. Supports high-power 350 kW DC charging profiles, rivaling Tesla's Supercharger charge cycle performance.", ST["bullet"]),
        Paragraph("• <b>Rivian Automotive:</b> Formed around lifestyle trucks/SUVs (R1T/R1S). Launching the mass-market R2 platform layer ($45k target) by 2026 to open higher volume categories.", ST["bullet"]),
        PageBreak(),
    ]

    # ==================== SECTION 6 ====================
    story += [
        Bookmark("sec6", "6. Research & Academic Literature"),
        anchor("sec6"),
        Paragraph("6. Research & Academic Literature", ST["section_h1"]),
        hr(),
        Paragraph("The operational scale and technology stack at Tesla remain central subjects across alternative transportation, energy storage, and automation research. The bibliography matrix below presents high-citation literature investigating these systems:", ST["body"]),
        sp(4),
    ]
    
    ref_papers = [
        ("End-to-End Learning for Self-Driving Cars", "Bojarski, M. et al. (NVIDIA), 2016", "4,500x", "Foundational analysis demonstrating direct deep learning control from pixels to steering inputs. Validates FSD V12's network structure."),
        ("Effects of battery manufacturing on lifecycle emissions", "Romare, M. & Dahllöf, L. (IVL), 2017", "1,820x", "Establishes baseline battery processing emission values (150-200 kg CO2e/kWh) used to benchmark sustainability indices."),
        ("Lithium-ion battery supply chain considerations", "Olivetti, E. A. et al. (MIT), 2017", "1,150x", "Details critical raw material supply risks. Documents Tesla's early vertical integration defense moves."),
        ("A review of battery management systems for EVs", "Xiong, R. et al., 2020", "780x", "Evaluates BMS architectures, highlighting Tesla's distributed layout monitoring method as an industry reference benchmark."),
        ("Tesla and the global EV market: Business innovation", "Mangram, M. E., 2012", "612x", "Early analysis mapping the direct-to-consumer delivery infrastructure model and structural software OTA updates."),
        ("Comparing Tesla 4680, 2170 and 18650 cell architectures", "Ank, M. et al., 2023", "215x", "Teardown data verifying the tabless internal configurations yield 40% thermal optimization improvements, despite lower initial density matrices.")
    ]
    
    for title_p, author_p, citations_p, impact_p in ref_papers:
        story += [
            Paragraph(f"<b>{title_p}</b>", ST["section_h3"]),
            Paragraph(f"<i>Author/Source:</i> {author_p}  ·  <b>Citations:</b> {citations_p}", ST["body"]),
            Paragraph(f"<i>Core Insight:</i> {impact_p}", ST["body"]),
            sp(4)
        ]
        
    story.append(PageBreak())

    # ==================== SECTION 7 ====================
    story += [
        Bookmark("sec7", "7. SWOT Analysis"),
        anchor("sec7"),
        Paragraph("7. SWOT Analysis", ST["section_h1"]),
        hr(),
        Paragraph("<b>Strengths</b>", ST["section_h2"]),
        Paragraph("• Market capitalization dominance ($800B-$1.1T) securing capital market access channels.", ST["bullet"]),
        Paragraph("• Advanced vertical supply line links handling cell processing, drive components, and refinery links.", ST["bullet"]),
        Paragraph("• Massive Supercharger footprints (60k+ global stalls) establishing NACS as the de facto standard.", ST["bullet"]),
        
        Paragraph("<b>Weaknesses</b>", ST["section_h2"]),
        Paragraph("• Product lineup age profiles requiring platform updates (Model Y Juniper slated early 2025).", ST["bullet"]),
        Paragraph("• High repair complexity cost profiles stemming from single-piece aluminum casting structures.", ST["bullet"]),
        Paragraph("• Corporate governance challenges and key-person focus concentration around Elon Musk.", ST["bullet"]),
        
        Paragraph("<b>Opportunities</b>", ST["section_h2"]),
        Paragraph("• Launching the next-generation affordable vehicle architecture platform ($25k 'Model 2' / Redwood).", ST["bullet"]),
        Paragraph("• Rapid utility storage scaling, tracking 90%+ year-over-year Megapack production growth.", ST["bullet"]),
        Paragraph("• Geographic expansion steps via active manufacturing entries within regions like India.", ST["bullet"]),
        
        Paragraph("<b>Threats</b>", ST["section_h2"]),
        Paragraph("• Deep manufacturing structural cost advantages held by private vertically-integrated Chinese OEMs.", ST["bullet"]),
        Paragraph("• Price-war margin compressions lowering automotive margins down toward ~16% by mid-2024.", ST["bullet"]),
        Paragraph("• Evolving regulatory challenges and active trade tariff implementations (e.g., EU model import duties).", ST["bullet"]),
        PageBreak()
    ]

    # ==================== SECTION 8 ====================
    story += [
        Bookmark("sec8", "8. Data Quality & Sources"),
        anchor("sec8"),
        Paragraph("8. Data Quality & Sources", ST["section_h1"]),
        hr(),
        Paragraph("<b>Confidence Index: High.</b> Data synthesis leans on audited financial documentation, regulatory filings, corporate presentation releases, and authenticated global patent indices. Country-level volume parsing profiles display a standard variance of ±10% reflecting mixed registry tracking systems.", ST["body"]),
        sp(4),
        Paragraph("Sources Consulted Matrix", ST["section_h2"]),
        Paragraph("• <i>Tesla Corporate Documentation:</i> Forms 10-K (FY2023), 10-Q (FY2024), and official IR production releases.", ST["bullet"]),
        Paragraph("• <i>Patent Databases:</i> USPTO Assignee Indexes and Google Patents Global Database tracking matrices.", ST["bullet"]),
        Paragraph("• <i>Industry Tracking Groups:</i> Counterpoint Research EV indexes, IEA Outlook tables, and EV-Volumes data repositories.", ST["bullet"]),
        Paragraph("• <i>Safety System Databases:</i> NHTSA OTI/ODI active safety recall records.", ST["bullet"]),
        sp(20),
        hr(2),
        Paragraph("End of Report", ST["caption"])
    ]

    # Render Document utilizing dynamic page-tracking canvas callbacks
    doc.build(story, onFirstPage=nb.footer, onLaterPages=nb.footer)
    
    # Cleanup chart images post-render to keep workspace clean
    for path in ["chart_revenue.png", "chart_deliveries.png", "chart_market_share.png"]:
        if os.path.exists(path):
            os.remove(path)
            
    print(f"[export_report] PDF successfully written to -> {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Complete Tesla R&D Report PDF")
    parser.add_argument("--output", default="tesla_model_y_report.pdf", help="Output PDF filename")
    args = parser.parse_args()
    build_pdf(args.output)

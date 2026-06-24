#!/usr/bin/env python3
"""
dhf_export.py — Integrated DHF Builder + PDF Exporter

Generates a complete Design History File (DHF) as a professional PDF
from a device intake JSON, with embedded Matplotlib charts/diagrams.

No external diagram subprocess required — all visuals generated inline.

Usage:
    python dhf_export.py --intake intake.json --out DHF_Report.pdf
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import date

# ── Matplotlib headless ────────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches mpatches
import numpy as np

# ── ReportLab ──────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, HRFlowable, Image, KeepTogether
)

# ═══════════════════════════════════════════════════════════════════════════
# COLOUR PALETTE
# ═══════════════════════════════════════════════════════════════════════════
C_BLACK   = colors.HexColor("#0f1923")
C_DARK    = colors.HexColor("#1e2d3d")
C_NAVY    = colors.HexColor("#1b3a5c")
C_BLUE    = colors.HexColor("#2563a8")
C_TEAL    = colors.HexColor("#0d9488")
C_RED     = colors.HexColor("#c0392b")
C_AMBER   = colors.HexColor("#d97706")
C_GREEN   = colors.HexColor("#16a34a")
C_MID     = colors.HexColor("#4b5563")
C_LIGHT   = colors.HexColor("#9ca3af")
C_RULE    = colors.HexColor("#d1d5db")
C_SHADE   = colors.HexColor("#f3f4f6")
C_SHADE2  = colors.HexColor("#e0f2fe")
C_WHITE   = colors.white

PAGE_W, PAGE_H = A4
MARGIN        = 2.0 * cm
CONTENT_W     = PAGE_W - 2 * MARGIN

DRAFT_NOTICE = (
    "DRAFT — AI-ASSISTED CONTENT. NOT FOR REGULATORY SUBMISSION WITHOUT "
    "SME REVIEW, RESPONSIBLE-PERSON APPROVAL, AND CSV-VALIDATED RELEASE "
    "PER 21 CFR PART 11."
)

# ═══════════════════════════════════════════════════════════════════════════
# STYLE SHEET
# ═══════════════════════════════════════════════════════════════════════════
def _s(name, **kw):
    return ParagraphStyle(name, **kw)

ST = {
    "cover_title": _s("cover_title",
        fontName="Helvetica-Bold", fontSize=26, leading=32,
        textColor=C_WHITE, alignment=TA_CENTER),
    "cover_sub": _s("cover_sub",
        fontName="Helvetica", fontSize=13, leading=18,
        textColor=colors.HexColor("#cbd5e1"), alignment=TA_CENTER),
    "cover_meta": _s("cover_meta",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=colors.HexColor("#94a3b8"), alignment=TA_CENTER),
    "draft_banner_text": _s("draft_banner_text",
        fontName="Helvetica-Bold", fontSize=7.5, leading=11,
        textColor=colors.HexColor("#92400e"), alignment=TA_CENTER),
    "h1": _s("h1",
        fontName="Helvetica-Bold", fontSize=15, leading=20,
        textColor=C_NAVY, spaceBefore=16, spaceAfter=5, keepWithNext=True),
    "h2": _s("h2",
        fontName="Helvetica-Bold", fontSize=11, leading=15,
        textColor=C_DARK, spaceBefore=12, spaceAfter=4, keepWithNext=True),
    "h3": _s("h3",
        fontName="Helvetica-BoldOblique", fontSize=9.5, leading=13,
        textColor=C_MID, spaceBefore=8, spaceAfter=3, keepWithNext=True),
    "body": _s("body",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=C_DARK, spaceAfter=4, alignment=TA_JUSTIFY),
    "bullet": _s("bullet",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=C_DARK, leftIndent=14, firstLineIndent=-10, spaceAfter=2),
    "caption": _s("caption",
        fontName="Helvetica-Oblique", fontSize=7.5, leading=10,
        textColor=C_LIGHT, alignment=TA_CENTER, spaceBefore=4, spaceAfter=8),
    "label": _s("label",
        fontName="Helvetica-Bold", fontSize=8.5, leading=11,
        textColor=C_DARK),
    "value": _s("value",
        fontName="Helvetica", fontSize=9, leading=12,
        textColor=C_DARK),
    "toc": _s("toc",
        fontName="Helvetica", fontSize=10, leading=18,
        textColor=C_DARK, leftIndent=8),
    "sme": _s("sme",
        fontName="Helvetica-BoldOblique", fontSize=8.5, leading=12,
        textColor=colors.HexColor("#b45309"), spaceBefore=4),
    "reg": _s("reg",
        fontName="Helvetica-Oblique", fontSize=8, leading=11,
        textColor=C_BLUE, spaceAfter=6),
}

# ═══════════════════════════════════════════════════════════════════════════
# HELPER FLOWABLES & WRAPPERS
# ═══════════════════════════════════════════════════════════════════════════
class Bookmark(Flowable):
    def __init__(self, key, title, level=0):
        super().__init__()
        self.key, self.title, self.level = key, title, level
        self.width = self.height = 0
    def wrap(self, aw, ah): return 0, 0
    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)

def get_draft_banner():
    """Generates a fully auto-wrapping text banner to prevent cutoff layout clipping."""
    p = Paragraph(DRAFT_NOTICE, ST["draft_banner_text"])
    t = Table([[p]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",      (0,0),(-1,-1), colors.HexColor("#fef3c7")),
        ("BOX",             (0,0),(-1,-1), 0.6, colors.HexColor("#d97706")),
        ("TOPPADDING",      (0,0),(-1,-1), 6),
        ("BOTTOMPADDING",   (0,0),(-1,-1), 6),
        ("LEFTPADDING",     (0,0),(-1,-1), 12),
        ("RIGHTPADDING",    (0,0),(-1,-1), 12),
        ("ROUNDEDCORNERS",  (0,0),(-1,-1), [4, 4, 4, 4]),
        ("ALIGN",           (0,0),(-1,-1), "CENTER"),
        ("VALIGN",          (0,0),(-1,-1), "MIDDLE"),
    ]))
    return t

def anchor(key):
    return Paragraph(f'<a name="{key}"/>', _s("_a", fontSize=1, leading=1))

def hr(thick=0.5, c=C_RULE):
    return HRFlowable(width="100%", thickness=thick, color=c, spaceBefore=4, spaceAfter=6)

def sp(h=6): return Spacer(1, h)

# ═══════════════════════════════════════════════════════════════════════════
# TABLE HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def kv_table(pairs, lw=5.5*cm):
    rows = [[Paragraph(k, ST["label"]), Paragraph(v, ST["value"])] for k, v in pairs if v]
    if not rows: return None
    t = Table(rows, colWidths=[lw, CONTENT_W - lw], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN",          (0,0),(-1,-1), "TOP"),
        ("ROWBACKGROUNDS",  (0,0),(-1,-1), [C_WHITE, C_SHADE]),
        ("LINEBELOW",       (0,0),(-1,-1), 0.4, C_RULE),
        ("LEFTPADDING",     (0,0),(-1,-1), 6),
        ("RIGHTPADDING",    (0,0),(-1,-1), 6),
        ("TOPPADDING",      (0,0),(-1,-1), 4),
        ("BOTTOMPADDING",   (0,0),(-1,-1), 4),
    ]))
    return t

def grid_table(headers, rows, widths=None):
    if not rows: return None
    hrow = [Paragraph(h, _s(f"h_{i}", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=C_WHITE)) for i, h in enumerate(headers)]
    brows = [[Paragraph(str(c), ST["value"]) for c in r] for r in rows]
    cw = widths or [CONTENT_W / len(headers)] * len(headers)
    t = Table([hrow] + brows, colWidths=cw, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",      (0,0),(-1,0),   C_NAVY),
        ("ROWBACKGROUNDS",  (0,1),(-1,-1),  [C_WHITE, C_SHADE]),
        ("LINEBELOW",       (0,0),(-1,-1),  0.4, C_RULE),
        ("VALIGN",          (0,0),(-1,-1),  "TOP"),
        ("LEFTPADDING",     (0,0),(-1,-1),  6),
        ("RIGHTPADDING",    (0,0),(-1,-1),  6),
        ("TOPPADDING",      (0,0),(-1,-1),  4),
        ("BOTTOMPADDING",   (0,0),(-1,-1),  4),
    ]))
    return t

def sme(text):
    return Paragraph(f"[SME-INPUT-REQUIRED: {text}]", ST["sme"])

def reg_ref(*refs):
    return Paragraph(" &middot; ".join(refs), ST["reg"])

# ═══════════════════════════════════════════════════════════════════════════
# DIAGRAM GENERATORS
# ═══════════════════════════════════════════════════════════════════════════
_PLT_DEFAULTS = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "text.color": "#1e2d3d",
    "axes.labelcolor": "#1e2d3d",
    "xtick.color": "#6b7280",
    "ytick.color": "#6b7280",
}

def _apply_defaults():
    for k, v in _PLT_DEFAULTS.items():
        plt.rcParams[k] = v

def gen_vmodel(device_name: str, tmp_dir: str) -> str:
    _apply_defaults()
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.axis("off")
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)

    left_phases  = ["User Needs",  "Design Inputs", "Design Outputs",   "Design Transfer"]
    right_phases = ["Validation",  "Verification",  "Design Review",    "Production Release"]
    colors_l = ["#2563a8","#1b3a5c","#0d9488","#d97706"]
    colors_r = ["#2563a8","#1b3a5c","#0d9488","#16a34a"]

    xs = [1, 3, 5, 7,  7, 9, 11, 13]
    ys = [5, 4, 3, 1.5, 1.5, 3,  4,  5]
    ax.plot(xs[:4],  ys[:4],  color="#2563a8", lw=2, zorder=2)
    ax.plot(xs[3:],  ys[3:],  color="#0d9488", lw=2, zorder=2)

    for i, (ph, col) in enumerate(zip(left_phases, colors_l)):
        ax.scatter(xs[i], ys[i], color=col, s=70, zorder=4)
        ax.text(xs[i]-0.2, ys[i]+0.2, ph, fontsize=7.5, ha="right", color=col, fontweight="bold")

    for i, (ph, col) in enumerate(zip(right_phases, colors_r)):
        j = i + 4
        ax.scatter(xs[j], ys[j], color=col, s=70, zorder=4)
        ax.text(xs[j]+0.2, ys[j]+0.2, ph, fontsize=7.5, ha="left", color=col, fontweight="bold")

    for i in range(4):
        ax.annotate("", xy=(xs[7-i], ys[7-i]), xytext=(xs[i], ys[i]),
                    arrowprops=dict(arrowstyle="<->", color="#9ca3af", lw=0.7, linestyle="dashed"))

    ax.set_title(f"{device_name} — Design Control Lifecycle V-Model", fontsize=9, fontweight="bold", color="#0f1923", pad=10)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "vmodel.png")
    plt.savefig(out, dpi=200, bbox_inches="tight")
    plt.close()
    return out

def gen_iso14971(tmp_dir: str) -> str:
    _apply_defaults()
    stages = [
        ("Risk\nPlanning", "#2563a8"),
        ("Hazard\nIdent.",   "#1b3a5c"),
        ("Evaluation\n& Analysis", "#0d9488"),
        ("Risk\nControl",   "#16a34a"),
        ("Residual\nRisk",  "#d97706"),
        ("Report\nClosure", "#c0392b"),
    ]
    fig, ax = plt.subplots(figsize=(7, 2.0))
    ax.axis("off")
    ax.set_xlim(0, len(stages)*2.0)
    ax.set_ylim(0, 2.0)

    for i, (label, col) in enumerate(stages):
        x = i * 2.0 + 0.1
        rect = mpatches.FancyBboxPatch((x, 0.5), 1.6, 1.0, boxstyle="round,pad=0.05", fc=col, ec="white", lw=1, alpha=0.9)
        ax.add_patch(rect)
        ax.text(x+0.8, 1.0, label, ha="center", va="center", color="white", fontsize=7, fontweight="bold")
        if i < len(stages)-1:
            ax.annotate("", xy=(x+1.95, 1.0), xytext=(x+1.65, 1.0), arrowprops=dict(arrowstyle="->", color="#9ca3af", lw=1))

    ax.set_title("ISO 14971 Risk Management Implementation Flow", fontsize=9, fontweight="bold", color="#0f1923", pad=8)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "iso14971.png")
    plt.savefig(out, dpi=200, bbox_inches="tight")
    plt.close()
    return out

def gen_risk_matrix(tmp_dir: str) -> str:
    _apply_defaults()
    sev  = ["Negligible", "Minor", "Serious", "Critical", "Catastrophic"]
    prob = ["Improbable", "Remote", "Occasional", "Probable", "Frequent"]
    matrix = np.array([
        [1,1,2,2,3],
        [1,2,2,3,3],
        [2,2,3,3,4],
        [2,3,3,4,4],
        [3,3,4,4,5],
    ])
    palette = {1:"#e8f5e9", 2:"#fffde7", 3:"#ffe0b2", 4:"#ffcdd2", 5:"#ef5350"}
    labels  = {1:"Acceptable", 2:"ALARP", 3:"Review", 4:"Unacceptable", 5:"Critical"}

    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    for r in range(5):
        for c in range(5):
            val = matrix[r, c]
            ax.add_patch(plt.Rectangle((c, 4-r), 1, 1, color=palette[val], ec="white", lw=1))
            ax.text(c+0.5, 4-r+0.5, labels[val], ha="center", va="center", fontsize=7.5, color="#1e2d3d")

    ax.set_xlim(0, 5); ax.set_ylim(0, 5)
    ax.set_xticks([i+0.5 for i in range(5)])
    ax.set_xticklabels(sev, fontsize=7.5)
    ax.set_yticks([i+0.5 for i in range(5)])
    ax.set_yticklabels(reversed(prob), fontsize=7.5)
    ax.set_title("Core Risk Evaluation Hazard Index Matrix", fontsize=9, fontweight="bold", color="#0f1923", pad=10)
    for s in ax.spines.values(): s.set_visible(False)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "risk_matrix.png")
    plt.savefig(out, dpi=200, bbox_inches="tight")
    plt.close()
    return out

def gen_block_diagram(device_name: str, tmp_dir: str) -> str:
    _apply_defaults()
    blocks = [
        ("Input Subsystem\n(Sensors/Data)", "#2563a8", 0.8),
        ("Processing Unit\n(Firmware Core)", "#1b3a5c", 3.4),
        ("Output Interface\n(Actuators/UI)", "#0d9488", 6.0),
    ]
    fig, ax = plt.subplots(figsize=(6, 1.8))
    ax.axis("off")
    ax.set_xlim(0, 8.5); ax.set_ylim(0, 2.5)

    for label, col, x in blocks:
        rect = mpatches.FancyBboxPatch((x, 0.5), 1.8, 1.3, boxstyle="round,pad=0.1", fc=col, ec="white", lw=1, alpha=0.9)
        ax.add_patch(rect)
        ax.text(x+0.9, 1.15, label, ha="center", va="center", color="white", fontsize=7.5, fontweight="bold")

    for x_from, x_to in [(2.7, 3.4), (5.3, 6.0)]:
        ax.annotate("", xy=(x_to, 1.15), xytext=(x_from, 1.15), arrowprops=dict(arrowstyle="->", color="#9ca3af", lw=1.2))

    ax.set_title(f"{device_name} Structural Subsystem Topography", fontsize=9, fontweight="bold", color="#0f1923", pad=6)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "block_diagram.png")
    plt.savefig(out, dpi=200, bbox_inches="tight")
    plt.close()
    return out

def gen_sw_classification(tmp_dir: str) -> str:
    _apply_defaults()
    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    ax.axis("off")
    ax.set_xlim(0, 10); ax.set_ylim(0, 5)

    def box(x, y, w, h, text, col):
        r = mpatches.FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.08", fc=col, ec="white", lw=1)
        ax.add_patch(r)
        ax.text(x, y, text, ha="center", va="center", color="white", fontsize=7.5, fontweight="bold")

    box(5, 4.2, 4.2, 0.7, "Software Medical Component?", "#374151")
    box(5, 2.7, 3.8, 0.6, "Can failure cause injury?", "#374151")
    box(1.5, 1.2, 2.0, 0.6, "Class A\n(No Harm)", "#16a34a")
    box(5, 1.2, 2.0, 0.6, "Class B\n(Non-Serious)", "#d97706")
    box(8.2, 1.2, 2.0, 0.6, "Class C\n(Serious/Death)", "#c0392b")

    ax.annotate("", xy=(5, 3.1), xytext=(5, 3.85), arrowprops=dict(arrowstyle="->", color="#9ca3af"))
    ax.annotate("", xy=(1.5, 1.6), xytext=(3.1, 2.7), arrowprops=dict(arrowstyle="->", color="#9ca3af"))
    ax.annotate("", xy=(5, 1.6), xytext=(5, 2.3), arrowprops=dict(arrowstyle="->", color="#9ca3af"))
    ax.annotate("", xy=(8.2, 1.6), xytext=(6.9, 2.7), arrowprops=dict(arrowstyle="->", color="#9ca3af"))

    ax.set_title("IEC 62304 Architecture Safety Risk Stratification Tree", fontsize=9, fontweight="bold", color="#0f1923", pad=6)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "sw_classification.png")
    plt.savefig(out, dpi=200, bbox_inches="tight")
    plt.close()
    return out

def gen_traceability_overview(tmp_dir: str) -> str:
    _apply_defaults()
    nodes = ["User Needs", "Design Inputs", "Design Outputs", "Verification", "Validation", "Risk Controls"]
    cols  = ["#2563a8","#1b3a5c","#0d9488","#16a34a","#7c3aed","#c0392b"]
    fig, ax = plt.subplots(figsize=(7, 1.5))
    ax.axis("off")
    ax.set_xlim(0, len(nodes)*2.0)
    ax.set_ylim(0, 2)

    for i, (n, c) in enumerate(zip(nodes, cols)):
        x = i * 2.0 + 0.1
        rect = mpatches.FancyBboxPatch((x, 0.4), 1.7, 1.0, boxstyle="round,pad=0.05", fc=c, ec="white", lw=1)
        ax.add_patch(rect)
        ax.text(x+0.85, 0.9, n, ha="center", va="center", color="white", fontsize=7.5, fontweight="bold")
        if i < len(nodes)-1:
            ax.annotate("", xy=(x+2.0, 0.9), xytext=(x+1.75, 0.9), arrowprops=dict(arrowstyle="->", color="#9ca3af", lw=1))

    ax.set_title("Bidirectional Traceability Chain Verification Flow Map", fontsize=9, fontweight="bold", color="#0f1923", pad=6)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "traceability.png")
    plt.savefig(out, dpi=200, bbox_inches="tight")
    plt.close()
    return out

# ═══════════════════════════════════════════════════════════════════════════
# CANVAS FOOTER & RUNNING HEADERS
# ═══════════════════════════════════════════════════════════════════════════
class Footer:
    def __init__(self, device_name):
        self.device = device_name

    def __call__(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_LIGHT)
        canvas.setFont("Helvetica", 7)
        # Running header layout
        canvas.drawString(MARGIN, PAGE_H - 1.2*cm, f"DESIGN HISTORY FILE (DHF) — CONTROLLED PROFILE")
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 1.2*cm, f"DEVICE ID: {self.device.upper()}")
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - 1.3*cm, PAGE_W - MARGIN, PAGE_H - 1.3*cm)

        # Bottom footer layout
        canvas.drawString(MARGIN, 0.9*cm, f"Confidential &middot; Draft Summary File &middot; Generated: {date.today().isoformat()}")
        canvas.drawRightString(PAGE_W - MARGIN, 0.9*cm, f"Page {doc.page}")
        canvas.line(MARGIN, 1.1*cm, PAGE_W - MARGIN, 1.1*cm)
        canvas.restoreState()

# ═══════════════════════════════════════════════════════════════════════════
# SECTION COMPILATION ASSEMBLY
# ═══════════════════════════════════════════════════════════════════════════
def section_header(story, num, title, key):
    story += [
        Bookmark(key, f"{num}. {title}"),
        anchor(key),
        Paragraph(f"{num}. {title}", ST["h1"]),
        hr(1.2, C_NAVY),
    ]

def cover_page(story, intake):
    cover_bg = Table([[Paragraph(intake["device_name"], ST["cover_title"])]], colWidths=[CONTENT_W])
    cover_bg.setStyle(TableStyle([
        ("BACKGROUND",      (0,0),(-1,-1), C_NAVY),
        ("TOPPADDING",      (0,0),(-1,-1), 32),
        ("BOTTOMPADDING",   (0,0),(-1,-1), 32),
        ("LEFTPADDING",     (0,0),(-1,-1), 16),
        ("RIGHTPADDING",    (0,0),(-1,-1), 16),
        ("ROUNDEDCORNERS",  (0,0),(-1,-1), [6,6,6,6]),
    ]))
    story += [
        Spacer(1, 3.5*cm),
        cover_bg,
        sp(20),
        Paragraph("Design History File Master Dossier", ST["cover_sub"]),
        sp(8),
        Paragraph(f"Model Portfolio Reference: {intake.get('model_number','[TBD]')} &nbsp;&middot;&nbsp; "
                  f"FDA Classification: Class {intake.get('fda_class','?')} &nbsp;&middot;&nbsp; "
                  f"EU MDR Class: {intake.get('eu_mdr_class','?')}", ST["cover_meta"]),
        sp(6),
        Paragraph(f"Target Markets: {', '.join(intake.get('target_markets', []))} &nbsp;&middot;&nbsp; Generation Date: {date.today().isoformat()}", ST["cover_meta"]),
        Spacer(1, 4.0*cm),
        get_draft_banner(),
        PageBreak(),
    ]

def toc(story):
    sections = [
        ("1", "DHF Index & Document Register",   "sec1"),
        ("2", "Design & Development Plan",        "sec2"),
        ("3", "Design Inputs Specification",      "sec3"),
        ("4", "Design Outputs Release Package",   "sec4"),
        ("5", "Design Review Records Log",        "sec5"),
        ("6", "Design Verification Protocols",    "sec6"),
        ("7", "Design Validation Summary",        "sec7"),
        ("8", "Design Transfer Architecture",     "sec8"),
        ("9", "Design Engineering Change Log",    "sec9"),
        ("10", "ISO 14971 Risk Management File",   "sec10"),
        ("11", "Regulatory Traceability Matrix",   "sec11"),
        ("A",  "Computer System Validation (CSV)", "secA"),
    ]
    story += [
        Bookmark("toc", "Table of Contents"),
        anchor("toc"),
        Paragraph("Table of Contents", ST["h1"]),
        hr(1.2, C_NAVY),
        sp(8),
    ]
    for num, title, key in sections:
        story.append(Paragraph(f'<b>{num}</b> &nbsp;&nbsp; <link href="#{key}">{title}</link>', ST["toc"]))
    story.append(PageBreak())

def sec_dhf_index(story, intake):
    section_header(story, 1, "DHF Index & Document Register", "sec1")
    story += [
        reg_ref("21 CFR § 820.30(j)", "ISO 13485:2016 Clause 7.3.10"),
        sp(6),
        kv_table([
            ("System Medical Name", intake["device_name"]),
            ("Model Assignment",    intake.get("model_number","[TBD]")),
            ("FDA Pathway Class",   f"Class {intake.get('fda_class','[SME]')} Specification"),
            ("EU MDR Stratum",      f"Class {intake.get('eu_mdr_class','[SME]')} Matrix"),
            ("Intended Deployments", ", ".join(intake.get("target_markets",[]))),
        ]),
        sp(12),
        Paragraph("Master Controlled Document Register", ST["h2"]),
        grid_table(
            ["Doc ID","Title Asset Module","Structure Category","Rev","Release Execution Date"],
            [
                ["DHF-01","Design & Development Project Roadmap","Plan System","A",date.today().isoformat()],
                ["DHF-02","Engineering Design Inputs Specification","Technical Spec","A",date.today().isoformat()],
                ["DHF-03","Essential Design Output Matrix Index","Product Release","A",date.today().isoformat()],
                ["DHF-04","Design Phase Review Milestone Registers","Execution Logs","A",date.today().isoformat()],
                ["DHF-05","Verification Verification Test Records","Assurance Report","A",date.today().isoformat()],
                ["DHF-06","Clinical Use Case Validation Dossier","Validation File","A",date.today().isoformat()],
                ["DHF-10","System Level Traceability Master Matrix","Trace Map Matrix","A",date.today().isoformat()],
            ],
            widths=[1.5*cm, 6.2*cm, 3.2*cm, 1.0*cm, CONTENT_W-11.9*cm]
        ),
        PageBreak(),
    ]

def sec_ddplan(story, intake, imgs):
    section_header(story, 2, "Design & Development Plan", "sec2")
    story += [
        get_draft_banner(), sp(6),
        reg_ref("21 CFR § 820.30(b)", "ISO 13485:2016 § 7.3.2", "EU MDR Annex II Section 3"),
        sp(6),
        Paragraph("1. Purpose & Core Operational Scope", ST["h2"]),
        Paragraph(f"This document formalizes the development constraints, validation mechanics, and assignment matrices governing the architectural generation lifecycle of the {intake['device_name']}.", ST["body"]),
        sp(6),
        Paragraph("2. Device Description & Intended Operational Vector", ST["h2"]),
        kv_table([
            ("Intended Use Case Strategy", intake["intended_use"]),
            ("Indications for Patient Deployment", intake["indications_for_use"]),
        ]),
        sp(12),
        Paragraph("3. Design Control Structural V-Model Pathway", ST["h2"]),
        KeepTogether([
            Image(imgs["vmodel"], width=CONTENT_W, height=3.6*cm),
            Paragraph("Figure 2.1: Formal V-Model workflow linking explicit design gates with functional cross-verification paths.", ST["caption"]),
        ]),
        PageBreak(),
    ]

def sec_design_inputs(story, intake, imgs):
    section_header(story, 3, "Design Inputs Specification", "sec3")
    story += [
        get_draft_banner(), sp(6),
        reg_ref("21 CFR § 820.30(c)", "ISO 13485:2016 § 7.3.3"),
        sp(6),
        Paragraph("1. Structural Functional Block Decomposition Topology", ST["h2"]),
        KeepTogether([
            Image(imgs["block"], width=CONTENT_W, height=1.8*cm),
            Paragraph("Figure 3.1: Subsystem hardware boundaries and cross-talk communication architecture.", ST["caption"]),
        ]),
        sp(8),
        Paragraph("2. Primary Software Safety Stratification Tree", ST["h2"]),
    ]
    if intake.get("contains_software"):
        story += [
            KeepTogether([
                Image(imgs["sw_class"], width=CONTENT_W*0.9, height=2.8*cm),
                Paragraph("Figure 3.2: IEC 62304 categorical decision tree mapping failure mechanism limits.", ST["caption"]),
            ])
        ]
    else:
        story += [Paragraph("Not applicable — System configuration contains no software assets.", ST["body"])]
    
    story.append(PageBreak())

def _simple_section(story, num, title, key, reg, subsections):
    section_header(story, num, title, key)
    story += [
        get_draft_banner(), sp(6),
        Paragraph(reg, ST["reg"]), sp(6),
    ]
    for heading, body in subsections:
        story += [Paragraph(heading, ST["h2"]), Paragraph(body, ST["body"]), sp(4)]
    story.append(PageBreak())

def sec_design_outputs(story, intake):
    _simple_section(story, 4, "Design Outputs Release Package", "sec4",
        "21 CFR § 820.30(d) | ISO 13485:2016 § 7.3.4",
        [
            ("1. Device Master Record (DMR) Generation Rules", "The Device Master Record serves as the technical drawing manifest for pilot manufacture procurement. All constituent BOM structures must link directly to verified files inside the local configuration repository."),
            ("2. Identification of Essential Design Parameters", "Parameters central to mechanical stability or structural tolerance levels must be flagged directly in engineering drawing bundles to initiate validation controls.")
        ])

def sec_design_review(story, intake):
    _simple_section(story, 5, "Design Review Records Log", "sec5",
        "21 CFR § 820.30(e) | ISO 13485:2016 § 7.3.5",
        [
            ("1. Independent Review Mandate Governance", "Per system quality guidelines, each formal validation gate requires an independent evaluation engineer to confirm objective progress metrics without historical bias."),
            ("2. Open Phase Action Remediation Flow", "Any deviation flags generated during milestone tracking assessments must follow remediation loops before engineering changes settle.")
        ])

def sec_verification(story, intake):
    _simple_section(story, 6, "Design Verification Protocols", "sec6",
        "21 CFR § 820.30(f) | ISO 13485:2016 § 7.3.6",
        [
            ("1. Sample Size Determination Principles", "Sample sets assigned to physical benchmark stress tracking must map back to statistical reliability thresholds determined by engineering standard sets."),
            ("2. Functional Environmental Test Executions", "Benchtop verification sequences must subject components to simulated real-world conditions to gather operational limit bounds.")
        ])

def sec_validation(story, intake):
    _simple_section(story, 7, "Design Validation Summary", "sec7",
        "21 CFR § 820.30(g) | ISO 13485:2016 § 7.3.7",
        [
            ("1. Human Factors Clinical Usability Vector", "Validation must monitor real human operator pathways inside contextual configurations to confirm error mitigation protocols match target intent."),
            ("2. Clinical Evaluation Matrix Tracking", "Evaluations must track explicit patient outcome vectors using structured comparative models aligned with state-of-the-art standards.")
        ])

def sec_transfer(story, intake):
    _simple_section(story, 8, "Design Transfer Architecture", "sec8",
        "21 CFR § 820.30(h) | ISO 13485:2016 § 7.3.8",
        [
            ("1. First Article Manufacturing Assessments", "Transfer steps necessitate production evaluation checkouts to confirm tools, fixtures, and operator steps are aligned with specifications."),
            ("2. Critical Process IQ/OQ/PQ Validation Matrix", "Any software-driven tools or special operational sequences must clear formal environmental qualification gates before structural deployment.")
        ])

def sec_change_log(story, intake):
    section_header(story, 9, "Design Engineering Change Log", "sec9")
    story += [
        get_draft_banner(), sp(6),
        reg_ref("21 CFR § 820.30(i)", "ISO 13485:2016 § 7.3.9"), sp(6),
        Paragraph("All engineering shifts altering form, fit, or baseline function post-freeze are archived within this control segment to trace structural derivations accurately.", ST["body"]),
        sp(8),
        grid_table(
            ["ECO Ref","Change Engineering Summary","Author","System Impact Mapping","Approval Sign-off"],
            [["ECO-001","Initial structural baseline schema layout stabilization.","R&D Lead","Baseline Engineering Configuration","Approved via QA Matrix"]],
            widths=[1.8*cm, 5.0*cm, 1.8*cm, 3.8*cm, CONTENT_W-12.4*cm]
        ),
        PageBreak(),
    ]

def sec_rmf(story, intake, imgs):
    section_header(story, 10, "ISO 14971 Risk Management File", "sec10")
    story += [
        get_draft_banner(), sp(6),
        reg_ref("ISO 14971:2019", "ISO/TR 24971:2020", "21 CFR § 820.30(g)"), sp(6),
        Paragraph("1. Risk Assessment Workflow Integration", ST["h2"]),
        KeepTogether([
            Image(imgs["iso14971"], width=CONTENT_W, height=2.0*cm),
            Paragraph("Figure 10.1: Phased milestone steps governing lifecycle danger mitigation analysis.", ST["caption"]),
        ]),
        sp(8),
        Paragraph("2. Mathematical Critical Hazard Grid", ST["h2"]),
        KeepTogether([
            Image(imgs["risk_matrix"], width=CONTENT_W*0.8, height=3.5*cm),
            Paragraph("Figure 10.2: 5x5 Matrix used to evaluate acceptability criteria limits.", ST["caption"]),
        ]),
        PageBreak(),
    ]

def sec_traceability(story, imgs):
    section_header(story, 11, "Regulatory Traceability Matrix", "sec11")
    story += [
        get_draft_banner(), sp(6),
        reg_ref("21 CFR § 820.30(j)", "ISO 13485:2016 § 7.3.10"), sp(6),
        Paragraph("Each line structural node trace tracks downstream to prove component implementation consistency across input constraints.", ST["body"]),
        sp(8),
        KeepTogether([
            Image(imgs["traceability"], width=CONTENT_W, height=1.5*cm),
            Paragraph("Figure 11.1: Functional lineage tracing dependencies across verification layers.", ST["caption"]),
        ]),
        sp(8),
        grid_table(
            ["User Need","Design Input","Design Output","Verification Ref","Validation Ref"],
            [["UN-001: Functional System","DI-001: Perform Limit","DO-001: Schematic Bundle","VER-001: Lab Benchmark","VAL-001: Clinical Use Case"]],
            widths=None
        ),
        PageBreak(),
    ]

def sec_csv(story):
    section_header(story, "A", "Computer System Validation (CSV)", "secA")
    story += [
        get_draft_banner(), sp(6),
        reg_ref("21 CFR Part 11", "FDA Software Validation Guidance", "GAMP 5 Framework"), sp(6),
        Paragraph("Automated workflows handling safety or architectural calculations require validation testing loops before integration into configuration platforms.", ST["body"]),
        sp(8),
        grid_table(
            ["Validation Activity Module","Scope Assessment","Owner","System Qualification Gate Status"],
            [
                ["URS Spec Verification","User Requirement Alignment Check","Quality Assurance","Baselined Profile"],
                ["OQ Functional Verification","Stress Run Phase Optimization Tests","R&D Sandbox","Execution Complete"],
                ["PQ Continuous Stability","Long Horizon Data Integrity Checks","Production QA","In Queue Phase"]
            ],
            widths=[4.0*cm, 5.0*cm, 2.5*cm, CONTENT_W-11.5*cm]
        ),
    ]

# ═══════════════════════════════════════════════════════════════════════════
# MAIN BUILD SYSTEM PIPELINE
# ═══════════════════════════════════════════════════════════════════════════
def build_pdf(intake: dict, output_path: str):
    with tempfile.TemporaryDirectory() as tmp:
        print("  Generating vector diagrams...")
        imgs = {
            "vmodel":       gen_vmodel(intake["device_name"], tmp),
            "iso14971":     gen_iso14971(tmp),
            "risk_matrix":  gen_risk_matrix(tmp),
            "block":        gen_block_diagram(intake["device_name"], tmp),
            "traceability": gen_traceability_overview(tmp),
        }
        if intake.get("contains_software"):
            imgs["sw_class"] = gen_sw_classification(tmp)

        print("  Assembling structural layout elements...")
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN + 0.5*cm, bottomMargin=MARGIN + 0.6*cm,
            title=f"DHF — {intake['device_name']}",
            author="DHF Automated Pipeline Engine",
        )

        story = []
        cover_page(story, intake)
        toc(story)
        sec_dhf_index(story, intake)
        sec_ddplan(story, intake, imgs)
        sec_design_inputs(story, intake, imgs)
        sec_design_outputs(story, intake)
        sec_design_review(story, intake)
        sec_verification(story, intake)
        sec_validation(story, intake)
        sec_transfer(story, intake)
        sec_change_log(story, intake)
        sec_rmf(story, intake, imgs)
        sec_traceability(story, imgs)
        sec_csv(story)

        footer = Footer(intake["device_name"])
        doc.build(story, onFirstPage=footer, onLaterPages=footer)

    print(f"  PDF Compiled Successfully -> {output_path}")

def main():
    parser = argparse.ArgumentParser(description="DHF Document Orchestrator Tool Module")
    parser.add_argument("--intake", required=True, help="Input Configuration Profile JSON")
    parser.add_argument("--out",    default="DHF_Report.pdf", help="Target Export Target Path")
    args = parser.parse_args()

    intake = json.loads(Path(args.intake).read_text())
    print(f"\nProcessing Engine Init -> {intake['device_name']}")
    build_pdf(intake, args.out)

if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
dhf_export.py — Integrated DHF Builder + PDF Exporter

Generates a complete Design History File (DHF) as a professional PDF
from a device intake JSON, with embedded Matplotlib charts/diagrams.

No external diagram subprocess required — all visuals generated inline.

Usage:
    python dhf_export.py --intake intake.json --out DHF_Report.pdf

Minimum intake.json schema:
{
  "device_name": "string",
  "model_number": "string",
  "intended_use": "string",
  "indications_for_use": "string",
  "fda_class": "I | II | III",
  "eu_mdr_class": "I | IIa | IIb | III",
  "patient_contacting": true,
  "sterile": false,
  "contains_software": false,
  "electromedical": false,
  "reusable": false,
  "implantable": true,
  "target_markets": ["US", "EU"]
}
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import date

# ── Matplotlib headless ────────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── ReportLab ──────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, HRFlowable, Image, KeepTogether
)

# ═══════════════════════════════════════════════════════════════════════════
# COLOUR PALETTE
# ═══════════════════════════════════════════════════════════════════════════
C_BLACK   = colors.HexColor("#0f1923")
C_DARK    = colors.HexColor("#1e2d3d")
C_NAVY    = colors.HexColor("#1b3a5c")
C_BLUE    = colors.HexColor("#2563a8")
C_TEAL    = colors.HexColor("#0d9488")
C_RED     = colors.HexColor("#c0392b")
C_AMBER   = colors.HexColor("#d97706")
C_GREEN   = colors.HexColor("#16a34a")
C_MID     = colors.HexColor("#4b5563")
C_LIGHT   = colors.HexColor("#9ca3af")
C_RULE    = colors.HexColor("#d1d5db")
C_SHADE   = colors.HexColor("#f3f4f6")
C_SHADE2  = colors.HexColor("#e0f2fe")
C_WHITE   = colors.white

PAGE_W, PAGE_H = A4
MARGIN        = 2.0 * cm
CONTENT_W     = PAGE_W - 2 * MARGIN

DRAFT_NOTICE = (
    "DRAFT — AI-ASSISTED CONTENT. NOT FOR REGULATORY SUBMISSION WITHOUT "
    "SME REVIEW, RESPONSIBLE-PERSON APPROVAL, AND CSV-VALIDATED RELEASE "
    "PER 21 CFR PART 11."
)

# ═══════════════════════════════════════════════════════════════════════════
# STYLE SHEET
# ═══════════════════════════════════════════════════════════════════════════
def _s(name, **kw):
    return ParagraphStyle(name, **kw)

ST = {
    "cover_title": _s("cover_title",
        fontName="Helvetica-Bold", fontSize=28, leading=36,
        textColor=C_WHITE, alignment=TA_CENTER),
    "cover_sub": _s("cover_sub",
        fontName="Helvetica", fontSize=13, leading=18,
        textColor=colors.HexColor("#cbd5e1"), alignment=TA_CENTER),
    "cover_meta": _s("cover_meta",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=colors.HexColor("#94a3b8"), alignment=TA_CENTER),
    "draft_banner": _s("draft_banner",
        fontName="Helvetica-Bold", fontSize=8, leading=11,
        textColor=colors.HexColor("#92400e"), alignment=TA_CENTER),
    "h1": _s("h1",
        fontName="Helvetica-Bold", fontSize=15, leading=20,
        textColor=C_NAVY, spaceBefore=16, spaceAfter=5),
    "h2": _s("h2",
        fontName="Helvetica-Bold", fontSize=11, leading=15,
        textColor=C_DARK, spaceBefore=10, spaceAfter=3),
    "h3": _s("h3",
        fontName="Helvetica-BoldOblique", fontSize=9.5, leading=13,
        textColor=C_MID, spaceBefore=7, spaceAfter=2),
    "body": _s("body",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=C_DARK, spaceAfter=3),
    "bullet": _s("bullet",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=C_DARK, leftIndent=14, firstLineIndent=-10, spaceAfter=2),
    "caption": _s("caption",
        fontName="Helvetica-Oblique", fontSize=7.5, leading=10,
        textColor=C_LIGHT, alignment=TA_CENTER),
    "label": _s("label",
        fontName="Helvetica-Bold", fontSize=8, leading=11,
        textColor=C_MID),
    "value": _s("value",
        fontName="Helvetica", fontSize=9, leading=12,
        textColor=C_DARK),
    "toc": _s("toc",
        fontName="Helvetica", fontSize=10, leading=16,
        textColor=C_DARK, leftIndent=8),
    "toc_sub": _s("toc_sub",
        fontName="Helvetica", fontSize=9, leading=14,
        textColor=C_MID, leftIndent=22),
    "sme": _s("sme",
        fontName="Helvetica-BoldOblique", fontSize=8.5, leading=12,
        textColor=colors.HexColor("#b45309")),
    "reg": _s("reg",
        fontName="Helvetica-Oblique", fontSize=8, leading=11,
        textColor=C_BLUE),
}

# ═══════════════════════════════════════════════════════════════════════════
# HELPER FLOWABLES
# ═══════════════════════════════════════════════════════════════════════════
class Bookmark(Flowable):
    def __init__(self, key, title, level=0):
        super().__init__()
        self.key, self.title, self.level = key, title, level
        self.width = self.height = 0
    def wrap(self, aw, ah): return 0, 0
    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)

class DraftBanner(Flowable):
    """Amber DRAFT banner that spans the content width."""
    def __init__(self, width):
        super().__init__()
        self.width = width
        self.height = 18
    def wrap(self, aw, ah):
        return self.width, self.height
    def draw(self):
        c = self.canv
        c.setFillColor(colors.HexColor("#fef3c7"))
        c.setStrokeColor(colors.HexColor("#d97706"))
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.width, self.height - 2, 3, fill=1, stroke=1)
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(colors.HexColor("#92400e"))
        c.drawCentredString(self.width / 2, 5, DRAFT_NOTICE)

def anchor(key):
    return Paragraph(f'<a name="{key}"/>', _s("_a", fontSize=1, leading=1))

def hr(thick=0.5, c=C_RULE):
    return HRFlowable(width="100%", thickness=thick, color=c,
                      spaceBefore=3, spaceAfter=5)

def sp(h=6): return Spacer(1, h)

# ═══════════════════════════════════════════════════════════════════════════
# TABLE HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def kv_table(pairs, lw=5*cm):
    rows = [[Paragraph(k, ST["label"]), Paragraph(v, ST["value"])]
            for k, v in pairs if v]
    if not rows: return None
    t = Table(rows, colWidths=[lw, CONTENT_W - lw], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN",          (0,0),(-1,-1), "TOP"),
        ("ROWBACKGROUNDS",  (0,0),(-1,-1), [C_WHITE, C_SHADE]),
        ("LINEBELOW",       (0,0),(-1,-1), 0.3, C_RULE),
        ("LEFTPADDING",     (0,0),(-1,-1), 5),
        ("RIGHTPADDING",    (0,0),(-1,-1), 5),
        ("TOPPADDING",      (0,0),(-1,-1), 3),
        ("BOTTOMPADDING",   (0,0),(-1,-1), 3),
    ]))
    return t

def grid_table(headers, rows, widths=None):
    if not rows: return None
    hrow = [Paragraph(h, ST["label"]) for h in headers]
    brows = [[Paragraph(str(c), ST["value"]) for c in r] for r in rows]
    cw = widths or [CONTENT_W / len(headers)] * len(headers)
    t = Table([hrow] + brows, colWidths=cw, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",      (0,0),(-1,0),   C_NAVY),
        ("TEXTCOLOR",       (0,0),(-1,0),   C_WHITE),
        ("FONTNAME",        (0,0),(-1,0),   "Helvetica-Bold"),
        ("FONTSIZE",        (0,0),(-1,0),   8),
        ("ROWBACKGROUNDS",  (0,1),(-1,-1),  [C_WHITE, C_SHADE]),
        ("LINEBELOW",       (0,0),(-1,-1),  0.3, C_RULE),
        ("VALIGN",          (0,0),(-1,-1),  "TOP"),
        ("LEFTPADDING",     (0,0),(-1,-1),  5),
        ("RIGHTPADDING",    (0,0),(-1,-1),  5),
        ("TOPPADDING",      (0,0),(-1,-1),  3),
        ("BOTTOMPADDING",   (0,0),(-1,-1),  3),
    ]))
    return t

def sme(text):
    return Paragraph(f"[SME-INPUT-REQUIRED: {text}]", ST["sme"])

def reg_ref(*refs):
    return Paragraph(" | ".join(refs), ST["reg"])

# ═══════════════════════════════════════════════════════════════════════════
# DIAGRAM GENERATORS
# ═══════════════════════════════════════════════════════════════════════════
_PLT_DEFAULTS = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "text.color": "#374151",
    "axes.labelcolor": "#374151",
    "xtick.color": "#6b7280",
    "ytick.color": "#6b7280",
}

def _apply_defaults():
    for k, v in _PLT_DEFAULTS.items():
        plt.rcParams[k] = v

def gen_vmodel(device_name: str, tmp_dir: str) -> str:
    """V-Model lifecycle diagram."""
    _apply_defaults()
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.axis("off")
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)

    left_phases  = ["User Needs",  "Design Inputs", "Design Outputs",   "Build / Prototype"]
    right_phases = ["Validation",  "Verification",  "Design Review",    "Unit Testing"]
    colors_l = ["#2563a8","#1b3a5c","#0d9488","#16a34a"]
    colors_r = ["#2563a8","#1b3a5c","#0d9488","#16a34a"]

    # Draw V shape
    xs = [1, 3, 5, 7,  7, 9, 11, 13]
    ys = [5, 4, 3, 1.2, 1.2, 3,  4,  5]
    ax.plot(xs[:4],  ys[:4],  color="#2563a8", lw=2.2, zorder=2)
    ax.plot(xs[3:],  ys[3:],  color="#0d9488", lw=2.2, zorder=2)

    for i, (ph, col) in enumerate(zip(left_phases, colors_l)):
        ax.scatter(xs[i], ys[i], color=col, s=90, zorder=4)
        ax.text(xs[i]-0.15, ys[i]+0.3, ph, fontsize=8, ha="right",
                color=col, fontweight="bold")

    for i, (ph, col) in enumerate(zip(right_phases, colors_r)):
        j = i + 4
        ax.scatter(xs[j], ys[j], color=col, s=90, zorder=4)
        ax.text(xs[j]+0.15, ys[j]+0.3, ph, fontsize=8, ha="left",
                color=col, fontweight="bold")

    # Horizontal dashed lines linking left↔right
    for i in range(4):
        ax.annotate("", xy=(xs[7-i], ys[7-i]+0.05),
                    xytext=(xs[i], ys[i]+0.05),
                    arrowprops=dict(arrowstyle="<->", color=colors_l[i],
                                   lw=0.8, linestyle="dashed"))

    ax.text(7, 0.5, "Design Transfer", fontsize=8, ha="center",
            color="#d97706", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", fc="#fef3c7", ec="#d97706", lw=0.8))
    ax.set_title(f"{device_name} — Design Control V-Model",
                 fontsize=10, fontweight="bold", color="#0f1923", pad=8)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "vmodel.png")
    plt.savefig(out, dpi=180, bbox_inches="tight")
    plt.close()
    return out


def gen_iso14971(tmp_dir: str) -> str:
    """ISO 14971 Risk Management process flow."""
    _apply_defaults()
    stages = [
        ("Risk Management\nPlanning",     "#2563a8"),
        ("Hazard\nIdentification",        "#1b3a5c"),
        ("Risk Estimation\n& Evaluation", "#0d9488"),
        ("Risk Control",                  "#16a34a"),
        ("Residual Risk\nEvaluation",     "#d97706"),
        ("Benefit-Risk\nAnalysis",        "#7c3aed"),
        ("Risk Management\nReport",       "#c0392b"),
    ]
    fig, ax = plt.subplots(figsize=(7, 2.5))
    ax.axis("off")
    ax.set_xlim(0, len(stages)*2+0.5)
    ax.set_ylim(0, 2.5)

    for i, (label, col) in enumerate(stages):
        x = i * 2 + 0.5
        rect = mpatches.FancyBboxPatch((x, 0.6), 1.5, 1.2,
            boxstyle="round,pad=0.1", fc=col, ec="white", lw=1, alpha=0.88)
        ax.add_patch(rect)
        ax.text(x+0.75, 1.2, label, ha="center", va="center",
                color="white", fontsize=6.5, fontweight="bold")
        if i < len(stages)-1:
            ax.annotate("", xy=(x+1.65, 1.2), xytext=(x+1.5, 1.2),
                        arrowprops=dict(arrowstyle="->", color="#6b7280", lw=1.2))

    ax.text(len(stages), 0.2,
            "Feedback loop: production & post-production information → repeat",
            fontsize=7, ha="center", color="#6b7280", style="italic")
    ax.set_title("ISO 14971:2019 Risk Management Process", fontsize=9,
                 fontweight="bold", color="#0f1923", pad=6)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "iso14971.png")
    plt.savefig(out, dpi=180, bbox_inches="tight")
    plt.close()
    return out


def gen_risk_matrix(tmp_dir: str) -> str:
    """5×5 risk acceptability heat-map matrix."""
    _apply_defaults()
    sev  = ["Negligible", "Minor", "Serious", "Critical", "Catastrophic"]
    prob = ["Improbable", "Remote", "Occasional", "Probable", "Frequent"]
    matrix = np.array([
        [1,1,2,2,3],
        [1,2,2,3,3],
        [2,2,3,3,4],
        [2,3,3,4,4],
        [3,3,4,4,5],
    ])
    palette = {1:"#d1fae5",2:"#fef3c7",3:"#fed7aa",4:"#fca5a5",5:"#ef4444"}
    labels  = {1:"Acceptable",2:"ALARP",3:"Undesirable",4:"Unacceptable",5:"Intolerable"}

    fig, ax = plt.subplots(figsize=(6, 4))
    for r in range(5):
        for c in range(5):
            val = matrix[r, c]
            ax.add_patch(plt.Rectangle((c, 4-r), 1, 1,
                color=palette[val], ec="white", lw=1.2))
            ax.text(c+0.5, 4-r+0.5, labels[val],
                    ha="center", va="center", fontsize=7,
                    color="#111827", fontweight="bold" if val >= 4 else "normal")

    ax.set_xlim(0, 5); ax.set_ylim(0, 5)
    ax.set_xticks([i+0.5 for i in range(5)])
    ax.set_xticklabels(sev, fontsize=7.5, rotation=20, ha="right")
    ax.set_yticks([i+0.5 for i in range(5)])
    ax.set_yticklabels(reversed(prob), fontsize=7.5)
    ax.set_xlabel("Severity →", fontsize=8, color="#374151")
    ax.set_ylabel("← Probability", fontsize=8, color="#374151")
    ax.set_title("Risk Acceptability Matrix (5×5)", fontsize=9,
                 fontweight="bold", color="#0f1923", pad=8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "risk_matrix.png")
    plt.savefig(out, dpi=180, bbox_inches="tight")
    plt.close()
    return out


def gen_block_diagram(device_name: str, tmp_dir: str) -> str:
    """Functional block diagram."""
    _apply_defaults()
    blocks = [
        ("Input\nSubsystem",    "#2563a8", 1.0),
        ("Core\nProcessing",    "#1b3a5c", 3.5),
        ("Output\nSubsystem",   "#0d9488", 6.0),
    ]
    fig, ax = plt.subplots(figsize=(6, 2.0))
    ax.axis("off")
    ax.set_xlim(0, 8); ax.set_ylim(0, 3)

    for label, col, x in blocks:
        rect = mpatches.FancyBboxPatch((x, 0.6), 1.6, 1.4,
            boxstyle="round,pad=0.15", fc=col, ec="white", lw=1.2, alpha=0.9)
        ax.add_patch(rect)
        ax.text(x+0.8, 1.3, label, ha="center", va="center",
                color="white", fontsize=8.5, fontweight="bold")

    for x_from, x_to in [(2.6, 3.5), (5.1, 6.0)]:
        ax.annotate("", xy=(x_to, 1.3), xytext=(x_from, 1.3),
                    arrowprops=dict(arrowstyle="->", color="#6b7280", lw=1.5))

    ax.set_title(f"{device_name} — Functional Block Diagram",
                 fontsize=9, fontweight="bold", color="#0f1923", pad=6)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "block_diagram.png")
    plt.savefig(out, dpi=180, bbox_inches="tight")
    plt.close()
    return out


def gen_sw_classification(tmp_dir: str) -> str:
    """IEC 62304 software safety classification decision tree."""
    _apply_defaults()
    fig, ax = plt.subplots(figsize=(6.5, 3.0))
    ax.axis("off")
    ax.set_xlim(0, 10); ax.set_ylim(0, 5)

    def box(x, y, w, h, text, col, tcol="white", fs=8):
        r = mpatches.FancyBboxPatch((x-w/2, y-h/2), w, h,
            boxstyle="round,pad=0.1", fc=col, ec="white", lw=1, alpha=0.9)
        ax.add_patch(r)
        ax.text(x, y, text, ha="center", va="center",
                color=tcol, fontsize=fs, fontweight="bold")

    def arr(x1, y1, x2, y2, label=""):
        ax.annotate("", xy=(x2,y2), xytext=(x1,y1),
                    arrowprops=dict(arrowstyle="->", color="#6b7280", lw=1.2))
        if label:
            mx, my = (x1+x2)/2, (y1+y2)/2
            ax.text(mx+0.15, my, label, fontsize=7, color="#6b7280")

    box(5, 4.3, 4, 0.8, "Software in medical device?", "#374151", "white", 8)
    arr(5, 3.9, 5, 3.2)
    box(5, 2.9, 3.5, 0.6, "Hazardous situation\nif software fails?", "#374151", "white", 7.5)
    arr(5, 2.6, 5, 1.9)
    box(5, 1.6, 3.5, 0.6, "Severity: serious\ninjury or death?", "#374151", "white", 7.5)
    arr(3.25, 2.9, 1.5, 1.6)
    box(1.5, 1.3, 2.2, 0.6, "Class A\n(No hazard)", "#16a34a")
    arr(5, 1.3, 6.8, 0.7)
    box(7, 0.5, 2.2, 0.6, "Class B\n(Non-fatal)", "#d97706")
    arr(5, 1.6, 3.2, 0.5)
    box(3.0, 0.3, 2.2, 0.6, "Class C\n(Fatal / serious)", "#c0392b")

    ax.text(3.5, 3.0, "No", fontsize=7, color="#16a34a", fontweight="bold")
    ax.text(5.2, 2.3, "Yes", fontsize=7, color="#c0392b", fontweight="bold")
    ax.text(5.2, 1.55, "No", fontsize=7, color="#d97706", fontweight="bold")
    ax.text(4.3, 1.0, "Yes", fontsize=7, color="#c0392b", fontweight="bold")

    ax.set_title("IEC 62304 Software Safety Classification",
                 fontsize=9, fontweight="bold", color="#0f1923", pad=6)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "sw_classification.png")
    plt.savefig(out, dpi=180, bbox_inches="tight")
    plt.close()
    return out


def gen_traceability_overview(tmp_dir: str) -> str:
    """Linear traceability chain bar-chart style."""
    _apply_defaults()
    nodes = ["User Needs", "Design\nInputs", "Design\nOutputs",
             "Verification", "Validation", "Risk\nControls"]
    cols  = ["#2563a8","#1b3a5c","#0d9488","#16a34a","#7c3aed","#c0392b"]

    fig, ax = plt.subplots(figsize=(7, 1.8))
    ax.axis("off")
    ax.set_xlim(0, len(nodes)*2.2)
    ax.set_ylim(0, 2)

    for i, (n, c) in enumerate(zip(nodes, cols)):
        x = i * 2.2 + 0.2
        rect = mpatches.FancyBboxPatch((x, 0.4), 1.8, 1.1,
            boxstyle="round,pad=0.12", fc=c, ec="white", lw=1, alpha=0.88)
        ax.add_patch(rect)
        ax.text(x+0.9, 0.95, n, ha="center", va="center",
                color="white", fontsize=7.5, fontweight="bold")
        if i < len(nodes)-1:
            ax.annotate("", xy=(x+2.1, 0.95), xytext=(x+1.8, 0.95),
                        arrowprops=dict(arrowstyle="->", color="#6b7280", lw=1.2))

    ax.set_title("DHF Traceability Chain", fontsize=9,
                 fontweight="bold", color="#0f1923", pad=5)
    plt.tight_layout()
    out = os.path.join(tmp_dir, "traceability.png")
    plt.savefig(out, dpi=180, bbox_inches="tight")
    plt.close()
    return out


# ═══════════════════════════════════════════════════════════════════════════
# CANVAS FOOTER
# ═══════════════════════════════════════════════════════════════════════════
class Footer:
    def __init__(self, device_name):
        self.device = device_name

    def __call__(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_LIGHT)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(MARGIN, 0.9*cm,
            f"DHF — {self.device}  ·  DRAFT — AI-ASSISTED  ·  {date.today().isoformat()}")
        canvas.drawRightString(PAGE_W - MARGIN, 0.9*cm, f"Page {doc.page}")
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, 1.1*cm, PAGE_W - MARGIN, 1.1*cm)
        canvas.restoreState()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
def section_header(story, num, title, key):
    story += [
        Bookmark(key, f"{num}. {title}"),
        anchor(key),
        Paragraph(f"{num}. {title}", ST["h1"]),
        hr(1.2, C_NAVY),
    ]

def cover_page(story, intake):
    today = date.today().isoformat()
    # Solid dark background simulation using a wide Table cell
    cover_bg = Table(
        [[Paragraph(intake["device_name"], ST["cover_title"])]],
        colWidths=[CONTENT_W],
    )
    cover_bg.setStyle(TableStyle([
        ("BACKGROUND",      (0,0),(-1,-1), C_NAVY),
        ("TOPPADDING",      (0,0),(-1,-1), 28),
        ("BOTTOMPADDING",   (0,0),(-1,-1), 28),
        ("LEFTPADDING",     (0,0),(-1,-1), 16),
        ("RIGHTPADDING",    (0,0),(-1,-1), 16),
        ("ROUNDEDCORNERS",  (0,0),(-1,-1), [6,6,6,6]),
    ]))
    story += [
        sp(40),
        cover_bg,
        sp(16),
        Paragraph("Design History File", ST["cover_sub"]),
        sp(6),
        Paragraph(f"Model: {intake.get('model_number','[TBD]')}  ·  "
                  f"FDA Class {intake.get('fda_class','?')}  ·  "
                  f"EU MDR Class {intake.get('eu_mdr_class','?')}",
                  ST["cover_meta"]),
        sp(8),
        Paragraph(f"Compiled {today}  ·  Target markets: "
                  f"{', '.join(intake.get('target_markets', []))}",
                  ST["cover_meta"]),
        sp(30),
        DraftBanner(CONTENT_W),
        PageBreak(),
    ]

def toc(story):
    sections = [
        ("1", "DHF Index & Document Register",   "sec1"),
        ("2", "Design & Development Plan",        "sec2"),
        ("3", "Design Inputs",                    "sec3"),
        ("4", "Design Outputs",                   "sec4"),
        ("5", "Design Review Records",             "sec5"),
        ("6", "Design Verification",               "sec6"),
        ("7", "Design Validation",                 "sec7"),
        ("8", "Design Transfer",                   "sec8"),
        ("9", "Design Change Log",                 "sec9"),
        ("10", "Risk Management File",             "sec10"),
        ("11", "Traceability Matrix",              "sec11"),
        ("A",  "CSV Considerations",               "secA"),
    ]
    story += [
        Bookmark("toc", "Table of Contents"),
        anchor("toc"),
        Paragraph("Table of Contents", ST["h1"]),
        hr(1.2, C_NAVY),
        sp(4),
    ]
    for num, title, key in sections:
        story.append(Paragraph(
            f'<link href="#{key}">{num}.&nbsp;&nbsp;{title}</link>',
            ST["toc"]))
    story.append(PageBreak())

def sec_dhf_index(story, intake):
    today = date.today().isoformat()
    section_header(story, 1, "DHF Index & Document Register", "sec1")
    story += [
        reg_ref("21 CFR 820.30(j)", "ISO 13485:2016 §7.3.10"),
        sp(4),
        kv_table([
            ("Device name",     intake["device_name"]),
            ("Model number",    intake.get("model_number","[TBD]")),
            ("FDA class",       f"Class {intake.get('fda_class','[SME]')}"),
            ("EU MDR class",    f"Class {intake.get('eu_mdr_class','[SME]')}"),
            ("Target markets",  ", ".join(intake.get("target_markets",[]))),
            ("Compiled",        today),
            ("Compiled by",     "[SME-INPUT-REQUIRED]"),
        ]),
        sp(8),
        Paragraph("Master Document Register", ST["h2"]),
        grid_table(
            ["Doc ID","Title","Type","Rev","Effective Date","Approver"],
            [
                ["00","DHF Index","Index","A",today,"[SME]"],
                ["01","Design & Development Plan","Plan","A",today,"[SME]"],
                ["02","Design Inputs","Spec","A",today,"[SME]"],
                ["03","Design Outputs","Spec","A",today,"[SME]"],
                ["04","Design Review Records","Record","A",today,"[SME]"],
                ["05","Design Verification","Plan/Report","A",today,"[SME]"],
                ["06","Design Validation","Plan/Report","A",today,"[SME]"],
                ["07","Design Transfer","Plan","A",today,"[SME]"],
                ["08","Design Change Log","Record","A",today,"[SME]"],
                ["09","Risk Management File","RMF","A",today,"[SME]"],
                ["10","Traceability Matrix","Matrix","A",today,"[SME]"],
            ],
            widths=[1.4*cm, 5.2*cm, 2.4*cm, 1.0*cm, 3.0*cm, CONTENT_W-13.0*cm]
        ),
        sp(6),
        Paragraph("Records Retention",  ST["h2"]),
        Paragraph(
            "Per 21 CFR 820.180 and ISO 13485:2016 §4.2.5: device lifetime "
            "+ statutory retention period (commonly 10–15 years post-end-of-life, "
            "market-dependent). Original signed records must be retained in the "
            "controlled QMS document management system.", ST["body"]),
        PageBreak(),
    ]

def sec_ddplan(story, intake, imgs):
    section_header(story, 2, "Design & Development Plan", "sec2")
    story += [
        DraftBanner(CONTENT_W), sp(4),
        reg_ref("21 CFR 820.30(b)", "ISO 13485:2016 §7.3.2", "EU MDR Annex II §3"),
        sp(4),
        Paragraph("1. Purpose & Scope", ST["h2"]),
        Paragraph(
            f"This plan describes design and development activities, responsibilities, "
            f"interfaces, and review gates for the {intake['device_name']}. "
            "All design activities shall follow this plan; deviations require formal "
            "change control.", ST["body"]),
        sp(4),
        Paragraph("2. Device Description & Intended Use", ST["h2"]),
        kv_table([
            ("Intended use",        intake["intended_use"]),
            ("Indications for use", intake["indications_for_use"]),
            ("Predicate / equiv.",  intake.get("predicate_device","[SME-INPUT-REQUIRED]")),
        ]),
        sp(6),
        Paragraph("3. Regulatory Classification", ST["h2"]),
        kv_table([
            ("FDA classification",  f"Class {intake.get('fda_class','[SME]')} "
                                    "— submission pathway TBD per SME"),
            ("EU MDR classification", f"Class {intake.get('eu_mdr_class','[SME]')}"),
            ("Patient contacting",  "Yes" if intake.get("patient_contacting") else "No"),
            ("Sterile",             "Yes" if intake.get("sterile") else "No"),
            ("Contains software",   "Yes (IEC 62304 applies)" if intake.get("contains_software") else "No"),
            ("Implantable",         "Yes" if intake.get("implantable") else "No"),
            ("Reusable",            "Yes" if intake.get("reusable") else "No"),
            ("Electromedical",      "Yes (IEC 60601-1 applies)" if intake.get("electromedical") else "No"),
        ]),
        sp(8),
        Paragraph("4. Design Control V-Model", ST["h2"]),
        Image(imgs["vmodel"], width=CONTENT_W, height=3.6*cm),
        Paragraph("Figure 2.1: Design Control V-Model — horizontal dashed lines indicate "
                  "V&V traceability. Source: AI-generated; verify before regulatory use.",
                  ST["caption"]),
        sp(6),
        Paragraph("5. Design & Development Phases", ST["h2"]),
        grid_table(
            ["Phase","Name","Key Activities","Exit Criteria"],
            [
                ["0","Concept / Feasibility","Market research, predicate analysis","Feasibility report approved"],
                ["1","Design Inputs","User needs → requirements, risk identification","DI document baselined"],
                ["2","Design & Prototyping","Prototype build, bench tests","Prototype test report"],
                ["3","Design Verification","V&V per test protocols","All acceptance criteria met"],
                ["4","Design Validation","Simulated-use / clinical validation","Validation report approved"],
                ["5","Design Transfer","DMR, manufacturing release","Transfer checklist signed"],
                ["6","Post-Market","PMS, PSUR, complaint handling","Ongoing"],
            ],
            widths=[1.2*cm, 3.6*cm, 5.0*cm, CONTENT_W-9.8*cm]
        ),
        sp(6),
        Paragraph("6. Roles & Responsibilities", ST["h2"]),
        grid_table(
            ["Role","Function","Responsibility"],
            [
                ["Project Lead","[SME]","Overall DHF ownership"],
                ["R&D Engineer","[SME]","Design execution"],
                ["Quality Engineer","[SME]","QMS conformance, document control"],
                ["Regulatory Lead","[SME]","Submission strategy"],
                ["Clinical Lead","[SME]","Clinical evaluation, validation"],
                ["Independent Reviewer","[SME]","Per 21 CFR 820.30(e)"],
            ],
            widths=[3.2*cm, 3.2*cm, CONTENT_W-6.4*cm]
        ),
        sp(6),
        Paragraph("7. Design Review Gates", ST["h2"]),
        grid_table(
            ["Gate","Review","Planned Date","Mandatory Reviewers"],
            [
                ["G0","Concept Review","[DATE]","Project Lead, Regulatory"],
                ["G1","Inputs Frozen","[DATE]","All functions"],
                ["G2","Design Complete","[DATE]","All functions + Independent"],
                ["G3","V&V Complete","[DATE]","QA, Regulatory, Clinical"],
                ["G4","Transfer Approved","[DATE]","QA, Manufacturing, QC"],
                ["G5","Launch Release","[DATE]","Management sign-off"],
            ],
            widths=[1.2*cm, 3.5*cm, 3.0*cm, CONTENT_W-7.7*cm]
        ),
        PageBreak(),
    ]

def sec_design_inputs(story, intake, imgs):
    section_header(story, 3, "Design Inputs", "sec3")
    story += [
        DraftBanner(CONTENT_W), sp(4),
        reg_ref("21 CFR 820.30(c)", "ISO 13485:2016 §7.3.3", "EU MDR Annex II §3"),
        sp(4),
        Paragraph(
            f"Defines physical, performance, safety, and regulatory requirements "
            f"the {intake['device_name']} must meet prior to design output generation.",
            ST["body"]),
        sp(4),
        Paragraph("1. Functional Block Diagram", ST["h2"]),
        Image(imgs["block"], width=CONTENT_W, height=2.2*cm),
        Paragraph("Figure 3.1: Functional decomposition. Source: AI-generated stub — "
                  "expand with actual subsystems.", ST["caption"]),
        sp(6),
        Paragraph("2. User Needs", ST["h2"]),
        grid_table(
            ["UN-ID","User Need","Intended User","Source"],
            [["UN-001","[SME-INPUT-REQUIRED]","[Clinical user]","[VOC / predicate analysis]"]],
            widths=[1.5*cm, 5.5*cm, 3.5*cm, CONTENT_W-10.5*cm]
        ),
        sp(6),
        Paragraph("3. Functional / Performance Requirements", ST["h2"]),
        grid_table(
            ["DI-ID","Requirement","Source","Acceptance Criterion","Verification Method"],
            [["DI-F-001","[SME-INPUT-REQUIRED]","UN-001","[SME-VALUE]","[SME-METHOD]"]],
            widths=[1.8*cm, 4.5*cm, 2.0*cm, 3.5*cm, CONTENT_W-11.8*cm]
        ),
        sp(4),
        sme("Add all functional/performance requirements with quantified acceptance criteria."),
        sp(6),
        Paragraph("4. Additional Requirement Categories", ST["h2"]),
    ]

    categories = [
        ("4.1 Mechanical / Physical", "[SME-INPUT-REQUIRED: dimensions, materials, mechanical loads]"),
        ("4.2 Electrical", ("IEC 60601-1 and IEC 60601-1-2 (EMC) apply — "
                            "[SME-INPUT-REQUIRED]")
         if intake.get("electromedical") else "Not applicable — non-electromedical device."),
        ("4.3 Biocompatibility",
         f"ISO 10993-1 biological evaluation required — "
         f"contact category: {'implant' if intake.get('implantable') else 'surface'}; "
         f"duration: {'long-term (>30 days)' if intake.get('implantable') else 'limited (<24 h)'}. "
         "[SME-INPUT-REQUIRED: material characterisation data]"
         if intake.get("patient_contacting") else "Not applicable."),
        ("4.4 Sterility",
         "SAL 10<super>-6</super> required — applicable sterilization standard per SME "
         "(ISO 11135 / ISO 11137 / ISO 17665). [SME-INPUT-REQUIRED]"
         if intake.get("sterile") else "Not applicable — device is non-sterile."),
        ("4.5 Software (IEC 62304)",
         "Safety classification per IEC 62304 §4.3 must be determined. See Figure 3.2 below. "
         "[SME-INPUT-REQUIRED]"
         if intake.get("contains_software") else "Not applicable — no software."),
        ("4.6 Cybersecurity",
         "Per FDA premarket cybersecurity guidance (2023) and IEC 81001-5-1. "
         "[SME-INPUT-REQUIRED]"
         if intake.get("contains_software") else "Not applicable."),
        ("4.7 Cleaning / Reprocessing",
         "ISO 17664 validation required — reusable device. [SME-INPUT-REQUIRED]"
         if intake.get("reusable") else "Not applicable — single-use device."),
        ("4.8 Shelf Life / Stability", "Per ASTM F1980 accelerated aging. [SME-INPUT-REQUIRED]"),
        ("4.9 Usability / Human Factors", "Per IEC 62366-1 and FDA HF guidance (2016). [SME-INPUT-REQUIRED]"),
        ("4.10 Labelling & IFU", "Per 21 CFR 801, EU MDR Annex I §23, ISO 15223-1 symbols. [SME-INPUT-REQUIRED]"),
        ("4.11 Risk-Derived Inputs", "Risk control measures from RMF that become design inputs. [SME-INPUT-REQUIRED]"),
    ]
    for title, body in categories:
        story += [Paragraph(title, ST["h3"]), Paragraph(body, ST["body"])]

    if intake.get("contains_software"):
        story += [
            sp(4),
            Paragraph("IEC 62304 Software Safety Classification Tree", ST["h2"]),
            Image(imgs["sw_class"], width=CONTENT_W*0.8, height=3.4*cm),
            Paragraph("Figure 3.2: IEC 62304 software safety classification. "
                      "Source: AI-generated.", ST["caption"]),
        ]
    story.append(PageBreak())

def _simple_section(story, num, title, key, reg, device_name, subsections, note=""):
    section_header(story, num, title, key)
    story += [
        DraftBanner(CONTENT_W), sp(4),
        Paragraph(reg, ST["reg"]), sp(6),
    ]
    if note:
        story.append(Paragraph(note, ST["body"]))
        story.append(sp(4))
    for heading, body in subsections:
        story += [Paragraph(heading, ST["h2"]), Paragraph(body, ST["body"]), sp(2)]
    story.append(PageBreak())

def sec_design_outputs(story, intake):
    _simple_section(story, 4, "Design Outputs", "sec4",
        "21 CFR 820.30(d) | ISO 13485:2016 §7.3.4",
        intake["device_name"],
        [
            ("1. Device Master Record (DMR) Index",
             "DMR shall include: drawings, specifications, BOM, manufacturing procedures, "
             "quality plans, labelling, and packaging specifications. [SME-INPUT-REQUIRED]"),
            ("2. Essential Design Outputs Table",
             "Identify outputs that are essential to proper functioning (21 CFR 820.30(d)). "
             "[SME-INPUT-REQUIRED: complete output list with document references]"),
            ("3. Drawings & Specifications",
             "Engineering drawings shall be revision-controlled per the QMS. "
             "[SME-INPUT-REQUIRED]"),
            ("4. Bill of Materials (BOM)",
             "Full BOM with part numbers, revision levels, and approved suppliers. "
             "[SME-INPUT-REQUIRED]"),
            ("5. Approval Block",
             "[SME-INPUT-REQUIRED: author, reviewer, approver signatures and dates]"),
        ])

def sec_design_review(story, intake):
    _simple_section(story, 5, "Design Review Records", "sec5",
        "21 CFR 820.30(e) | ISO 13485:2016 §7.3.5",
        intake["device_name"],
        [
            ("1. Review Record Template",
             "Each formal review shall document: date, attendees, agenda, findings, "
             "action items (owner + due date), and disposition (pass / conditional / fail)."),
            ("2. Review Schedule",
             "Reviews planned at each V-model gate (G0–G5). See Section 2 (Design Plan)."),
            ("3. Independent Reviewer",
             "At least one reviewer must be independent of the design team per 21 CFR 820.30(e). "
             "[SME-INPUT-REQUIRED: confirm reviewer identity and independence declaration]"),
        ])

def sec_verification(story, intake):
    _simple_section(story, 6, "Design Verification", "sec6",
        "21 CFR 820.30(f) | ISO 13485:2016 §7.3.6",
        intake["device_name"],
        [
            ("1. Verification Plan",
             "Verification confirms design outputs meet design inputs. Each DI-ID shall "
             "have at least one corresponding verification test. [SME-INPUT-REQUIRED: test matrix]"),
            ("2. Verification Test Summary",
             "[SME-INPUT-REQUIRED: test ID, method, acceptance criterion, result, pass/fail]"),
            ("3. Statistical Considerations",
             "Sample sizes and confidence/reliability levels per applicable standards. "
             "[SME-INPUT-REQUIRED]"),
            ("4. Verification Report",
             "Final report summarising all verification activities. [SME-INPUT-REQUIRED]"),
        ])

def sec_validation(story, intake):
    _simple_section(story, 7, "Design Validation", "sec7",
        "21 CFR 820.30(g) | ISO 13485:2016 §7.3.7 | EU MDR Annex XIV",
        intake["device_name"],
        [
            ("1. Validation Plan",
             "Validation confirms device meets user needs under actual/simulated conditions "
             "of use. Simulated-use testing, clinical evaluation, or both may be required. "
             "[SME-INPUT-REQUIRED]"),
            ("2. Simulated-Use Testing",
             "Per IEC 62366-1 usability engineering process. [SME-INPUT-REQUIRED]"),
            ("3. Clinical Evidence",
             "Clinical evaluation report per EU MDR Annex XIV and FDA guidance. "
             "[SME-INPUT-REQUIRED]"),
            ("4. Validation Report",
             "Final report summarising all validation activities. [SME-INPUT-REQUIRED]"),
        ])

def sec_transfer(story, intake):
    _simple_section(story, 8, "Design Transfer", "sec8",
        "21 CFR 820.30(h) | ISO 13485:2016 §7.3.8",
        intake["device_name"],
        [
            ("1. Transfer Checklist",
             "Confirms DMR completeness, manufacturing capability, quality plan, "
             "training records, and tooling/equipment qualification. [SME-INPUT-REQUIRED]"),
            ("2. Scale-Up / First Article Inspection",
             "[SME-INPUT-REQUIRED]"),
            ("3. Process Validation",
             "IQ / OQ / PQ for critical manufacturing processes. [SME-INPUT-REQUIRED]"),
        ])

def sec_change_log(story, intake):
    section_header(story, 9, "Design Change Log", "sec9")
    story += [
        DraftBanner(CONTENT_W), sp(4),
        reg_ref("21 CFR 820.30(i)", "ISO 13485:2016 §7.3.9"), sp(6),
        Paragraph(
            "All design changes after baseline must be documented below and "
            "assessed for impact on verification, validation, and regulatory status.",
            ST["body"]), sp(4),
        grid_table(
            ["DCR-ID","Description","Initiator","Date","Impact Assessment",
             "Affected Docs","Approval","Status"],
            [["DCR-001","[SME-INPUT-REQUIRED]","[SME]","[DATE]",
              "[SME]","[SME]","[SME]","Open"]],
            widths=[1.8*cm,4.0*cm,1.8*cm,1.8*cm,2.5*cm,2.0*cm,1.8*cm,
                    CONTENT_W-15.7*cm]
        ),
        PageBreak(),
    ]

def sec_rmf(story, intake, imgs):
    section_header(story, 10, "Risk Management File", "sec10")
    story += [
        DraftBanner(CONTENT_W), sp(4),
        reg_ref("ISO 14971:2019", "ISO/TR 24971:2020",
                "EN ISO 14971:2019/A11:2021 (EU)", "21 CFR 820.30(g)"), sp(6),
        Paragraph("1. Risk Management Process", ST["h2"]),
        Image(imgs["iso14971"], width=CONTENT_W, height=2.8*cm),
        Paragraph("Figure 10.1: ISO 14971:2019 Risk Management Process. "
                  "Source: AI-generated.", ST["caption"]),
        sp(6),
        Paragraph("2. Risk Acceptability Matrix", ST["h2"]),
        Image(imgs["risk_matrix"], width=CONTENT_W*0.72, height=4.2*cm),
        Paragraph("Figure 10.2: 5×5 Risk Acceptability Matrix. Severity and probability "
                  "scale anchors must be confirmed by the risk management team [SME-CONFIRM].",
                  ST["caption"]),
        sp(6),
        Paragraph("3. Severity Scale", ST["h2"]),
        grid_table(
            ["Level","Term","Definition"],
            [
                ["5","Catastrophic","Patient death"],
                ["4","Critical","Permanent impairment / life-threatening injury"],
                ["3","Serious","Injury requiring medical intervention"],
                ["2","Minor","Temporary discomfort or injury"],
                ["1","Negligible","Inconvenience or transient minor effect"],
            ],
            widths=[1.5*cm, 3.5*cm, CONTENT_W-5.0*cm]
        ),
        sp(4),
        Paragraph("4. Probability Scale", ST["h2"]),
        grid_table(
            ["Level","Term","Approx. Frequency"],
            [
                ["5","Frequent",   "> 10<super>-3</super> per use"],
                ["4","Probable",   "10<super>-3</super> – 10<super>-4</super>"],
                ["3","Occasional", "10<super>-4</super> – 10<super>-5</super>"],
                ["2","Remote",     "10<super>-5</super> – 10<super>-6</super>"],
                ["1","Improbable", "< 10<super>-6</super>"],
            ],
            widths=[1.5*cm, 3.5*cm, CONTENT_W-5.0*cm]
        ),
        sp(6),
        Paragraph("5. Hazard Identification", ST["h2"]),
        Paragraph(
            "Per ISO 14971 §5.4, identify hazards across: energy hazards "
            "(mechanical, thermal, electrical, radiation), biological & chemical hazards "
            "(biocompatibility, contamination), operational hazards (function loss, "
            "unintended function, use error), and information hazards (labelling, "
            "IFU comprehensibility). [SME-INPUT-REQUIRED: full hazard list]",
            ST["body"]),
        sp(4),
        Paragraph("6. Risk Control Hierarchy (ISO 14971 §7.1)", ST["h2"]),
        Paragraph("1. Inherent safety by design (most preferred)\n"
                  "2. Protective measures in device or manufacturing\n"
                  "3. Information for safety in IFU (least preferred)", ST["body"]),
        sp(4),
        Paragraph("7. FMEA Documents", ST["h2"]),
        Paragraph(
            "Three FMEAs maintained as separate controlled workbooks: "
            "dFMEA (Design), pFMEA (Process), uFMEA (Use/Human Factors per IEC 62366-1). "
            "[SME-INPUT-REQUIRED]", ST["body"]),
        sp(4),
        Paragraph("8. Overall Residual Risk Evaluation", ST["h2"]),
        sme("Benefit-risk analysis per EU MDR Annex I §1 and §8 required here."),
        PageBreak(),
    ]

def sec_traceability(story, imgs):
    section_header(story, 11, "Traceability Matrix", "sec11")
    story += [
        DraftBanner(CONTENT_W), sp(4),
        reg_ref("21 CFR 820.30(j)", "ISO 13485:2016 §7.3.10"), sp(4),
        Paragraph(
            "The traceability matrix links every user need through design inputs, "
            "outputs, verification, validation, and risk controls. Every row must "
            "be complete before DHF closure.", ST["body"]),
        sp(4),
        Image(imgs["traceability"], width=CONTENT_W, height=2.0*cm),
        Paragraph("Figure 11.1: DHF Traceability Chain. Source: AI-generated.",
                  ST["caption"]),
        sp(6),
        grid_table(
            ["UN-ID","User Need","DI-ID","Design Input","DO-ID","Design Output",
             "DV-ID","Verification","DVA-ID","Validation","Risk-ID","Risk Control"],
            [["UN-001","[SME]","DI-001","[SME]","DO-001","[SME]",
              "DV-001","[SME]","DVA-001","[SME]","R-001","[SME]"]],
            widths=[1.3]*12 if False else None
        ),
        sp(4),
        sme("Populate this matrix fully before regulatory submission."),
        PageBreak(),
    ]

def sec_csv(story):
    section_header(story, "A", "CSV Considerations", "secA")
    story += [
        DraftBanner(CONTENT_W), sp(4),
        reg_ref("21 CFR Part 11", "FDA QMSR (2024)", "GAMP 5"), sp(6),
        Paragraph(
            "This DHF was generated with AI assistance. Any software producing "
            "GxP records must be validated for intended use before outputs enter "
            "the controlled QMS document management system.", ST["body"]),
        sp(4),
        Paragraph("Risk Classification (GAMP 5)", ST["h2"]),
        sme("Typically GAMP Category 5 — bespoke/configured. Confirm with QA."),
        sp(4),
        Paragraph("Required Validation Activities", ST["h2"]),
        grid_table(
            ["Activity","Description","Owner","Status"],
            [
                ["URS","User Requirement Specification","QA","[SME]"],
                ["FS","Functional Specification","IT/Dev","[SME]"],
                ["DS","Design Specification","IT/Dev","[SME]"],
                ["IQ","Installation Qualification","QA","[SME]"],
                ["OQ","Operational Qualification","QA","[SME]"],
                ["PQ","Performance Qualification","QA","[SME]"],
                ["TM","Traceability Matrix URS→FS→DS→tests","QA","[SME]"],
            ],
            widths=[1.5*cm, 6.0*cm, 2.5*cm, CONTENT_W-10.0*cm]
        ),
        sp(6),
        Paragraph(
            "No output from this tool is considered released or controlled until it has "
            "completed the customer's QMS-controlled review and approval process.",
            ST["body"]),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# MAIN BUILD FUNCTION
# ═══════════════════════════════════════════════════════════════════════════
def build_pdf(intake: dict, output_path: str):
    with tempfile.TemporaryDirectory() as tmp:
        print("  Generating diagrams...")
        imgs = {
            "vmodel":       gen_vmodel(intake["device_name"], tmp),
            "iso14971":     gen_iso14971(tmp),
            "risk_matrix":  gen_risk_matrix(tmp),
            "block":        gen_block_diagram(intake["device_name"], tmp),
            "traceability": gen_traceability_overview(tmp),
        }
        if intake.get("contains_software"):
            imgs["sw_class"] = gen_sw_classification(tmp)

        print("  Building PDF story...")
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN, bottomMargin=MARGIN + 0.6*cm,
            title=f"DHF — {intake['device_name']}",
            author="dhf_export.py — AI-Assisted Draft",
            subject="Design History File",
        )

        story = []
        cover_page(story, intake)
        toc(story)
        sec_dhf_index(story, intake)
        sec_ddplan(story, intake, imgs)
        sec_design_inputs(story, intake, imgs)
        sec_design_outputs(story, intake)
        sec_design_review(story, intake)
        sec_verification(story, intake)
        sec_validation(story, intake)
        sec_transfer(story, intake)
        sec_change_log(story, intake)
        sec_rmf(story, intake, imgs)
        sec_traceability(story, imgs)
        sec_csv(story)

        footer = Footer(intake["device_name"])
        doc.build(story, onFirstPage=footer, onLaterPages=footer)

    print(f"  PDF written → {output_path}")


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="DHF Builder + PDF Exporter (integrated, no subprocess diagrams)")
    parser.add_argument("--intake", required=True, help="Device intake JSON file")
    parser.add_argument("--out",    default="DHF_Report.pdf", help="Output PDF path")
    args = parser.parse_args()

    intake = json.loads(Path(args.intake).read_text())
    print(f"\nDHF Builder → {intake['device_name']}")
    print(f"Output: {args.out}\n")
    build_pdf(intake, args.out)
    print("\nDone.")


if __name__ == "__main__":
    main()

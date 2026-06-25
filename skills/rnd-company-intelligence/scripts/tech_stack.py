#!/usr/bin/env python3
"""
dhf_export.py  —  Design History File (DHF) Builder & PDF Exporter
===================================================================
Generates a complete, professionally formatted Design History File (DHF)
as a multi-section PDF, with embedded Matplotlib charts, colour-coded
risk matrices, V-model diagrams, and full regulatory cross-references.

Usage:
    python dhf_export.py --intake intake.json --out DHF_Report.pdf

Minimum intake.json schema:
{
  "device_name":        "string",
  "model_number":       "string",
  "intended_use":       "string",
  "indications_for_use":"string",
  "fda_class":          "I | II | III",
  "eu_mdr_class":       "I | IIa | IIb | III",
  "patient_contacting": true,
  "sterile":            false,
  "contains_software":  false,
  "electromedical":     false,
  "reusable":           false,
  "implantable":        false,
  "target_markets":     ["US", "EU"]
}
"""

import argparse, json, os, tempfile
from pathlib import Path
from datetime import date

# ── Matplotlib (headless) ─────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
import numpy as np

# ── ReportLab ─────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, HRFlowable, Image, KeepTogether, ListFlowable,
    ListItem,
)
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib.colors import HexColor

# ══════════════════════════════════════════════════════════════════════════
# GLOBAL CONSTANTS & COLOUR PALETTE
# ══════════════════════════════════════════════════════════════════════════
PAGE_W, PAGE_H = A4
MARGIN    = 1.8 * cm
CONTENT_W = PAGE_W - 2 * MARGIN
TODAY     = date.today().isoformat()

# Brand palette
C_INK       = HexColor("#0D1117")   # near-black
C_NAVY      = HexColor("#0F2D52")   # primary dark
C_BLUE      = HexColor("#1A5FA8")   # primary mid
C_AZURE     = HexColor("#2E86C1")   # accent
C_TEAL      = HexColor("#0E9F8E")   # success / go
C_EMERALD   = HexColor("#16A34A")   # green
C_AMBER     = HexColor("#D97706")   # warning
C_ORANGE    = HexColor("#EA580C")   # strong warning
C_RED       = HexColor("#C0392B")   # danger
C_PURPLE    = HexColor("#6D28D9")   # special
C_SLATE     = HexColor("#475569")   # mid text
C_COOL      = HexColor("#94A3B8")   # light text
C_RULE      = HexColor("#CBD5E1")   # dividers
C_SHADE     = HexColor("#F1F5F9")   # alt row
C_SHADE2    = HexColor("#E0F2FE")   # light blue tint
C_AMBER_BG  = HexColor("#FFFBEB")   # draft banner bg
C_WHITE     = colors.white

# DRAFT_NOTICE removed

# ══════════════════════════════════════════════════════════════════════════
# STYLE SHEET
# ══════════════════════════════════════════════════════════════════════════
def _ps(name, **kw):
    return ParagraphStyle(name, **kw)

ST = {
    # Cover
    "cover_title":   _ps("cover_title",   fontName="Helvetica-Bold",   fontSize=30, leading=38, textColor=C_WHITE, alignment=TA_CENTER),
    "cover_tag":     _ps("cover_tag",     fontName="Helvetica",        fontSize=13, leading=18, textColor=HexColor("#94A3B8"), alignment=TA_CENTER),
    "cover_meta":    _ps("cover_meta",    fontName="Helvetica",        fontSize=9,  leading=14, textColor=HexColor("#CBD5E1"), alignment=TA_CENTER),
    "cover_warn":    _ps("cover_warn",    fontName="Helvetica-Bold",   fontSize=7.5,leading=11, textColor=HexColor("#92400E"), alignment=TA_CENTER),
    # Headings
    "part":          _ps("part",          fontName="Helvetica-Bold",   fontSize=18, leading=24, textColor=C_WHITE, alignment=TA_CENTER, spaceBefore=0, spaceAfter=0),
    "h1":            _ps("h1",            fontName="Helvetica-Bold",   fontSize=14, leading=19, textColor=C_NAVY,  spaceBefore=14, spaceAfter=5,  keepWithNext=True),
    "h2":            _ps("h2",            fontName="Helvetica-Bold",   fontSize=11, leading=15, textColor=C_BLUE,  spaceBefore=10, spaceAfter=3,  keepWithNext=True),
    "h3":            _ps("h3",            fontName="Helvetica-Bold",   fontSize=9.5,leading=13, textColor=C_SLATE, spaceBefore=8,  spaceAfter=2,  keepWithNext=True),
    # Body
    "body":          _ps("body",          fontName="Helvetica",        fontSize=9,  leading=13.5, textColor=C_INK, spaceAfter=4, alignment=TA_JUSTIFY),
    "body_left":     _ps("body_left",     fontName="Helvetica",        fontSize=9,  leading=13.5, textColor=C_INK, spaceAfter=3),
    "bullet":        _ps("bullet",        fontName="Helvetica",        fontSize=9,  leading=13.5, textColor=C_INK, leftIndent=14, firstLineIndent=-10, spaceAfter=2),
    "num_bullet":    _ps("num_bullet",    fontName="Helvetica",        fontSize=9,  leading=13.5, textColor=C_INK, leftIndent=18, firstLineIndent=-14, spaceAfter=2),
    # Table cells
    "th":            _ps("th",            fontName="Helvetica-Bold",   fontSize=8,  leading=10, textColor=C_WHITE),
    "td":            _ps("td",            fontName="Helvetica",        fontSize=8.5,leading=11, textColor=C_INK),
    "td_bold":       _ps("td_bold",       fontName="Helvetica-Bold",   fontSize=8.5,leading=11, textColor=C_INK),
    "td_mono":       _ps("td_mono",       fontName="Courier",          fontSize=8,  leading=10, textColor=C_INK),
    "label":         _ps("label",         fontName="Helvetica-Bold",   fontSize=8,  leading=11, textColor=C_SLATE),
    "value":         _ps("value",         fontName="Helvetica",        fontSize=9,  leading=12, textColor=C_INK),
    # Navigation
    "toc":           _ps("toc",           fontName="Helvetica",        fontSize=10, leading=19, textColor=C_INK,  leftIndent=4),
    "toc_sub":       _ps("toc_sub",       fontName="Helvetica",        fontSize=9,  leading=16, textColor=C_SLATE,leftIndent=22),
    # Special
    "sme":           _ps("sme",           fontName="Helvetica-Bold",   fontSize=8.5,leading=12, textColor=HexColor("#92400E"), spaceBefore=3, spaceAfter=3),
    "reg":           _ps("reg",           fontName="Helvetica-Oblique",fontSize=7.5,leading=10, textColor=C_AZURE, spaceAfter=4),
    "caption":       _ps("caption",       fontName="Helvetica-Oblique",fontSize=7.5,leading=10, textColor=C_COOL, alignment=TA_CENTER, spaceBefore=3, spaceAfter=8),
    "notice":        _ps("notice",        fontName="Helvetica-Oblique",fontSize=8,  leading=12, textColor=C_SLATE, spaceAfter=4, alignment=TA_JUSTIFY),
    "tag_pill":      _ps("tag_pill",      fontName="Helvetica-Bold",   fontSize=7,  leading=9,  textColor=C_WHITE),
    "page_label":    _ps("page_label",    fontName="Helvetica",        fontSize=7,  leading=9,  textColor=C_COOL),
}

# ══════════════════════════════════════════════════════════════════════════
# CUSTOM FLOWABLES
# ══════════════════════════════════════════════════════════════════════════
class Bookmark(Flowable):
    """PDF bookmark + outline entry."""
    def __init__(self, key, title, level=0):
        super().__init__()
        self.key, self.title, self.level = key, title, level
        self.width = self.height = 0
    def wrap(self, aw, ah): return 0, 0
    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)


class SectionDivider(Flowable):
    """Full-width section part divider (dark background band)."""
    def __init__(self, num, title, subtitle=""):
        super().__init__()
        self.num = num
        self.title = title
        self.subtitle = subtitle
        self.height = 54
    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.height
    def draw(self):
        c = self.canv
        c.setFillColor(C_NAVY)
        c.roundRect(0, 0, self.width, self.height, 5, fill=1, stroke=0)
        c.setFillColor(C_AZURE)
        c.roundRect(0, 0, 40, self.height, 5, fill=1, stroke=0)
        c.rect(30, 0, 15, self.height, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(C_WHITE)
        c.drawCentredString(20, (self.height - 16) / 2 + 2, str(self.num))
        c.setFont("Helvetica-Bold", 13)
        c.drawString(52, (self.height - 13) / 2 + 8, self.title)
        if self.subtitle:
            c.setFont("Helvetica", 8)
            c.setFillColor(HexColor("#94A3B8"))
            c.drawString(52, (self.height - 13) / 2 - 6, self.subtitle)

class StatusPill(Flowable):
    """Coloured status pill badge."""
    STATUS_COLORS = {
        "APPROVED":    HexColor("#16A34A"),
        "IN REVIEW":   HexColor("#D97706"),
        "DRAFT":       HexColor("#6D28D9"),
        "OPEN":        HexColor("#2E86C1"),
        "CLOSED":      HexColor("#64748B"),
        "REQUIRED":    HexColor("#C0392B"),
        "N/A":         HexColor("#94A3B8"),
    }
    def __init__(self, status):
        super().__init__()
        self.status = status.upper()
        self.width = len(self.status) * 6 + 16
        self.height = 14
    def wrap(self, aw, ah): return self.width, self.height
    def draw(self):
        col = self.STATUS_COLORS.get(self.status, HexColor("#64748B"))
        c = self.canv
        c.setFillColor(col)
        c.roundRect(0, 1, self.width, self.height - 2, 5, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_WHITE)
        c.drawCentredString(self.width / 2, 5, self.status)


# ══════════════════════════════════════════════════════════════════════════
# LAYOUT HELPERS
# ══════════════════════════════════════════════════════════════════════════
def anchor(key):
    return Paragraph(f'<a name="{key}"/>', _ps("_a", fontSize=1, leading=1))

def hr(thick=0.5, col=None):
    return HRFlowable(width="100%", thickness=thick, color=col or C_RULE, spaceBefore=4, spaceAfter=6)

def sp(h=6): return Spacer(1, h)

def sme(text):
    return Paragraph(f"▶ SME INPUT REQUIRED: {text}", ST["sme"])

def reg_ref(*refs):
    pills = " &nbsp;|&nbsp; ".join(f'<font color="#1A5FA8"><b>{r}</b></font>' for r in refs)
    return Paragraph(pills, ST["reg"])

def info_box(text, accent=None, bg=None):
    """Coloured callout paragraph wrapped in a sidebar accent."""
    p = Paragraph(text, ST["notice"])
    t = Table([[p]], colWidths=[CONTENT_W - 14])
    accent = accent or C_AZURE
    bg = bg or C_SHADE2
    outer = Table(
        [[ Table([[""]],colWidths=[4],rowHeights=[None]),  t ]],
        colWidths=[4, CONTENT_W - 4], hAlign="LEFT"
    )
    outer.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), bg),
        ("BACKGROUND",    (0,0),(0,-1),  accent),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("TOPPADDING",    (0,0),(-1,-1), 7),
        ("BOTTOMPADDING", (0,0),(-1,-1), 7),
        ("LEFTPADDING",   (1,0),(1,-1),  8),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
        ("LEFTPADDING",   (0,0),(0,-1),  0),
        ("RIGHTPADDING",  (0,0),(0,-1),  0),
    ]))
    return outer


# ══════════════════════════════════════════════════════════════════════════
# TABLE BUILDERS
# ══════════════════════════════════════════════════════════════════════════
def kv_table(pairs, lw=5.0*cm, show_empty=False):
    """Two-column label/value table."""
    rows = []
    for k, v in pairs:
        if not v and not show_empty:
            continue
        rows.append([Paragraph(k, ST["label"]), Paragraph(str(v), ST["value"])])
    if not rows:
        return None
    t = Table(rows, colWidths=[lw, CONTENT_W - lw], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN",          (0,0),(-1,-1), "TOP"),
        ("ROWBACKGROUNDS",  (0,0),(-1,-1), [C_WHITE, C_SHADE]),
        ("LINEBELOW",       (0,0),(-1,-1), 0.35, C_RULE),
        ("LEFTPADDING",     (0,0),(-1,-1), 7),
        ("RIGHTPADDING",    (0,0),(-1,-1), 7),
        ("TOPPADDING",      (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",   (0,0),(-1,-1), 5),
        ("BOX",             (0,0),(-1,-1), 0.5, C_RULE),
    ]))
    return t

def grid_table(headers, rows, widths=None, compact=False):
    """Multi-column header/data table with styled header row."""
    if not rows:
        return None
    pad = 3 if compact else 5
    hrow = [Paragraph(h, ST["th"]) for h in headers]
    brows = [[Paragraph(str(c), ST["td"]) for c in r] for r in rows]
    cw = widths or [CONTENT_W / len(headers)] * len(headers)
    t = Table([hrow] + brows, colWidths=cw, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",      (0,0),(-1,0),   C_NAVY),
        ("ROWBACKGROUNDS",  (0,1),(-1,-1),  [C_WHITE, C_SHADE]),
        ("LINEBELOW",       (0,0),(-1,-1),  0.35, C_RULE),
        ("LINEBEFORE",      (0,0),(-1,-1),  0.35, C_RULE),
        ("BOX",             (0,0),(-1,-1),  0.5,  C_NAVY),
        ("VALIGN",          (0,0),(-1,-1),  "TOP"),
        ("LEFTPADDING",     (0,0),(-1,-1),  7),
        ("RIGHTPADDING",    (0,0),(-1,-1),  7),
        ("TOPPADDING",      (0,0),(-1,-1),  pad),
        ("BOTTOMPADDING",   (0,0),(-1,-1),  pad),
    ]))
    return t

def score_grid(headers, rows, widths=None, score_col=-1, thresholds=None):
    """Grid with colour-coded score column."""
    thresholds = thresholds or {1: C_EMERALD, 2: C_TEAL, 3: C_AMBER, 4: C_ORANGE, 5: C_RED}
    t = grid_table(headers, rows, widths)
    if t is None:
        return None
    # colour score cells
    for ri, row in enumerate(rows, start=1):
        try:
            val = int(str(row[score_col]).strip())
            col = next((c for k,c in sorted(thresholds.items()) if val <= k), C_RED)
            t.setStyle(TableStyle([("BACKGROUND", (score_col, ri),(score_col, ri), col),
                                    ("TEXTCOLOR",   (score_col, ri),(score_col, ri), C_WHITE)]))
        except Exception:
            pass
    return t

# ══════════════════════════════════════════════════════════════════════════
# MATPLOTLIB DIAGRAM GENERATORS
# ══════════════════════════════════════════════════════════════════════════
_RC = {
    "font.family":       "sans-serif",
    "font.sans-serif":   ["Arial", "DejaVu Sans"],
    "text.color":        "#0D1117",
    "axes.labelcolor":   "#475569",
    "xtick.color":       "#64748B",
    "ytick.color":       "#64748B",
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
}
def _rc(): [plt.rcParams.update({k: v}) for k, v in _RC.items()]

def _save(path, dpi=200):
    plt.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close()

# ── 1. V-Model ─────────────────────────────────────────────────────────
def gen_vmodel(device_name, tmp):
    _rc()
    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    ax.set_xlim(0, 16); ax.set_ylim(0, 7); ax.axis("off")

    left_phases  = ["User Needs\n& Requirements", "Design\nInputs", "Design\nOutputs", "Build &\nPrototype"]
    right_phases = ["Design\nValidation", "Design\nVerification", "Design\nReview", "Unit\nTesting"]
    lc = ["#0F2D52","#1A5FA8","#2E86C1","#0E9F8E"]
    rc = ["#16A34A","#D97706","#EA580C","#6D28D9"]

    xs = [1, 3.2, 5.4, 7.6,   7.6, 9.8, 12.0, 14.2]
    ys = [6.2, 5.1, 3.8, 1.4,  1.4, 3.8, 5.1,  6.2]

    # Main V lines with gradient effect
    for i in range(3):
        ax.plot(xs[i:i+2], ys[i:i+2], color=lc[i+1], lw=2.8, zorder=2, solid_capstyle="round")
    for i in range(4, 7):
        ax.plot(xs[i:i+2], ys[i:i+2], color=rc[i-4], lw=2.8, zorder=2, solid_capstyle="round")

    # Bottom connection
    ax.plot([xs[3], xs[4]], [ys[3], ys[4]], color="#0E9F8E", lw=2.8,
            linestyle="--", zorder=2, dashes=(5, 3))
    ax.text(7.6, 0.6, "Design Transfer", ha="center", fontsize=8.5,
            color="#0E9F8E", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.35", fc="#ECFDF5", ec="#0E9F8E", lw=1.0, alpha=0.9))

    # Left nodes
    for i, (ph, col) in enumerate(zip(left_phases, lc)):
        ax.scatter(xs[i], ys[i], s=110, color=col, zorder=5, edgecolors="white", linewidths=1.2)
        ha = "right"; xoff = -0.3
        ax.text(xs[i]+xoff, ys[i]+0.32, ph, ha=ha, va="bottom", fontsize=8,
                color=col, fontweight="bold", linespacing=1.35)

    # Right nodes
    for i, (ph, col) in enumerate(zip(right_phases, rc)):
        j = i + 4
        ax.scatter(xs[j], ys[j], s=110, color=col, zorder=5, edgecolors="white", linewidths=1.2)
        ax.text(xs[j]+0.3, ys[j]+0.32, ph, ha="left", va="bottom", fontsize=8,
                color=col, fontweight="bold", linespacing=1.35)

    # Horizontal traceability arrows
    for i in range(4):
        yy = ys[i] - 0.05
        ax.annotate("", xy=(xs[7-i], yy), xytext=(xs[i], yy),
                    arrowprops=dict(arrowstyle="<->", color="#CBD5E1", lw=0.9,
                                   linestyle=(0,(4,3))))

    ax.set_title(f"{device_name} — Design Control V-Model  (21 CFR §820.30 / ISO 13485 §7.3)",
                 fontsize=10, fontweight="bold", color="#0F2D52", pad=12)
    out = os.path.join(tmp, "vmodel.png")
    _save(out)
    return out

# ── 2. ISO 14971 Flow ──────────────────────────────────────────────────
def gen_iso14971(tmp):
    _rc()
    stages = [
        ("Risk Mgmt\nPlanning",      "#0F2D52"),
        ("Hazard\nIdentification",   "#1A5FA8"),
        ("Risk\nEstimation",         "#2E86C1"),
        ("Risk\nEvaluation",         "#0E9F8E"),
        ("Risk\nControl",            "#16A34A"),
        ("Residual Risk\nEvaluation","#D97706"),
        ("Benefit-Risk\nAnalysis",   "#EA580C"),
        ("Risk Mgmt\nReport",        "#C0392B"),
    ]
    fig, ax = plt.subplots(figsize=(10, 2.8))
    ax.axis("off")
    n = len(stages)
    bw, bh, gap = 1.7, 1.2, 0.25
    total = n * bw + (n-1) * gap
    ax.set_xlim(-0.3, total + 0.3); ax.set_ylim(-0.5, 2.5)

    for i, (lbl, col) in enumerate(stages):
        x = i * (bw + gap)
        r = mpatches.FancyBboxPatch((x, 0.3), bw, bh, boxstyle="round,pad=0.08",
                                     fc=col, ec="white", lw=1.2, alpha=0.92)
        ax.add_patch(r)
        ax.text(x + bw/2, 0.3 + bh/2, lbl, ha="center", va="center",
                color="white", fontsize=7, fontweight="bold", linespacing=1.3)
        if i < n - 1:
            ax.annotate("", xy=(x + bw + gap, 0.3 + bh/2),
                        xytext=(x + bw, 0.3 + bh/2),
                        arrowprops=dict(arrowstyle="->", color="#94A3B8", lw=1.3))

    # Feedback loop arc
    ax.annotate("", xy=(0, 0.2), xytext=(total, 0.2),
                arrowprops=dict(arrowstyle="->", color="#CBD5E1", lw=1.0,
                                connectionstyle="arc3,rad=0.3"))
    ax.text(total/2, -0.3, "Post-market surveillance feedback loop",
            ha="center", fontsize=7, color="#94A3B8", style="italic")

    ax.set_title("ISO 14971:2019 — Risk Management Process",
                 fontsize=9.5, fontweight="bold", color="#0F2D52", pad=10)
    plt.tight_layout(rect=[0, 0.08, 1, 1])
    out = os.path.join(tmp, "iso14971.png")
    _save(out)
    return out

# ── 3. Risk Matrix ─────────────────────────────────────────────────────
def gen_risk_matrix(tmp):
    _rc()
    sev  = ["Negligible", "Minor", "Serious", "Critical", "Catastrophic"]
    prob = ["Improbable", "Remote", "Occasional", "Probable", "Frequent"]
    matrix = np.array([
        [1,1,2,2,3],
        [1,2,2,3,3],
        [2,2,3,3,4],
        [2,3,3,4,4],
        [3,3,4,4,5],
    ])
    palettes = {
        1: ("#DCFCE7", "#166534"),  # acceptable
        2: ("#FEF9C3", "#854D0E"),  # ALARP
        3: ("#FED7AA", "#9A3412"),  # undesirable
        4: ("#FECACA", "#991B1B"),  # unacceptable
        5: ("#FCA5A5", "#7F1D1D"),  # intolerable
    }
    labels = {1:"Acceptable", 2:"ALARP", 3:"Undesirable", 4:"Unacceptable", 5:"Intolerable"}

    fig, ax = plt.subplots(figsize=(7, 4.8))
    for r in range(5):
        for c in range(5):
            val = matrix[r, c]
            bg, fg = palettes[val]
            ax.add_patch(plt.Rectangle((c, 4-r), 1, 1, color=bg, ec="white", lw=1.5))
            ax.text(c+0.5, 4-r+0.5, labels[val], ha="center", va="center",
                    fontsize=8, color=fg, fontweight="bold")

    # Boundary lines
    for lvl, col, lw in [(3, "#D97706", 1.5), (4, "#C0392B", 2.0)]:
        # rough diagonal for visual cue
        pass

    ax.set_xlim(0, 5); ax.set_ylim(0, 5)
    ax.set_xticks([i+0.5 for i in range(5)])
    ax.set_xticklabels(sev, fontsize=8, rotation=15, ha="right")
    ax.set_yticks([i+0.5 for i in range(5)])
    ax.set_yticklabels(list(reversed(prob)), fontsize=8)
    ax.set_xlabel("Severity →", fontsize=8.5, color="#475569", labelpad=8)
    ax.set_ylabel("← Probability", fontsize=8.5, color="#475569", labelpad=8)
    ax.set_title("Risk Acceptability Matrix (5 × 5)",
                 fontsize=9.5, fontweight="bold", color="#0F2D52", pad=10)
    for s in ax.spines.values(): s.set_visible(False)

    # Legend
    from matplotlib.patches import Patch
    legend_els = [Patch(fc=palettes[k][0], ec="white", label=labels[k]) for k in sorted(palettes)]
    ax.legend(handles=legend_els, loc="upper left", bbox_to_anchor=(1.01, 1.0),
              fontsize=7.5, frameon=False)
    plt.tight_layout()
    out = os.path.join(tmp, "risk_matrix.png")
    _save(out)
    return out

# ── 4. Block Diagram ───────────────────────────────────────────────────
def gen_block_diagram(device_name, tmp):
    _rc()
    fig, ax = plt.subplots(figsize=(8, 2.6))
    ax.set_xlim(0, 12); ax.set_ylim(0, 3.5); ax.axis("off")

    def block(x, y, w, h, title, sub, col):
        r = mpatches.FancyBboxPatch((x, y), w, h,
            boxstyle="round,pad=0.12", fc=col, ec="white", lw=1.5, alpha=0.92)
        ax.add_patch(r)
        ax.text(x+w/2, y+h/2+0.12, title, ha="center", va="center",
                color="white", fontsize=8.5, fontweight="bold")
        ax.text(x+w/2, y+h/2-0.28, sub, ha="center", va="center",
                color="white", fontsize=6.5, alpha=0.88)

    def arr(x1, x2, y=1.75):
        ax.annotate("", xy=(x2, y), xytext=(x1, y),
                    arrowprops=dict(arrowstyle="-|>", color="#475569",
                                   lw=1.5, mutation_scale=14))

    block(0.3,  0.5, 2.6, 2.5, "INPUT",        "Sensors / A-D / Comm",  "#0F2D52")
    block(4.1,  0.5, 3.8, 2.5, "PROCESSING",   "Firmware / Algorithms", "#1A5FA8")
    block(9.0,  0.5, 2.6, 2.5, "OUTPUT",       "Display / Alerts / API","#0E9F8E")

    arr(2.9,  4.1)
    arr(7.9,  9.0)

    # Power / comms bus
    ax.plot([0.3, 11.6], [0.35, 0.35], color="#D97706", lw=1.2, linestyle="--", alpha=0.7)
    ax.text(6, 0.10, "Power & Communication Bus", ha="center", fontsize=7,
            color="#D97706", alpha=0.9)

    ax.set_title(f"{device_name} — Functional Block Architecture",
                 fontsize=9.5, fontweight="bold", color="#0F2D52", pad=8)
    plt.tight_layout()
    out = os.path.join(tmp, "block_diagram.png")
    _save(out)
    return out

# ── 5. IEC 62304 Classification ────────────────────────────────────────
def gen_sw_classification(tmp):
    _rc()
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis("off")

    def box(cx, cy, w, h, text, col, fs=8.5):
        r = mpatches.FancyBboxPatch((cx-w/2, cy-h/2), w, h,
            boxstyle="round,pad=0.1", fc=col, ec="white", lw=1.2, alpha=0.92, zorder=3)
        ax.add_patch(r)
        ax.text(cx, cy, text, ha="center", va="center",
                color="white", fontsize=fs, fontweight="bold", zorder=4, linespacing=1.3)

    def arr(x1,y1,x2,y2, lbl="", lblside="right"):
        ax.annotate("", xy=(x2,y2), xytext=(x1,y1),
                    arrowprops=dict(arrowstyle="-|>", color="#94A3B8",
                                   lw=1.4, mutation_scale=12), zorder=2)
        if lbl:
            mx,my = (x1+x2)/2, (y1+y2)/2
            xoff = 0.2 if lblside=="right" else -0.2
            ax.text(mx+xoff, my, lbl, fontsize=7.5, color="#475569",
                    fontweight="bold", ha="left" if lblside=="right" else "right")

    # Boxes
    box(6,   5.2, 5.5, 0.9, "Software Present in Medical Device?", "#0F2D52")
    box(6,   3.8, 5.0, 0.9, "Failure could cause hazardous\nsituation?", "#1A5FA8", 8)
    box(6,   2.4, 5.0, 0.9, "Severity: Serious injury\nor death possible?", "#2E86C1", 8)
    box(1.6, 1.0, 2.6, 0.9, "CLASS A\n(No hazard)", "#16A34A")
    box(6,   1.0, 2.6, 0.9, "CLASS B\n(Non-serious)", "#D97706")
    box(10,  1.0, 2.6, 0.9, "CLASS C\n(Fatal/Serious)", "#C0392B")

    # Arrows
    arr(6, 4.75, 6, 4.25)
    arr(6, 3.35, 6, 2.85)
    arr(3.5, 3.8, 1.6, 1.45, "No", "left")
    arr(6, 1.95, 6, 1.45, "No → Class B", "right")
    arr(8.5, 2.4, 10, 1.45, "Yes → C", "right")
    arr(3.5, 2.4, 1.6, 1.45)

    ax.text(3.4, 4.2, "No →\nClass A", fontsize=7.5, color="#16A34A", fontweight="bold")
    ax.text(6.2, 3.0, "Yes", fontsize=7.5, color="#C0392B", fontweight="bold")

    ax.set_title("IEC 62304:2006+AMD1:2015 — Software Safety Classification Decision Tree",
                 fontsize=9.5, fontweight="bold", color="#0F2D52", pad=8)
    plt.tight_layout()
    out = os.path.join(tmp, "sw_classification.png")
    _save(out)
    return out

# ── 6. Traceability Chain ──────────────────────────────────────────────
def gen_traceability(tmp):
    _rc()
    nodes = [
        ("User\nNeeds",     "#0F2D52"),
        ("Design\nInputs",  "#1A5FA8"),
        ("Design\nOutputs", "#2E86C1"),
        ("Verification",    "#0E9F8E"),
        ("Validation",      "#16A34A"),
        ("Risk\nControls",  "#D97706"),
    ]
    fig, ax = plt.subplots(figsize=(9, 2.2))
    ax.set_xlim(0, len(nodes)*3.0); ax.set_ylim(0, 2.8); ax.axis("off")
    bw, bh = 2.4, 1.4

    for i, (lbl, col) in enumerate(nodes):
        x = i * (bw + 0.5) + 0.2
        r = mpatches.FancyBboxPatch((x, 0.7), bw, bh,
            boxstyle="round,pad=0.12", fc=col, ec="white", lw=1.3, alpha=0.93)
        ax.add_patch(r)
        ax.text(x + bw/2, 0.7 + bh/2, lbl, ha="center", va="center",
                color="white", fontsize=8, fontweight="bold", linespacing=1.3)
        if i < len(nodes) - 1:
            ax.annotate("", xy=(x + bw + 0.5 - 0.05, 0.7 + bh/2),
                        xytext=(x + bw + 0.05, 0.7 + bh/2),
                        arrowprops=dict(arrowstyle="-|>", color="#94A3B8",
                                        lw=1.5, mutation_scale=13))

    # Back-arrows for bidirectional traceability
    total = len(nodes) * (bw + 0.5) - 0.2
    ax.annotate("", xy=(0.2, 0.6), xytext=(total - 0.1, 0.6),
                arrowprops=dict(arrowstyle="<-", color="#CBD5E1", lw=1.0,
                                connectionstyle="arc3,rad=0.0"))
    ax.text(total/2, 0.32, "← Bidirectional Traceability →",
            ha="center", fontsize=7, color="#94A3B8", style="italic")

    ax.set_title("DHF Traceability Chain (21 CFR §820.30(j) / ISO 13485 §7.3.10)",
                 fontsize=9.5, fontweight="bold", color="#0F2D52", pad=8)
    plt.tight_layout()
    out = os.path.join(tmp, "traceability.png")
    _save(out)
    return out

# ── 7. Project Timeline (Gantt stub) ───────────────────────────────────
def gen_gantt(tmp):
    _rc()
    tasks = [
        ("Concept & Feasibility",   0,  2,  "#0F2D52"),
        ("Design Inputs",           1,  3,  "#1A5FA8"),
        ("Design & Prototyping",    3,  6,  "#2E86C1"),
        ("Design Verification",     5,  8,  "#0E9F8E"),
        ("Design Validation",       7,  10, "#16A34A"),
        ("Design Transfer",         9,  11, "#D97706"),
        ("Regulatory Submission",   10, 12, "#C0392B"),
    ]
    months = ["M0","M1","M2","M3","M4","M5","M6","M7","M8","M9","M10","M11","M12"]
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.set_xlim(0, 12); ax.set_ylim(-0.5, len(tasks))
    ax.set_yticks(range(len(tasks)))
    ax.set_yticklabels([t[0] for t in reversed(tasks)], fontsize=8)
    ax.set_xticks(range(13))
    ax.set_xticklabels(months, fontsize=7.5)
    ax.grid(axis="x", color="#E2E8F0", lw=0.8, zorder=0)
    ax.set_axisbelow(True)

    for i, (name, start, end, col) in enumerate(reversed(tasks)):
        bar = mpatches.FancyBboxPatch((start, i - 0.3), end - start, 0.6,
            boxstyle="round,pad=0.04", fc=col, ec="white", lw=0.8, alpha=0.88)
        ax.add_patch(bar)
        ax.text(start + (end-start)/2, i, f"{end-start}m",
                ha="center", va="center", color="white", fontsize=7.5, fontweight="bold")

    for spine in ["top","right","left"]:
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#CBD5E1")

    ax.set_title("Design & Development Schedule (Indicative — SME to confirm dates)",
                 fontsize=9.5, fontweight="bold", color="#0F2D52", pad=8)
    plt.tight_layout()
    out = os.path.join(tmp, "gantt.png")
    _save(out)
    return out

# ── 8. FMEA Severity/Occurrence heatmap ────────────────────────────────
def gen_fmea_overview(tmp):
    _rc()
    cats = ["Biocompatibility", "EMC / RF", "Software Failure", "Mechanical", "Use Error", "Sterility"]
    sev  = [3, 4, 4, 3, 3, 4]
    occ  = [2, 3, 3, 2, 4, 1]
    det  = [2, 2, 2, 3, 3, 2]
    rpn  = [s*o*d for s,o,d in zip(sev,occ,det)]
    norm = np.array(rpn) / max(rpn)
    cols = [plt.cm.RdYlGn(1-n) for n in norm]

    fig, ax = plt.subplots(figsize=(8, 3.0))
    y = range(len(cats))
    bars = ax.barh(y, rpn, color=cols, edgecolor="white", linewidth=0.8, height=0.55)
    ax.set_yticks(list(y)); ax.set_yticklabels(cats, fontsize=8.5)
    ax.set_xlabel("Risk Priority Number (RPN = Sev × Occ × Det)", fontsize=8, color="#475569")
    ax.set_title("FMEA Hazard Category RPN Overview (Indicative — Values Require SME Confirmation)",
                 fontsize=9, fontweight="bold", color="#0F2D52", pad=8)

    for bar, val, s, o, d in zip(bars, rpn, sev, occ, det):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                f"RPN {val}  (S{s}·O{o}·D{d})",
                va="center", fontsize=7.5, color="#475569")

    ax.set_xlim(0, max(rpn) * 1.45)
    for sp in ["top","right"]:
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.spines["left"].set_color("#CBD5E1")
    ax.xaxis.set_tick_params(colors="#94A3B8")
    plt.tight_layout()
    out = os.path.join(tmp, "fmea_rpn.png")
    _save(out)
    return out

# ── 9. Regulatory Map ──────────────────────────────────────────────────
def gen_regulatory_map(markets, tmp):
    _rc()
    reg_data = {
        "US":        ("FDA 510(k) / PMA", "#1A5FA8"),
        "EU":        ("EU MDR 2017/745",  "#16A34A"),
        "Canada":    ("Health Canada",    "#0E9F8E"),
        "Australia": ("TGA ARTG",         "#D97706"),
        "Japan":     ("PMDA",             "#6D28D9"),
        "UK":        ("UKCA / MHRA",      "#EA580C"),
    }
    show = [m for m in markets if m in reg_data]
    if not show:
        show = list(reg_data.keys())[:4]

    angles = np.linspace(0, 2*np.pi, len(show), endpoint=False)
    fig, ax = plt.subplots(figsize=(5.5, 4.0), subplot_kw=dict(polar=True))
    values = [0.85] * len(show) + [0.85]
    angles_plot = list(angles) + [angles[0]]
    ax.fill(angles_plot, values, alpha=0.15, color="#1A5FA8")
    ax.plot(angles_plot, values, color="#1A5FA8", lw=2.0)

    for angle, market in zip(angles, show):
        lbl, col = reg_data[market]
        ax.scatter([angle], [0.85], s=100, color=col, zorder=5)
        r = 1.10
        ax.text(angle, r, f"{market}\n{lbl}", ha="center", va="center",
                fontsize=7, color=col, fontweight="bold", linespacing=1.3)

    ax.set_rticks([])
    ax.set_yticklabels([])
    ax.set_thetagrids([])
    ax.spines["polar"].set_visible(False)
    ax.set_title("Target Market Regulatory Pathway Map",
                 fontsize=9.5, fontweight="bold", color="#0F2D52", pad=18)
    plt.tight_layout()
    out = os.path.join(tmp, "regulatory_map.png")
    _save(out)
    return out

# ══════════════════════════════════════════════════════════════════════════
# PAGE FOOTER / RUNNING HEADER
# ══════════════════════════════════════════════════════════════════════════
class CanvasDecorator:
    def __init__(self, intake):
        self.device = intake["device_name"]
        self.model  = intake.get("model_number", "")
        self.fda    = intake.get("fda_class", "?")

    def __call__(self, canvas, doc):
        canvas.saveState()
        # ── Running header ──
        canvas.setFillColor(C_NAVY)
        canvas.rect(MARGIN, PAGE_H - 1.45*cm, CONTENT_W, 0.7*cm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.setFillColor(C_WHITE)
        canvas.drawString(MARGIN + 5, PAGE_H - 1.05*cm, "DESIGN HISTORY FILE  ·  CONTROLLED DOCUMENT")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(PAGE_W - MARGIN - 4, PAGE_H - 1.05*cm,
                               f"{self.device}  |  Model {self.model}  |  FDA Class {self.fda}")
        # ── Footer ──
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 1.25*cm, PAGE_W - MARGIN, 1.25*cm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(C_COOL)
        canvas.drawString(MARGIN, 0.85*cm, f"Confidential  ·  Generated {TODAY}")
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(C_SLATE)
        canvas.drawRightString(PAGE_W - MARGIN, 0.85*cm, f"Page {doc.page}")
        canvas.restoreState()

# ══════════════════════════════════════════════════════════════════════════
# SECTION HEADER HELPER
# ══════════════════════════════════════════════════════════════════════════
def section_header(story, num, title, key, subtitle=""):
    story += [
        Bookmark(key, f"{num}. {title}"),
        anchor(key),
        SectionDivider(num, title, subtitle),
        sp(8),
    ]

# ══════════════════════════════════════════════════════════════════════════
# COVER PAGE
# ══════════════════════════════════════════════════════════════════════════
def cover_page(story, intake):
    markets = ", ".join(intake.get("target_markets", []))

    # Hero band
    hero = Table([[Paragraph(intake["device_name"], ST["cover_title"])]],
                 colWidths=[CONTENT_W])
    hero.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_NAVY),
        ("TOPPADDING",    (0,0),(-1,-1), 36),
        ("BOTTOMPADDING", (0,0),(-1,-1), 36),
        ("LEFTPADDING",   (0,0),(-1,-1), 20),
        ("RIGHTPADDING",  (0,0),(-1,-1), 20),
        ("ROUNDEDCORNERS",(0,0),(-1,-1), [8,8,8,8]),
    ]))

    # Accent strip
    accent = Table([[""]], colWidths=[CONTENT_W], rowHeights=[0.22*cm])
    accent.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,-1), C_TEAL)]))

    # Meta band
    meta_rows = [
        [
            Paragraph("Document Type", ST["label"]),
            Paragraph("Design History File (DHF) — Master Dossier", ST["value"]),
        ],
        [
            Paragraph("Model Number", ST["label"]),
            Paragraph(intake.get("model_number", "[TBD]"), ST["value"]),
        ],
        [
            Paragraph("FDA Classification", ST["label"]),
            Paragraph(f"Class {intake.get('fda_class','?')}", ST["value"]),
        ],
        [
            Paragraph("EU MDR Classification", ST["label"]),
            Paragraph(f"Class {intake.get('eu_mdr_class','?')}", ST["value"]),
        ],
        [
            Paragraph("Target Markets", ST["label"]),
            Paragraph(markets, ST["value"]),
        ],
        [
            Paragraph("Manufacturer", ST["label"]),
            Paragraph(intake.get("manufacturer", "[SME-INPUT-REQUIRED]"), ST["value"]),
        ],
        [
            Paragraph("Compiled", ST["label"]),
            Paragraph(TODAY, ST["value"]),
        ],
    ]
    meta = Table(meta_rows, colWidths=[4.5*cm, CONTENT_W-4.5*cm])
    meta.setStyle(TableStyle([
        ("VALIGN",          (0,0),(-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS",  (0,0),(-1,-1), [C_WHITE, C_SHADE]),
        ("LINEBELOW",       (0,0),(-1,-1), 0.35, C_RULE),
        ("BOX",             (0,0),(-1,-1), 0.5,  C_RULE),
        ("LEFTPADDING",     (0,0),(-1,-1), 10),
        ("TOPPADDING",      (0,0),(-1,-1), 6),
        ("BOTTOMPADDING",   (0,0),(-1,-1), 6),
    ]))


    story += [
        sp(28),
        hero,
        accent,
        sp(14),
        Paragraph("Design History File  ·  Master Dossier", ST["cover_tag"]),
        sp(22),
        meta,
        sp(18),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# TABLE OF CONTENTS
# ══════════════════════════════════════════════════════════════════════════
def toc_page(story):
    sections = [
        ("1",  "DHF Index & Document Register",      "sec1",  "21 CFR §820.30(j) · ISO 13485 §7.3.10"),
        ("2",  "Design & Development Plan",           "sec2",  "21 CFR §820.30(b) · ISO 13485 §7.3.2"),
        ("3",  "Design Inputs Specification",         "sec3",  "21 CFR §820.30(c) · ISO 13485 §7.3.3"),
        ("4",  "Design Outputs Release Package",      "sec4",  "21 CFR §820.30(d) · ISO 13485 §7.3.4"),
        ("5",  "Design Review Records",               "sec5",  "21 CFR §820.30(e) · ISO 13485 §7.3.5"),
        ("6",  "Design Verification Protocols",       "sec6",  "21 CFR §820.30(f) · ISO 13485 §7.3.6"),
        ("7",  "Design Validation Summary",           "sec7",  "21 CFR §820.30(g) · ISO 13485 §7.3.7"),
        ("8",  "Design Transfer Architecture",        "sec8",  "21 CFR §820.30(h) · ISO 13485 §7.3.8"),
        ("9",  "Design Engineering Change Log",       "sec9",  "21 CFR §820.30(i) · ISO 13485 §7.3.9"),
        ("10", "ISO 14971 Risk Management File",      "sec10", "ISO 14971:2019 · ISO/TR 24971"),
        ("11", "Regulatory Traceability Matrix",      "sec11", "21 CFR §820.30(j) · EU MDR Annex II"),
        ("A",  "Computer System Validation (CSV)",   "secA",  "21 CFR Part 11 · GAMP 5"),
    ]
    story += [
        Bookmark("toc", "Table of Contents"),
        anchor("toc"),
        Paragraph("Table of Contents", ST["h1"]),
        hr(1.5, C_NAVY),
        sp(6),
    ]
    for num, title, key, refs in sections:
        row = Table([
            [
                Paragraph(f'<link href="#{key}"><b>{num}</b></link>', ST["toc"]),
                Paragraph(f'<link href="#{key}">{title}</link>', ST["toc"]),
                Paragraph(refs, ST["toc_sub"]),
            ]
        ], colWidths=[1.0*cm, 8.5*cm, CONTENT_W - 9.5*cm])
        row.setStyle(TableStyle([
            ("VALIGN", (0,0),(-1,-1), "TOP"),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LINEBELOW",     (0,0),(-1,-1), 0.25, C_RULE),
        ]))
        story.append(row)
    story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════════
# SECTION 1 — DHF INDEX
# ══════════════════════════════════════════════════════════════════════════
def sec_dhf_index(story, intake):
    section_header(story, 1, "DHF Index & Document Register", "sec1",
                   "21 CFR §820.30(j) · ISO 13485:2016 §7.3.10")
    story += [
        reg_ref("21 CFR §820.30(j)", "ISO 13485:2016 §7.3.10", "EU MDR Annex II §2"), sp(4),
        Paragraph("1.1 Device Identification", ST["h2"]),
        kv_table([
            ("Device Name",            intake["device_name"]),
            ("Model Number",           intake.get("model_number","[TBD]")),
            ("FDA Classification",     f"Class {intake.get('fda_class','[SME]')}"),
            ("EU MDR Classification",  f"Class {intake.get('eu_mdr_class','[SME]')}"),
            ("Target Markets",         ", ".join(intake.get("target_markets",[]))),
            ("Manufacturer",           intake.get("manufacturer","[SME-INPUT-REQUIRED]")),
            ("Manufacturer Address",   intake.get("manufacturer_address","[SME-INPUT-REQUIRED]")),
            ("Regulatory Contact",     intake.get("regulatory_contact","[SME-INPUT-REQUIRED]")),
            ("DHF Compiled",           TODAY),
        ], lw=5.5*cm),
        sp(10),
        Paragraph("1.2 Master Controlled Document Register", ST["h2"]),
        Paragraph("All documents listed below are draft placeholders generated by AI tooling. "
                  "Each must be reviewed, completed by qualified SMEs, and approved through the "
                  "organisation's QMS before the DHF is considered controlled.", ST["body"]),
        sp(4),
        grid_table(
            ["Doc ID", "Title", "Type", "Rev", "Effective Date", "Owner", "Status"],
            [
                ["DHF-01", "Design & Development Plan",             "Plan",        "A", TODAY, "[PM]",      "Draft"],
                ["DHF-02", "Design Inputs Specification",           "Spec",        "A", TODAY, "[R&D]",     "Draft"],
                ["DHF-03", "Design Outputs Package",                "Spec/DMR",    "A", TODAY, "[R&D]",     "Draft"],
                ["DHF-04", "Design Review Records (G0–G5)",         "Record",      "A", TODAY, "[QA]",      "Draft"],
                ["DHF-05", "Verification Plan & Report",            "V&V Report",  "A", TODAY, "[R&D/QA]",  "Draft"],
                ["DHF-06", "Validation Plan & Report",              "V&V Report",  "A", TODAY, "[Clinical]","Draft"],
                ["DHF-07", "Design Transfer Plan & Checklist",      "Plan",        "A", TODAY, "[Mfg]",     "Draft"],
                ["DHF-08", "Design Change Log",                     "Record",      "A", TODAY, "[R&D]",     "Draft"],
                ["DHF-09", "Risk Management File (ISO 14971)",      "RMF",         "A", TODAY, "[RA/R&D]",  "Draft"],
                ["DHF-10", "Traceability Matrix",                   "Matrix",      "A", TODAY, "[QA]",      "Draft"],
                ["DHF-11", "Clinical Evaluation Report",            "CER/SER",     "A", TODAY, "[Clinical]","Draft"],
                ["DHF-12", "Labelling & IFU",                       "Document",    "A", TODAY, "[RA]",      "Draft"],
                ["DHF-13", "Post-Market Surveillance Plan",         "Plan",        "A", TODAY, "[QA/RA]",   "Draft"],
                ["DHF-14", "CSV Validation Package",                "Val Package", "A", TODAY, "[IT/QA]",   "Draft"],
            ],
            widths=[1.6*cm, 5.8*cm, 2.5*cm, 0.9*cm, 2.5*cm, 1.8*cm, CONTENT_W-15.1*cm],
        ),
        sp(8),
        Paragraph("1.3 Records Retention Policy", ST["h2"]),
        Paragraph("Per 21 CFR §820.180 and ISO 13485:2016 §4.2.5: DHF records must be retained "
                  "for the design lifetime of the device plus applicable statutory retention periods — "
                  "commonly device lifetime + 10 years (FDA); device lifetime + 15 years (EU MDR Article 10(8)), "
                  "with longer periods for implantable devices (minimum 15 years). All original signed "
                  "records must be stored in the organisation's controlled electronic document management "
                  "system (EDMS) with audit trail per 21 CFR Part 11.", ST["body"]),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 2 — DESIGN & DEVELOPMENT PLAN
# ══════════════════════════════════════════════════════════════════════════
def sec_ddplan(story, intake, imgs):
    section_header(story, 2, "Design & Development Plan", "sec2",
                   "21 CFR §820.30(b) · ISO 13485:2016 §7.3.2")
    story += [
        reg_ref("21 CFR §820.30(b)", "ISO 13485:2016 §7.3.2", "EU MDR Annex II §3.1"),
        sp(6),
        Paragraph("2.1 Purpose & Scope", ST["h2"]),
        Paragraph(f"This Design & Development Plan (DDP) documents the activities, responsibilities, "
                  f"interfaces, review gates, and deliverables governing the complete design lifecycle of "
                  f"the <b>{intake['device_name']}</b>. It is a living document and must be updated "
                  f"when design activities deviate materially from those described.", ST["body"]),
        sp(6),
        Paragraph("2.2 Device Description & Intended Use", ST["h2"]),
        kv_table([
            ("Intended Use",                intake["intended_use"]),
            ("Indications for Use",         intake["indications_for_use"]),
            ("Predicate Device / Equivalent", intake.get("predicate_device", "[SME-INPUT-REQUIRED]")),
        ], lw=5.2*cm),
        sp(8),
        Paragraph("2.3 Regulatory Classification Summary", ST["h2"]),
        kv_table([
            ("FDA Classification",     f"Class {intake.get('fda_class','[SME]')} — submission pathway TBD per RA"),
            ("EU MDR Classification",  f"Class {intake.get('eu_mdr_class','[SME]')} — Notified Body required" if intake.get('eu_mdr_class','') in ['IIa','IIb','III'] else f"Class {intake.get('eu_mdr_class','[SME]')}"),
            ("Patient Contacting",     "Yes" if intake.get("patient_contacting") else "No"),
            ("Sterile",                "Yes — sterilization method TBD [SME]" if intake.get("sterile") else "No — non-sterile device"),
            ("Contains Software",      "Yes — IEC 62304 applies" if intake.get("contains_software") else "No software component"),
            ("Implantable",            "Yes — ISO 14630 / ASTM F2847 applies" if intake.get("implantable") else "No"),
            ("Reusable",               "Yes — ISO 17664 reprocessing validation required" if intake.get("reusable") else "No — single use"),
            ("Electromedical",         "Yes — IEC 60601-1 and IEC 60601-1-2 apply" if intake.get("electromedical") else "No"),
        ], lw=5.2*cm),
        sp(10),
        Paragraph("2.4 Design Control V-Model", ST["h2"]),
        KeepTogether([
            Image(imgs["vmodel"], width=CONTENT_W, height=4.4*cm),
            Paragraph("Figure 2.1 — Design Control V-Model linking design phases to corresponding verification "
                      "and validation activities. Dashed horizontal arrows denote bidirectional V&V traceability. "
                      "Source: AI-generated. Verify applicability before regulatory use.", ST["caption"]),
        ]),
        sp(8),
        Paragraph("2.5 Design & Development Phases", ST["h2"]),
        grid_table(
            ["Phase", "Name", "Key Activities", "Key Deliverables", "Gate"],
            [
                ["0", "Concept &\nFeasibility",     "Market analysis, regulatory strategy, predicate analysis, initial risk identification",
                 "Feasibility report, regulatory classification memo, project charter",              "G0"],
                ["1", "Design Inputs",              "User needs → requirements, risk identification (PMCF planning), standards selection",
                 "Design Inputs Spec (DHF-02), Risk Management Plan, standards matrix",             "G1"],
                ["2", "Design &\nPrototyping",      "Detailed design, prototype build, bench testing, formative usability studies",
                 "Engineering drawings, BOM, prototype test report, formative HF study report",     "G2"],
                ["3", "Design\nVerification",       "Execute verification test protocols per DHF-05, document results",
                 "Verification Report, updated RMF",                                                "G3"],
                ["4", "Design\nValidation",         "Simulated/actual-use validation, clinical evaluation, summative usability",
                 "Validation Report (DHF-06), CER, Summative HF Report",                           "G4"],
                ["5", "Design\nTransfer",           "DMR completion, manufacturing process validation (IQ/OQ/PQ), training",
                 "DMR, Process Validation Reports, Transfer Checklist (DHF-07)",                    "G5"],
                ["6", "Post-Market",                "PMS, PSUR/MDR reporting, complaint handling, field safety",
                 "PSUR, PMS report, complaint log",                                                 "PMS"],
            ],
            widths=[1.1*cm, 2.4*cm, 5.8*cm, 5.4*cm, 1.0*cm],
        ),
        sp(8),
        Paragraph("2.6 Project Schedule (Indicative)", ST["h2"]),
        KeepTogether([
            Image(imgs["gantt"], width=CONTENT_W, height=3.5*cm),
            Paragraph("Figure 2.2 — Indicative design schedule. Durations are illustrative; "
                      "Project Lead must confirm and maintain a controlled project plan. "
                      "Source: AI-generated.", ST["caption"]),
        ]),
        sp(8),
        Paragraph("2.7 Roles & Responsibilities", ST["h2"]),
        grid_table(
            ["Role", "Name", "Responsibility"],
            [
                ["Project Lead",         intake.get("design_team_lead","[SME]"),   "Overall DHF ownership, phase gate authority"],
                ["R&D Engineer",         "[SME-INPUT-REQUIRED]",                    "Design execution, drawing control"],
                ["Quality Engineer",     intake.get("quality_lead","[SME]"),        "QMS conformance, document control, audit"],
                ["Regulatory Lead",      intake.get("regulatory_lead","[SME]"),     "Submission strategy, standards interpretation"],
                ["Clinical / HF Lead",   "[SME-INPUT-REQUIRED]",                    "Clinical evaluation, validation, usability"],
                ["Manufacturing Lead",   "[SME-INPUT-REQUIRED]",                    "Design transfer, process validation"],
                ["Independent Reviewer", "[SME-INPUT-REQUIRED]",                    "Per 21 CFR §820.30(e) — must be independent of design team"],
            ],
            widths=[3.5*cm, 4.5*cm, CONTENT_W-8.0*cm],
        ),
        sp(8),
        Paragraph("2.8 Design Review Gates", ST["h2"]),
        grid_table(
            ["Gate", "Review Name",            "Planned Date",  "Mandatory Attendees",                              "Exit Criteria"],
            [
                ["G0", "Concept Review",       "[DATE]",         "PM, RA, R&D, Finance",                             "Feasibility approved, project funded"],
                ["G1", "Inputs Frozen",        "[DATE]",         "All functions",                                    "DI document baselined, signed off"],
                ["G2", "Design Complete",      "[DATE]",         "All functions + Independent Reviewer",             "Prototype tested, HF formative complete"],
                ["G3", "V&V Complete",         "[DATE]",         "QA, RA, Clinical, Independent Reviewer",           "All acceptance criteria met, RMF updated"],
                ["G4", "Transfer Approved",    "[DATE]",         "QA, Manufacturing, QC, RA",                        "DMR complete, process validation done"],
                ["G5", "Launch Release",       "[DATE]",         "Management, QA, RA",                               "Regulatory approval/clearance received"],
            ],
            widths=[1.0*cm, 3.2*cm, 2.2*cm, 5.5*cm, CONTENT_W-11.9*cm],
        ),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 3 — DESIGN INPUTS
# ══════════════════════════════════════════════════════════════════════════
def sec_design_inputs(story, intake, imgs):
    section_header(story, 3, "Design Inputs Specification", "sec3",
                   "21 CFR §820.30(c) · ISO 13485:2016 §7.3.3")
    story += [
        reg_ref("21 CFR §820.30(c)", "ISO 13485:2016 §7.3.3", "EU MDR Annex I (GSPR)"),
        sp(4),
        Paragraph(f"Design Inputs define the physical, performance, safety, and regulatory requirements "
                  f"the <b>{intake['device_name']}</b> must satisfy. All inputs must be complete, "
                  f"unambiguous, and verifiable before design output generation.", ST["body"]),
        sp(6),
        Paragraph("3.1 Functional Architecture", ST["h2"]),
        KeepTogether([
            Image(imgs["block"], width=CONTENT_W, height=3.0*cm),
            Paragraph("Figure 3.1 — Functional Block Architecture. SME to replace with actual subsystem "
                      "boundary diagram. Source: AI-generated stub.", ST["caption"]),
        ]),
        sp(6),
        Paragraph("3.2 User Needs", ST["h2"]),
        grid_table(
            ["UN-ID", "User Need Statement", "User / Stakeholder", "Source / Evidence"],
            [
                ["UN-001", "[SME-INPUT-REQUIRED: primary clinical function]",      "Clinician / Patient",   "VOC, literature review"],
                ["UN-002", "[SME-INPUT-REQUIRED: usability / ergonomics]",         "Nurse / Technician",    "Formative usability study"],
                ["UN-003", "[SME-INPUT-REQUIRED: connectivity / data management]", "IT / Clinical Admin",   "Market research"],
                ["UN-004", "[SME-INPUT-REQUIRED: maintenance / cleaning]",         "Biomedical Engineer",   "Service requirements"],
            ],
            widths=[1.6*cm, 6.5*cm, 3.0*cm, CONTENT_W-11.1*cm],
        ),
        sp(6),
        Paragraph("3.3 Functional & Performance Requirements", ST["h2"]),
        grid_table(
            ["DI-ID", "Requirement Statement", "Source", "Acceptance Criterion", "Verification Method"],
            [
                ["DI-F-001", "[SME: primary performance parameter]",        "UN-001", "[Quantified limit]",  "[Test method]"],
                ["DI-F-002", "[SME: accuracy / precision]",                 "UN-001", "[±X% or ±Y units]",  "Bench test"],
                ["DI-F-003", "[SME: response time]",                        "UN-001", "&lt; X seconds",         "Timing test"],
                ["DI-F-004", "[SME: alarm / alert thresholds]",             "UN-002", "[Defined range]",     "Functional test"],
            ],
            widths=[1.8*cm, 5.5*cm, 1.6*cm, 3.5*cm, CONTENT_W-12.4*cm],
        ),
        sp(4),
        sme("Complete with quantified, verifiable acceptance criteria for each requirement. "
            "Every DI-ID must link to at least one verification test in Section 6."),
        sp(8),
        Paragraph("3.4 Mechanical / Physical Requirements", ST["h3"]),
        Paragraph("[SME-INPUT-REQUIRED: envelope dimensions, weight limits, material specifications, "
                  "mechanical load ratings, drop/shock/vibration per IEC 60068, IP rating if applicable.]", ST["body"]),
        sp(4),
    ]

    if intake.get("electromedical"):
        story += [
            Paragraph("3.5 Electrical Safety & EMC Requirements", ST["h3"]),
            grid_table(
                ["Req ID", "Requirement", "Standard", "Acceptance Criterion"],
                [
                    ["DI-E-001", "Basic safety & essential performance", "IEC 60601-1:2005+AMD2:2020", "[SME: defined limits]"],
                    ["DI-E-002", "EMC — emissions & immunity",          "IEC 60601-1-2:2014+AMD1:2020","[SME: environment class]"],
                    ["DI-E-003", "Alarm systems",                       "IEC 60601-1-8:2006",           "[SME: alarm categories]"],
                    ["DI-E-004", "Applied parts isolation",             "IEC 60601-1 Table 6",          "[SME: isolation class]"],
                ],
                widths=[2.0*cm, 5.5*cm, 4.5*cm, CONTENT_W-12.0*cm],
            ),
            sp(6),
        ]

    if intake.get("patient_contacting"):
        story += [
            Paragraph("3.6 Biocompatibility Requirements", ST["h3"]),
            Paragraph(f"ISO 10993-1:2018 biological evaluation required. "
                      f"Contact category: {'<b>Implant</b>' if intake.get('implantable') else '<b>Surface contact</b>'}. "
                      f"Contact duration: {'<b>Permanent (>30 days)</b>' if intake.get('implantable') else '<b>Limited</b>'}. "
                      "A biological evaluation plan (BEP) must be prepared by a toxicologist. "
                      "[SME-INPUT-REQUIRED: material characterisation data, extraction studies]", ST["body"]),
            sp(4),
        ]

    if intake.get("sterile"):
        story += [
            Paragraph("3.7 Sterility Requirements", ST["h3"]),
            Paragraph("Sterility Assurance Level (SAL) of 10<super>-6</super> required. "
                      "Applicable standard: [SME: ISO 11135 / ISO 11137 / ISO 17665 — EtO / "
                      "Gamma / Steam]. Bioburden testing per ISO 11737-1 required. "
                      "[SME-INPUT-REQUIRED]", ST["body"]),
            sp(4),
        ]

    if intake.get("contains_software"):
        story += [
            Paragraph("3.8 Software Requirements (IEC 62304)", ST["h3"]),
            KeepTogether([
                Image(imgs["sw_class"], width=CONTENT_W*0.78, height=4.0*cm),
                Paragraph("Figure 3.2 — IEC 62304:2006+AMD1:2015 Software Safety Classification. "
                          "Source: AI-generated.", ST["caption"]),
            ]),
            Paragraph("Software safety class must be determined per the decision tree above and "
                      "documented in the Software Development Plan (SDP). "
                      "Class B requires full SOUP management; Class C additionally requires "
                      "architectural design verification. [SME-INPUT-REQUIRED]", ST["body"]),
            sp(4),
            Paragraph("3.9 Cybersecurity Requirements", ST["h3"]),
            Paragraph("Per FDA premarket cybersecurity guidance (Sep 2023) and IEC 81001-5-1:2021. "
                      "A Security Risk Management file must be maintained alongside the ISO 14971 RMF. "
                      "SBOM (Software Bill of Materials) required for FDA submissions post-Oct 2023. "
                      "[SME-INPUT-REQUIRED]", ST["body"]),
            sp(4),
        ]

    if intake.get("reusable"):
        story += [
            Paragraph("3.10 Reprocessing / Cleaning Requirements", ST["h3"]),
            Paragraph("ISO 17664-1:2021 reprocessing validation required. Must define validated "
                      "cleaning, disinfection, and/or sterilization instructions in IFU. "
                      "[SME-INPUT-REQUIRED: reprocessing study report reference]", ST["body"]),
            sp(4),
        ]

    story += [
        Paragraph("3.11 Usability / Human Factors Requirements", ST["h3"]),
        Paragraph("Per IEC 62366-1:2015+AMD1:2020 and FDA HF guidance (2016). "
                  "Intended users, use environment, and critical tasks must be formally defined. "
                  "Formative and summative usability evaluations required. "
                  "[SME-INPUT-REQUIRED]", ST["body"]),
        sp(4),
        Paragraph("3.12 Shelf Life & Packaging Requirements", ST["h3"]),
        Paragraph("Accelerated aging per ASTM F1980. Real-time aging study plan required. "
                  "Packaging validation per ASTM F2097 / ISO 11607. "
                  "[SME-INPUT-REQUIRED: design life claim]", ST["body"]),
        sp(4),
        Paragraph("3.13 Labelling & IFU Requirements", ST["h3"]),
        Paragraph("Per 21 CFR §801 (FDA) and EU MDR Annex I §23 (EU). "
                  "Symbols per ISO 15223-1. IFU readability / comprehension testing required for EU. "
                  "UDI per 21 CFR §830 (FDA) and EU MDR Article 27. "
                  "[SME-INPUT-REQUIRED]", ST["body"]),
        sp(4),
        Paragraph("3.14 Risk-Derived Design Inputs", ST["h3"]),
        Paragraph("Risk control measures identified in the ISO 14971 RMF (Section 10) that become "
                  "design inputs must be captured here and cross-referenced to the risk register. "
                  "[SME-INPUT-REQUIRED: link from RMF risk control measures to DI-IDs]", ST["body"]),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 4 — DESIGN OUTPUTS
# ══════════════════════════════════════════════════════════════════════════
def sec_design_outputs(story, intake):
    section_header(story, 4, "Design Outputs Release Package", "sec4",
                   "21 CFR §820.30(d) · ISO 13485:2016 §7.3.4")
    story += [
        reg_ref("21 CFR §820.30(d)", "ISO 13485:2016 §7.3.4", "EU MDR Annex II §3.1"),
        sp(4),
        Paragraph("Design outputs are the results of each design phase that form the basis for the "
                  "Device Master Record (DMR). Essential design outputs must be identified and "
                  "controlled under the QMS.", ST["body"]),
        sp(6),
        Paragraph("4.1 Device Master Record (DMR) Index", ST["h2"]),
        grid_table(
            ["DMR-ID", "Document Title", "Document Type", "Rev", "QMS Reference"],
            [
                ["DMR-DWG", "Engineering Drawings (assembly + detail)", "Drawing Set", "A", "[Doc number]"],
                ["DMR-BOM", "Bill of Materials",                         "BOM",         "A", "[Doc number]"],
                ["DMR-SPC", "Material & Component Specifications",       "Spec",        "A", "[Doc number]"],
                ["DMR-MFG", "Manufacturing / Assembly Procedures",       "SOP",         "A", "[Doc number]"],
                ["DMR-QCP", "Quality Control Plans & Acceptance Criteria","QCP",        "A", "[Doc number]"],
                ["DMR-LBL", "Labelling & IFU",                           "Document",    "A", "[Doc number]"],
                ["DMR-PKG", "Packaging Specification",                   "Spec",        "A", "[Doc number]"],
                ["DMR-SFW", "Software Release Package (if applicable)",  "SW Package",  "A", "[Doc number]"],
            ],
            widths=[2.0*cm, 6.0*cm, 2.8*cm, 1.0*cm, CONTENT_W-11.8*cm],
        ),
        sp(6),
        Paragraph("4.2 Essential Design Outputs (21 CFR §820.30(d))", ST["h2"]),
        Paragraph("The following design outputs are identified as essential to proper device functioning. "
                  "Each must reference the corresponding design input it satisfies.", ST["body"]),
        sp(4),
        grid_table(
            ["DO-ID", "Design Output Description", "DI Reference", "Output Document", "Essential?"],
            [
                ["DO-001", "[SME: primary output/assembly]",           "DI-F-001",   "DMR-DWG-001", "Yes"],
                ["DO-002", "[SME: firmware/software binary]",          "DI-F-003",   "DMR-SFW-001", "Yes"],
                ["DO-003", "[SME: labelling/IFU]",                     "DI-L-001",   "DMR-LBL-001", "Yes"],
                ["DO-004", "[SME: packaging configuration]",           "DI-P-001",   "DMR-PKG-001", "Yes"],
            ],
            widths=[1.8*cm, 5.5*cm, 2.5*cm, 3.5*cm, CONTENT_W-13.3*cm],
        ),
        sp(4),
        sme("Complete DO list with every design output referencing a specific DI-ID. "
            "Flag each as 'Essential' per 21 CFR §820.30(d) criteria."),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 5 — DESIGN REVIEW
# ══════════════════════════════════════════════════════════════════════════
def sec_design_review(story, intake):
    section_header(story, 5, "Design Review Records", "sec5",
                   "21 CFR §820.30(e) · ISO 13485:2016 §7.3.5")
    story += [
        reg_ref("21 CFR §820.30(e)", "ISO 13485:2016 §7.3.5"),
        sp(4),
        Paragraph("Each formal gate review (G0–G5) must be documented using the template below. "
                  "At least one attendee must be independent of the design team. "
                  "All open action items must be resolved before the next gate is approved.", ST["body"]),
        sp(6),
        Paragraph("5.1 Review Record Template", ST["h2"]),
        kv_table([
            ("Review Gate",          "[G0 / G1 / G2 / G3 / G4 / G5]"),
            ("Review Date",          "[DATE]"),
            ("Chair",                "[Name, Title]"),
            ("Independent Reviewer", "[Name, Title] — confirm independence declaration on file"),
            ("Attendees",            "[Printed names and functions]"),
            ("Documents Reviewed",   "[List DHF-IDs reviewed]"),
            ("Disposition",          "[ ] Pass   [ ] Conditional Pass (AIL required)   [ ] Fail"),
            ("Notes / Summary",      "[Key discussion points and decision rationale]"),
        ], lw=5.2*cm),
        sp(6),
        Paragraph("5.2 Action Item Log (AIL)", ST["h2"]),
        grid_table(
            ["AI-ID", "Action Description",      "Owner",  "Due Date", "Priority", "Status"],
            [
                ["AI-001", "[SME-INPUT-REQUIRED]", "[SME]", "[DATE]",   "HIGH",     "OPEN"],
            ],
            widths=[1.5*cm, 7.0*cm, 2.0*cm, 2.0*cm, 1.8*cm, CONTENT_W-14.3*cm],
        ),
        sp(4),
        sme("Each design review must have a signed record stored in the DHF. "
            "Conditional passes require all action items closed before the next gate."),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 6 — DESIGN VERIFICATION
# ══════════════════════════════════════════════════════════════════════════
def sec_verification(story, intake):
    section_header(story, 6, "Design Verification Protocols", "sec6",
                   "21 CFR §820.30(f) · ISO 13485:2016 §7.3.6")
    story += [
        reg_ref("21 CFR §820.30(f)", "ISO 13485:2016 §7.3.6"),
        sp(4),
        Paragraph("Design verification confirms that each design output meets its corresponding design "
                  "input requirement. Every DI-ID must map to at least one verification test. "
                  "Verification must be performed under defined and documented conditions.", ST["body"]),
        sp(6),
        Paragraph("6.1 Verification Test Matrix", ST["h2"]),
        grid_table(
            ["DV-ID", "DI Reference", "Test Description", "Method / Standard", "Acceptance Criterion", "Sample Size", "Result", "Pass/Fail"],
            [
                ["DV-001", "DI-F-001", "[SME: primary function test]",     "[Standard]", "[Criterion]", "n=[SME]", "[RESULT]", "[PASS/FAIL]"],
                ["DV-002", "DI-F-002", "[SME: accuracy test]",             "[Standard]", "±X%",         "n=[SME]", "[RESULT]", "[PASS/FAIL]"],
                ["DV-003", "DI-F-003", "[SME: response time test]",        "[Standard]", "&lt;X sec",       "n=[SME]", "[RESULT]", "[PASS/FAIL]"],
                ["DV-004", "DI-E-001", "[SME: electrical safety — HiPot]", "IEC 60601-1","Pass criteria","n=5",     "[RESULT]", "[PASS/FAIL]"],
                ["DV-005", "DI-E-002", "[SME: EMC emissions]",             "IEC 60601-1-2","Pass",        "n=3",     "[RESULT]", "[PASS/FAIL]"],
            ],
            widths=[1.5*cm, 2.0*cm, 3.5*cm, 2.5*cm, 2.8*cm, 1.5*cm, 1.5*cm, CONTENT_W-15.3*cm],
        ),
        sp(6),
        Paragraph("6.2 Statistical Considerations", ST["h2"]),
        Paragraph("Sample sizes must be statistically justified. Recommended approach: reliability "
                  "R ≥ 95% at C ≥ 95% confidence unless a higher standard applies. "
                  "Acceptance sampling per ANSI/ASQ Z1.4 or equivalent. "
                  "[SME-INPUT-REQUIRED: statistical justification for each test]", ST["body"]),
        sp(4),
        Paragraph("6.3 Environmental & Conditioning Requirements", ST["h2"]),
        grid_table(
            ["Test Condition", "Standard", "Parameters"],
            [
                ["Temperature cycling",    "IEC 60068-2-14",  "[SME: temperature range and cycles]"],
                ["Humidity",               "IEC 60068-2-78",  "[SME: RH % and duration]"],
                ["Vibration",              "IEC 60068-2-6",   "[SME: frequency and amplitude]"],
                ["Drop / Mechanical shock","IEC 60068-2-27",  "[SME: drop height and surface]"],
                ["IP rating (ingress)",    "IEC 60529",       "[SME: IP class required]"],
            ],
            widths=[3.5*cm, 3.5*cm, CONTENT_W-7.0*cm],
        ),
        sp(4),
        Paragraph("6.4 Verification Report Summary", ST["h2"]),
        kv_table([
            ("Report Reference",    "[DHF-05-VER-001]"),
            ("Test Dates",          "[START] – [END]"),
            ("Test Location",       "[SME: lab name, accreditation #]"),
            ("Overall Disposition", "[ ] All tests PASSED   [ ] Open deviations — see NCR log"),
        ], lw=5.2*cm),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 7 — DESIGN VALIDATION
# ══════════════════════════════════════════════════════════════════════════
def sec_validation(story, intake):
    section_header(story, 7, "Design Validation Summary", "sec7",
                   "21 CFR §820.30(g) · ISO 13485:2016 §7.3.7")
    story += [
        reg_ref("21 CFR §820.30(g)", "ISO 13485:2016 §7.3.7", "EU MDR Annex XIV", "IEC 62366-1"),
        sp(4),
        Paragraph("Design validation demonstrates the device meets user needs and intended uses under "
                  "actual or simulated conditions of use. Validation must include production or "
                  "production-equivalent devices. Initial production units must be used. ", ST["body"]),
        sp(6),
        Paragraph("7.1 Validation Plan Summary", ST["h2"]),
        kv_table([
            ("Validation Plan Reference", "[DHF-06-VAL-PLAN-001]"),
            ("Validation Protocol",       "[Protocol ID and version]"),
            ("Validation Sites",          "[SME: clinical site(s) or simulated-use lab]"),
            ("Intended Users",            "[SME: user group and training level]"),
            ("Use Environment",           "[SME: hospital ward / ICU / home care]"),
            ("Device Configuration",      "Production or production-equivalent units"),
        ], lw=5.2*cm),
        sp(6),
        Paragraph("7.2 Human Factors / Usability Engineering (IEC 62366-1)", ST["h2"]),
        grid_table(
            ["HF Activity", "Description", "Status", "Report Reference"],
            [
                ["Intended Use Definition",       "Users, tasks, environment, use error risks",  "[SME]", "[Doc ref]"],
                ["Formative Evaluation(s)",        "Iterative design reviews with representative users", "[SME]", "[Doc ref]"],
                ["Summative Evaluation",           "Final simulated-use study with production device", "[SME]", "[Doc ref]"],
                ["Critical Task Analysis",         "Identification and validation of critical tasks",  "[SME]", "[Doc ref]"],
            ],
            widths=[3.8*cm, 5.5*cm, 1.5*cm, CONTENT_W-10.8*cm],
        ),
        sp(6),
        Paragraph("7.3 Clinical Evaluation (EU MDR Annex XIV)", ST["h2"]),
        Paragraph("A Clinical Evaluation Report (CER) must be maintained per EU MDR Annex XIV and "
                  "MEDDEV 2.7/1 rev. 4 (or MDR-compliant equivalent). The CER shall be updated "
                  "at minimum annually from post-market clinical follow-up (PMCF) data. "
                  "[SME-INPUT-REQUIRED: CER reference]", ST["body"]),
        sp(4),
        Paragraph("7.4 Software Validation (if applicable)", ST["h2"]),
        Paragraph("Per IEC 62304 and FDA Software Validation guidance. System-level validation "
                  "must cover all defined software safety functions. Regression testing plan required "
                  "for each software release. [SME-INPUT-REQUIRED]", ST["body"])
        if intake.get("contains_software") else Paragraph("Not applicable — no software component.", ST["body"]),
        sp(4),
        Paragraph("7.5 Validation Report Summary", ST["h2"]),
        kv_table([
            ("Report Reference",    "[DHF-06-VAL-RPT-001]"),
            ("Validation Dates",    "[START] – [END]"),
            ("Overall Disposition", "[ ] All objectives met   [ ] Open deviations — see deviation log"),
        ], lw=5.2*cm),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 8 — DESIGN TRANSFER
# ══════════════════════════════════════════════════════════════════════════
def sec_transfer(story, intake):
    section_header(story, 8, "Design Transfer Architecture", "sec8",
                   "21 CFR §820.30(h) · ISO 13485:2016 §7.3.8")
    story += [
        reg_ref("21 CFR §820.30(h)", "ISO 13485:2016 §7.3.8"),
        sp(4),
        Paragraph("Design transfer ensures that all design outputs are correctly translated into "
                  "production specifications and that the manufacturing process can reproducibly "
                  "produce a device that meets specifications.", ST["body"]),
        sp(6),
        Paragraph("8.1 Transfer Readiness Checklist", ST["h2"]),
        grid_table(
            ["Item", "Description", "Status", "Owner", "Evidence"],
            [
                ["T-01", "DMR complete and approved",                           "[ ]", "[SME]", "[Doc ref]"],
                ["T-02", "All drawings released in QMS",                        "[ ]", "[SME]", "[Doc ref]"],
                ["T-03", "BOM approved with supplier qualifications",           "[ ]", "[SME]", "[Doc ref]"],
                ["T-04", "Manufacturing procedures written and approved",        "[ ]", "[SME]", "[Doc ref]"],
                ["T-05", "Operator training completed and documented",           "[ ]", "[SME]", "[Doc ref]"],
                ["T-06", "First Article Inspection (FAI) completed",            "[ ]", "[SME]", "[Doc ref]"],
                ["T-07", "Process Validation (IQ/OQ/PQ) completed",            "[ ]", "[SME]", "[Doc ref]"],
                ["T-08", "Quality Control plan implemented",                    "[ ]", "[SME]", "[Doc ref]"],
                ["T-09", "Labelling print verification completed",              "[ ]", "[SME]", "[Doc ref]"],
                ["T-10", "UDI implementation verified",                         "[ ]", "[SME]", "[Doc ref]"],
                ["T-11", "Post-market surveillance plan activated",             "[ ]", "[SME]", "[Doc ref]"],
            ],
            widths=[1.2*cm, 6.2*cm, 1.2*cm, 1.8*cm, CONTENT_W-10.4*cm],
        ),
        sp(6),
        Paragraph("8.2 Process Validation (IQ / OQ / PQ)", ST["h2"]),
        grid_table(
            ["Process", "Qualification Phase", "Standard / Method", "Status", "Report Reference"],
            [
                ["[Critical process 1]", "IQ",  "[SME: standard]", "[SME]", "[Doc ref]"],
                ["[Critical process 1]", "OQ",  "[SME: standard]", "[SME]", "[Doc ref]"],
                ["[Critical process 1]", "PQ",  "[SME: standard]", "[SME]", "[Doc ref]"],
                ["[Critical process 2]", "IQ/OQ/PQ", "[SME]",     "[SME]", "[Doc ref]"],
            ],
            widths=[3.5*cm, 2.5*cm, 3.5*cm, 1.5*cm, CONTENT_W-11.0*cm],
        ),
        sp(4),
        sme("List all special processes (welding, sterilization, coating, injection moulding, etc.) "
            "that require process validation. Each must have IQ/OQ/PQ qualification."),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 9 — CHANGE LOG
# ══════════════════════════════════════════════════════════════════════════
def sec_change_log(story, intake):
    section_header(story, 9, "Design Engineering Change Log", "sec9",
                   "21 CFR §820.30(i) · ISO 13485:2016 §7.3.9")
    story += [
        reg_ref("21 CFR §820.30(i)", "ISO 13485:2016 §7.3.9"),
        sp(4),
        Paragraph("All design changes after design freeze must be formally documented, reviewed, "
                  "and approved. The impact on verification, validation, regulatory status, "
                  "and risk management must be assessed for each change.", ST["body"]),
        sp(6),
        Paragraph("9.1 Design Change Register", ST["h2"]),
        grid_table(
            ["DCR-ID", "Description", "Initiator", "Date", "Change Category",
             "V&V Impact", "Regulatory Impact", "Risk Impact", "Affected Docs", "Status"],
            [
                ["DCR-001","Initial design baseline established","PM",TODAY,
                 "Baseline","N/A","N/A","N/A","All DHF","Closed"],
                ["DCR-002","[SME-INPUT-REQUIRED]","[SME]","[DATE]",
                 "[SME]","[SME]","[SME]","[SME]","[SME]","Open"],
            ],
            widths=[1.5*cm, 3.0*cm, 1.5*cm, 1.8*cm, 2.0*cm,
                    1.6*cm, 2.0*cm, 1.5*cm, 1.8*cm, CONTENT_W-16.7*cm],
            compact=True,
        ),
        sp(6),
        Paragraph("9.2 Change Impact Assessment Criteria", ST["h2"]),
        grid_table(
            ["Change Category", "Description", "V&V Re-work Required?"],
            [
                ["Major",    "Affects form, fit, function, or intended use",             "Yes — full re-verification"],
                ["Minor",    "Does not affect FFE or clinical performance",              "Partial — as justified"],
                ["Cosmetic", "Aesthetic only; no functional or dimensional change",     "No — documented justification"],
                ["Baseline", "Initial release — no prior version",                      "N/A"],
            ],
            widths=[2.5*cm, 7.5*cm, CONTENT_W-10.0*cm],
        ),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 10 — RISK MANAGEMENT FILE
# ══════════════════════════════════════════════════════════════════════════
def sec_rmf(story, intake, imgs):
    section_header(story, 10, "ISO 14971 Risk Management File", "sec10",
                   "ISO 14971:2019 · ISO/TR 24971:2020 · EN ISO 14971/A11:2021")
    story += [
        reg_ref("ISO 14971:2019", "ISO/TR 24971:2020", "EN ISO 14971:2019/A11:2021 (EU)",
                "21 CFR §820.30(g)", "EU MDR Annex I §3"),
        sp(4),
        Paragraph("10.1 Risk Management Process Overview", ST["h2"]),
        KeepTogether([
            Image(imgs["iso14971"], width=CONTENT_W, height=3.2*cm),
            Paragraph("Figure 10.1 — ISO 14971:2019 Risk Management Process. "
                      "Post-market surveillance feeds back into the risk management system throughout "
                      "the device lifetime. Source: AI-generated.", ST["caption"]),
        ]),
        sp(6),
        Paragraph("10.2 Risk Acceptability Matrix", ST["h2"]),
        KeepTogether([
            Image(imgs["risk_matrix"], width=CONTENT_W*0.68, height=4.8*cm),
            Paragraph("Figure 10.2 — 5×5 Risk Acceptability Matrix. Severity and probability "
                      "scale anchors must be formally approved by the risk management team. "
                      "[SME-CONFIRM: criteria appropriate to clinical context]. "
                      "Source: AI-generated.", ST["caption"]),
        ]),
        sp(6),
        Paragraph("10.3 Severity Scale (ISO 14971 Annex C)", ST["h2"]),
        grid_table(
            ["Level", "Term", "Definition"],
            [
                ["5", "Catastrophic", "Results in patient death"],
                ["4", "Critical",     "Results in permanent impairment or life-threatening injury"],
                ["3", "Serious",      "Results in injury or impairment requiring professional medical intervention"],
                ["2", "Minor",        "Results in temporary injury or impairment not requiring professional medical intervention"],
                ["1", "Negligible",   "Inconvenience or temporary discomfort"],
            ],
            widths=[1.2*cm, 2.8*cm, CONTENT_W-4.0*cm],
        ),
        sp(6),
        Paragraph("10.4 Probability of Occurrence Scale", ST["h2"]),
        grid_table(
            ["Level", "Term", "Qualitative Description", "Approx. Frequency per Use"],
            [
                ["5","Frequent",   "Likely to occur often in clinical use",                "> 10<super>-3</super>"],
                ["4","Probable",   "Likely to occur several times during device lifetime",  "10<super>-3</super> – 10<super>-4</super>"],
                ["3","Occasional", "Likely to occur sometime during device lifetime",       "10<super>-4</super> – 10<super>-5</super>"],
                ["2","Remote",     "Unlikely but possible to occur during device lifetime", "10<super>-5</super> – 10<super>-6</super>"],
                ["1","Improbable", "So unlikely it can be assumed not to occur",            "< 10<super>-6</super>"],
            ],
            widths=[1.2*cm, 2.2*cm, 5.5*cm, CONTENT_W-8.9*cm],
        ),
        sp(6),
        Paragraph("10.5 Hazard Identification Categories (ISO 14971 §5.4 + Annex C)", ST["h2"]),
        grid_table(
            ["Hazard Category",    "Examples for This Device Type"],
            [
                ["Energy",               "Mechanical (sharp edges, pressure), electrical, thermal, radiation"],
                ["Biological / Chemical","Biocompatibility, toxicity, microbial contamination, allergens"],
                ["Operational",          "Unintended use, malfunction, software error, alarm failure"],
                ["Information",          "Labelling errors, IFU deficiency, inaccurate measurement output"],
                ["Environmental",        "Electromagnetic interference, temperature/humidity extremes"],
                ["Human Factors",        "Use error, misuse, confusion with similar devices"],
            ],
            widths=[4.2*cm, CONTENT_W-4.2*cm],
        ),
        sp(6),
        Paragraph("10.6 FMEA / Hazard Register Overview", ST["h2"]),
        KeepTogether([
            Image(imgs["fmea_rpn"], width=CONTENT_W, height=3.5*cm),
            Paragraph("Figure 10.3 — Indicative RPN overview by hazard category. "
                      "Values are illustrative stubs only — SME must populate actual FMEA workbooks. "
                      "Source: AI-generated.", ST["caption"]),
        ]),
        sp(6),
        Paragraph("10.7 Risk Control Hierarchy (ISO 14971 §6.2)", ST["h2"]),
        grid_table(
            ["Priority", "Control Type",             "Description", "Example"],
            [
                ["1 (Preferred)", "Inherent safety",         "Eliminate hazard through design",             "Use rounded edges; avoid toxic materials"],
                ["2",             "Protective measures",     "Guards, alarms, failsafe mechanisms",         "Fuse, overcurrent protection, software limits"],
                ["3 (Last resort)","Information for safety", "IFU warnings, labelling, training materials", "Contraindication in IFU; operator training requirement"],
            ],
            widths=[2.0*cm, 3.0*cm, 5.0*cm, CONTENT_W-10.0*cm],
        ),
        sp(6),
        Paragraph("10.8 FMEA Documents on File", ST["h2"]),
        grid_table(
            ["FMEA Type", "Document Reference", "Scope",          "Owner",  "Status"],
            [
                ["dFMEA (Design)", "[Doc-FMEA-D-001]", "Design failure modes",          "[R&D]",    "Draft"],
                ["pFMEA (Process)", "[Doc-FMEA-P-001]","Manufacturing process failures", "[Mfg/QA]", "Draft"],
                ["uFMEA (Use)",    "[Doc-FMEA-U-001]", "Use error failure modes (IEC 62366-1)", "[HF Lead]","Draft"],
            ],
            widths=[2.5*cm, 3.5*cm, 5.0*cm, 2.0*cm, CONTENT_W-13.0*cm],
        ),
        sp(6),
        Paragraph("10.9 Overall Residual Risk Evaluation", ST["h2"]),
        Paragraph("Per ISO 14971 §8 and EU MDR Annex I §1 and §8: a formal benefit-risk analysis "
                  "must demonstrate that the overall residual risk is acceptable in light of the "
                  "clinical benefits. This analysis must be documented and signed off by the risk "
                  "management team prior to design transfer.", ST["body"]),
        sp(4),
        sme("Benefit-risk analysis per EU MDR Annex I §1 and §8 required here. "
            "Must cite clinical evidence from CER."),
        sp(6),
        Paragraph("10.10 Post-Market Risk Update", ST["h2"]),
        Paragraph("The Risk Management File must be updated at defined intervals (at minimum annually) "
                  "using post-market surveillance data, vigilance reports, complaint data, "
                  "literature reviews, and PMCF results. [SME-INPUT-REQUIRED]", ST["body"]),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# SECTION 11 — TRACEABILITY MATRIX
# ══════════════════════════════════════════════════════════════════════════
def sec_traceability(story, intake, imgs):
    section_header(story, 11, "Regulatory Traceability Matrix", "sec11",
                   "21 CFR §820.30(j) · EU MDR Annex II")
    story += [
        reg_ref("21 CFR §820.30(j)", "ISO 13485:2016 §7.3.10", "EU MDR Annex II"),
        sp(4),
        Paragraph("The traceability matrix links every user need through design inputs, design outputs, "
                  "verification, validation, and risk controls. All cells must be complete, verified, "
                  "and cross-referenced before DHF closure.", ST["body"]),
        sp(6),
        Paragraph("11.1 Traceability Chain Diagram", ST["h2"]),
        KeepTogether([
            Image(imgs["traceability"], width=CONTENT_W, height=2.4*cm),
            Paragraph("Figure 11.1 — DHF Traceability Chain. Each node must be traceable "
                      "bidirectionally to the adjacent nodes. Source: AI-generated.", ST["caption"]),
        ]),
        sp(6),
        Paragraph("11.2 Master Traceability Matrix", ST["h2"]),
        grid_table(
            ["UN-ID", "User Need", "DI-ID", "Design Input", "DO-ID", "Design Output",
             "DV-ID", "Verification", "DVA-ID", "Validation", "Risk-ID", "Risk Control"],
            [
                ["UN-001","[SME]","DI-F-001","[SME]","DO-001","[SME]",
                 "DV-001","[SME]","DVA-001","[SME]","R-001","[SME]"],
                ["UN-002","[SME]","DI-F-002","[SME]","DO-002","[SME]",
                 "DV-002","[SME]","DVA-001","[SME]","R-002","[SME]"],
                ["UN-003","[SME]","DI-F-003","[SME]","DO-003","[SME]",
                 "DV-003","[SME]","DVA-002","[SME]","R-003","[SME]"],
            ],
            widths=None,
        ),
        sp(4),
        sme("Every row must be fully populated before regulatory submission. "
            "Highlight gaps in red during DHF review."),
        sp(8),
        Paragraph("11.3 Regulatory Standards Applicability Matrix", ST["h2"]),
        grid_table(
            ["Standard", "Scope", "Applicable?", "Compliance Evidence"],
            [
                ["IEC 60601-1:2005+AMD2",         "Basic electrical safety",          "Yes" if intake.get("electromedical") else "No",   "[Test report ref]"],
                ["IEC 60601-1-2:2014+AMD1",       "EMC",                              "Yes" if intake.get("electromedical") else "No",   "[EMC test report]"],
                ["ISO 10993-1:2018",               "Biocompatibility",                 "Yes" if intake.get("patient_contacting") else "No","[BEP/BER ref]"],
                ["ISO 14971:2019",                 "Risk management",                  "Yes",                                             "[RMF ref]"],
                ["IEC 62304:2006+AMD1",            "Software lifecycle",               "Yes" if intake.get("contains_software") else "No","[SDP ref]"],
                ["IEC 62366-1:2015+AMD1",          "Usability engineering",            "Yes",                                             "[HF report ref]"],
                ["ISO 13485:2016",                 "QMS",                              "Yes",                                             "[QMS cert]"],
                ["ISO 11135 / 11137 / 17665",      "Sterilization (as applicable)",   "Yes" if intake.get("sterile") else "No",          "[Sterility report]"],
                ["ISO 17664-1:2021",               "Reprocessing instructions",        "Yes" if intake.get("reusable") else "No",         "[Reprocessing validation]"],
                ["IEC 81001-5-1:2021",             "Cybersecurity",                   "Yes" if intake.get("contains_software") else "No","[SBOM / threat model]"],
            ],
            widths=[4.5*cm, 3.5*cm, 2.2*cm, CONTENT_W-10.2*cm],
        ),
        sp(6),
        Paragraph("11.4 Target Market Regulatory Map", ST["h2"]),
        KeepTogether([
            Image(imgs["reg_map"], width=CONTENT_W*0.60, height=4.5*cm),
            Paragraph("Figure 11.2 — Regulatory pathway per target market. "
                      "Source: AI-generated. Verify with RA Lead.", ST["caption"]),
        ]),
        PageBreak(),
    ]

# ══════════════════════════════════════════════════════════════════════════
# APPENDIX A — CSV
# ══════════════════════════════════════════════════════════════════════════
def sec_csv(story, intake):
    section_header(story, "A", "Computer System Validation (CSV)", "secA",
                   "21 CFR Part 11 · FDA QMSR 2024 · GAMP 5")
    story += [
        reg_ref("21 CFR Part 11", "FDA Guidance: Software Validation (2002)",
                "GAMP 5 (2022)", "EU Annex 11"),
        sp(4),
        Paragraph("Any computerised system producing GxP records must be validated for intended use "
                  "before its outputs enter the controlled QMS document management system. "
                  "This appendix outlines the required validation activities.", ST["body"]),
        sp(6),
        Paragraph("A.1 GAMP 5 Risk Classification", ST["h2"]),
        kv_table([
            ("System Name",         "DHF Builder / AI-Assisted Document Generator"),
            ("GAMP Category",       "Category 5 — Bespoke / AI-configured software [SME-CONFIRM]"),
            ("Intended GxP Use",    "Generation of DHF draft content for QMS-controlled review"),
            ("21 CFR Part 11 Scope","Electronic records — audit trail, user authentication [SME-CONFIRM]"),
            ("Validation Owner",    intake.get("quality_lead","[SME]")),
        ], lw=5.5*cm),
        sp(6),
        Paragraph("A.2 Validation Activities Required", ST["h2"]),
        grid_table(
            ["Phase", "Activity",               "Description",                                           "Owner",     "Status"],
            [
                ["Planning", "VMP",            "Validation Master Plan — scope, approach, acceptance",  "QA",        "[SME]"],
                ["URS",      "Requirements",   "User Requirement Specification — intended use, users",  "QA + User", "[SME]"],
                ["FS/DS",    "Specifications", "Functional and Design Specifications",                  "IT/Dev",    "[SME]"],
                ["IQ",       "Installation",   "Confirm correct installation in target environment",    "IT/QA",     "[SME]"],
                ["OQ",       "Operation",      "Test all functions against FS; test all edge cases",    "QA",        "[SME]"],
                ["PQ",       "Performance",    "Extended real-use testing; data integrity checks",      "QA + User", "[SME]"],
                ["TM",       "Traceability",   "URS → FS → DS → test cases mapping",                  "QA",        "[SME]"],
                ["Report",   "Final Report",   "Compiled validation summary, approvals, open items",    "QA",        "[SME]"],
            ],
            widths=[1.8*cm, 2.0*cm, 6.2*cm, 2.2*cm, CONTENT_W-12.2*cm],
        ),
        sp(6),
        Paragraph("A.3 Audit Trail & Data Integrity Requirements (21 CFR Part 11)", ST["h2"]),
        grid_table(
            ["Requirement",                   "Implementation", "Status"],
            [
                ["Unique user IDs / authentication",              "[SME: SSO / local auth]",          "[SME]"],
                ["Audit trail (who, what, when)",                 "[SME: system logging]",            "[SME]"],
                ["Access controls per roles",                     "[SME: role-based access]",         "[SME]"],
                ["Electronic signatures (if used)",               "[SME: 21 CFR Part 11 §11.50]",    "[SME]"],
                ["Data backup & disaster recovery",               "[SME: backup schedule]",          "[SME]"],
                ["Record retention (electronic)",                 "[SME: archive policy]",            "[SME]"],
            ],
            widths=[5.5*cm, 5.5*cm, CONTENT_W-11.0*cm],
        ),
        sp(6),
        info_box(
            "No document is considered released or controlled until it has completed the "
            "organisation's QMS-controlled review and approval process.", accent=C_AZURE, bg=C_SHADE2),
    ]

# ══════════════════════════════════════════════════════════════════════════
# MAIN BUILD ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════
def build_pdf(intake: dict, output_path: str):
    with tempfile.TemporaryDirectory() as tmp:
        print("  [1/2] Generating diagrams …")
        imgs = {
            "vmodel":      gen_vmodel(intake["device_name"], tmp),
            "iso14971":    gen_iso14971(tmp),
            "risk_matrix": gen_risk_matrix(tmp),
            "block":       gen_block_diagram(intake["device_name"], tmp),
            "traceability":gen_traceability(tmp),
            "gantt":       gen_gantt(tmp),
            "fmea_rpn":    gen_fmea_overview(tmp),
            "reg_map":     gen_regulatory_map(intake.get("target_markets",[]), tmp),
        }
        if intake.get("contains_software"):
            imgs["sw_class"] = gen_sw_classification(tmp)

        print("  [2/2] Assembling PDF …")
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=1.8*cm, bottomMargin=1.8*cm,
            title=f"DHF — {intake['device_name']}",
            author="dhf_export.py",
            subject="Design History File",
            creator="dhf_export.py",
        )

        story = []
        cover_page(story, intake)
        toc_page(story)
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
        sec_traceability(story, intake, imgs)
        sec_csv(story, intake)

        decorator = CanvasDecorator(intake)
        doc.build(story, onFirstPage=decorator, onLaterPages=decorator)

    print(f"  PDF written → {output_path}")

# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="DHF Builder + PDF Exporter — Enhanced")
    parser.add_argument("--intake", required=True, help="Device intake JSON path")
    parser.add_argument("--out",    default="DHF_Report.pdf", help="Output PDF path")
    args = parser.parse_args()

    intake = json.loads(Path(args.intake).read_text())
    print(f"\nDHF Builder → {intake['device_name']}")
    print(f"Output: {args.out}\n")
    build_pdf(intake, args.out)
    print("\nDone ✓")

if __name__ == "__main__":
    main()

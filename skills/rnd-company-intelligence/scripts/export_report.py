#!/usr/bin/env python3
"""
export_report.py — OpenClaw R&D Intelligence Report Exporter  v4.0
Generates a genuine, paginated PDF (ReportLab Platypus) with:
  - a clickable Table of Contents (internal links jump to each section)
  - a navigable PDF outline / bookmark sidebar in the PDF viewer
  - wrapping table cells everywhere (no overlapping text, ever)
  - matplotlib-rendered charts embedded as images

This replaces the previous "build HTML, print-to-PDF in a browser" approach,
which is what caused overlapping cover-page fields and crammed table cells —
print engines don't reliably honor flex/grid/vertical-align, and a true flow
layout (Platypus) avoids that class of bug entirely.

Usage:
    python3 export_report.py export --input report.json --output output.pdf \
        [--title "R&D Intelligence Report"]
"""

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, Image, KeepTogether, HRFlowable, ListFlowable, ListItem
)

# --------------------------------------------------------------------------- #
# Page geometry & shared styles
# --------------------------------------------------------------------------- #

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
CONTENT_WIDTH = PAGE_W - 2 * MARGIN

INK = colors.HexColor("#1a1a1a")
INK2 = colors.HexColor("#3a3a3a")
INK3 = colors.HexColor("#6a6a6a")
INK4 = colors.HexColor("#9a9a9a")
RULE = colors.HexColor("#d8d8d4")
ACCENT = colors.HexColor("#3266ad")
BG2 = colors.HexColor("#f6f6f4")
WARN_BG = colors.HexColor("#fff6e9")
WARN_BORDER = colors.HexColor("#d98c0f")

CHART_PALETTE = ["#3266ad", "#1d9e75", "#d85a30", "#ba7517", "#533ab7", "#d4537e", "#639922", "#888780"]

_styles = getSampleStyleSheet()

STYLE_TITLE = ParagraphStyle("CoverTitle", parent=_styles["Title"], fontName="Helvetica-Bold",
                              fontSize=25, leading=30, textColor=INK, alignment=TA_LEFT, spaceAfter=4)
STYLE_SUBTITLE = ParagraphStyle("CoverSubtitle", parent=_styles["Normal"], fontSize=14,
                                 leading=18, textColor=INK2, spaceAfter=2)
STYLE_EYEBROW = ParagraphStyle("Eyebrow", parent=_styles["Normal"], fontSize=9,
                                textColor=INK4, leading=12)
STYLE_H1 = ParagraphStyle("H1", parent=_styles["Heading1"], fontName="Helvetica-Bold",
                           fontSize=16, leading=20, textColor=INK, spaceBefore=0, spaceAfter=10)
STYLE_H2 = ParagraphStyle("H2", parent=_styles["Heading2"], fontName="Helvetica-Bold",
                           fontSize=12, leading=16, textColor=INK2, spaceBefore=12, spaceAfter=6)
STYLE_BODY = ParagraphStyle("Body", parent=_styles["Normal"], fontName="Helvetica",
                             fontSize=10, leading=14.5, textColor=INK2, spaceAfter=6)
STYLE_MUTED = ParagraphStyle("Muted", parent=STYLE_BODY, textColor=INK4, fontName="Helvetica-Oblique")
STYLE_SUBNOTE = ParagraphStyle("SubNote", parent=STYLE_BODY, fontSize=9.5, textColor=INK3, spaceAfter=8)
STYLE_KV_LABEL = ParagraphStyle("KVLabel", parent=STYLE_BODY, fontName="Helvetica-Bold",
                                 fontSize=9, textColor=INK3, spaceAfter=0)
STYLE_KV_VAL = ParagraphStyle("KVVal", parent=STYLE_BODY, fontSize=9.5, spaceAfter=0)
STYLE_TABLE_HEAD = ParagraphStyle("TableHead", parent=STYLE_BODY, fontName="Helvetica-Bold",
                                   fontSize=9, textColor=INK2, spaceAfter=0)
STYLE_TABLE_CELL = ParagraphStyle("TableCell", parent=STYLE_BODY, fontSize=9, spaceAfter=0, leading=12)
STYLE_CARD_TITLE = ParagraphStyle("CardTitle", parent=STYLE_BODY, fontName="Helvetica-Bold",
                                   fontSize=10, textColor=INK, spaceAfter=2)
STYLE_CARD_META = ParagraphStyle("CardMeta", parent=STYLE_BODY, fontSize=8.5, textColor=INK4, spaceAfter=3)
STYLE_CARD_DESC = ParagraphStyle("CardDesc", parent=STYLE_BODY, fontSize=9, textColor=INK3, spaceAfter=0)
STYLE_TOC_LINK = ParagraphStyle("TOCLink", parent=STYLE_BODY, fontSize=12, leading=22, textColor=ACCENT)
STYLE_GAP = ParagraphStyle("Gap", parent=STYLE_BODY, fontSize=9, textColor=colors.HexColor("#9a6a0c"), spaceAfter=2)
STYLE_CAPTION = ParagraphStyle("Caption", parent=STYLE_BODY, fontSize=8.5, textColor=INK4,
                                fontName="Helvetica-Oblique", spaceAfter=10, spaceBefore=2)


# --------------------------------------------------------------------------- #
# Data helpers (parsing the report.json — same shapes as upstream rnd_report.py)
# --------------------------------------------------------------------------- #

def safe(d, *keys, default="—"):
    """Return the first present, non-empty value among the given alternative
    keys (e.g. safe(row, "year", "fiscal_year", "date") tries each key name
    in turn) — NOT a nested-path lookup. `d` must be a dict already."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return default


def esc(t):
    """Escape for ReportLab's mini-XML Paragraph markup."""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def flatten_gaps(g):
    if not g:
        return []
    if isinstance(g, str):
        return [g]
    if isinstance(g, list):
        return [str(x) for x in g]
    return [str(g)]


def to_float(val):
    try:
        return float(str(val).replace(",", "").replace("$", "").replace("M", "e6").replace("B", "e9"))
    except Exception:
        return 0.0


# --------------------------------------------------------------------------- #
# Bookmark / outline flowable — links the in-body TOC and the PDF sidebar
# to the same destinations
# --------------------------------------------------------------------------- #

class Bookmark(Flowable):
    """Invisible flowable: drops a named destination + outline entry at this
    point in the flow. Zero height/width — purely a side-effecting marker."""
    def __init__(self, key, title, level=0):
        Flowable.__init__(self)
        self.key = key
        self.title = title
        self.level = level
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)


def anchor(key):
    """A Paragraph carrying just an invisible named anchor, for <link href="#key">
    targets — used together with Bookmark so internal Platypus links resolve."""
    return Paragraph(f'<a name="{key}"/>', ParagraphStyle("anchor", fontSize=1, leading=1))


# --------------------------------------------------------------------------- #
# Generic layout builders
# --------------------------------------------------------------------------- #

def kv_table(pairs, label_width=42 * mm):
    """Label/value table; every cell is a Paragraph so long values wrap
    instead of colliding with the next row or column."""
    rows = [
        [Paragraph(esc(label), STYLE_KV_LABEL), Paragraph(esc(val), STYLE_KV_VAL)]
        for label, val in pairs if val and val != "—"
    ]
    if not rows:
        return None
    t = Table(rows, colWidths=[label_width, CONTENT_WIDTH - label_width])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("BACKGROUND", (0, 0), (0, -1), BG2),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def data_table(headers, rows, col_widths=None):
    """Generic data table — headers + rows of plain strings, every cell
    wrapped in a Paragraph so nothing overlaps regardless of content length."""
    if not rows:
        return None
    header_cells = [Paragraph(esc(h), STYLE_TABLE_HEAD) for h in headers]
    body_rows = [[Paragraph(esc(c), STYLE_TABLE_CELL) for c in row] for row in rows]
    data = [header_cells] + body_rows
    if col_widths is None:
        col_widths = [CONTENT_WIDTH / len(headers)] * len(headers)
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 1, INK2),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), BG2))
    t.setStyle(TableStyle(style))
    return t


def info_card(title, meta_parts, desc, link=None):
    """A bordered card (used for patents, papers, competitors) — single-cell
    Table acting as a box so it can use KeepTogether and a border."""
    elements = [Paragraph(esc(title), STYLE_CARD_TITLE)]
    meta_str = " · ".join(p for p in meta_parts if p and p != "—")
    if meta_str:
        elements.append(Paragraph(esc(meta_str), STYLE_CARD_META))
    if desc and desc != "—":
        elements.append(Paragraph(esc(desc), STYLE_CARD_DESC))
    if link and link != "—":
        elements.append(Paragraph(f'<link href="{esc(link)}" color="#3266ad">{esc(link)}</link>',
                                   ParagraphStyle("cardlink", parent=STYLE_CARD_META, textColor=ACCENT)))
    inner = Table([[elements]], colWidths=[CONTENT_WIDTH])
    inner.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return KeepTogether(inner)


def gap_box(gaps):
    if not gaps:
        return None
    items = [Paragraph(esc(g), STYLE_GAP) for g in gaps]
    inner = Table([[items]], colWidths=[CONTENT_WIDTH])
    inner.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0, colors.white),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, WARN_BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return inner


# --------------------------------------------------------------------------- #
# Charts (matplotlib -> PNG -> Image flowable)
# --------------------------------------------------------------------------- #

def _save_chart(fig, path):
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _human_currency(val, _pos=None):
    av = abs(val)
    if av >= 1e9:
        return f"${val/1e9:.0f}B"
    if av >= 1e6:
        return f"${val/1e6:.0f}M"
    if av >= 1e3:
        return f"${val/1e3:.0f}K"
    return f"${val:.0f}"


def chart_bar(labels, values, title, ylabel, out_path, color=CHART_PALETTE[0]):
    if not labels or not any(v > 0 for v in values):
        return None
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.bar(labels, values, color=color, edgecolor="none")
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(axis="x", labelsize=8, rotation=30)
    ax.tick_params(axis="y", labelsize=8)
    if max(values) >= 1000:
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(_human_currency))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#eeeeee", linewidth=0.8)
    _save_chart(fig, out_path)
    return out_path


def chart_line(labels, values, title, ylabel, out_path, color=CHART_PALETTE[1]):
    if not labels:
        return None
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.plot(labels, values, color=color, linewidth=2, marker="o", markersize=3)
    ax.fill_between(range(len(labels)), values, color=color, alpha=0.08)
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=9)
    step = max(1, len(labels) // 12)
    ax.set_xticks(range(0, len(labels), step))
    ax.set_xticklabels([labels[i] for i in range(0, len(labels), step)], fontsize=7, rotation=45, ha="right")
    ax.tick_params(axis="y", labelsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#eeeeee", linewidth=0.8)
    _save_chart(fig, out_path)
    return out_path


def chart_pie(labels, values, title, out_path, max_segments=6):
    pairs = list(zip(labels, values))
    if len(pairs) > max_segments:
        pairs.sort(key=lambda p: -p[1])
        head, tail = pairs[:max_segments - 1], pairs[max_segments - 1:]
        other_sum = sum(v for _, v in tail)
        pairs = head + [("Other", other_sum)]
    labels2 = [p[0] for p in pairs]
    values2 = [p[1] for p in pairs]
    if not values2 or sum(values2) <= 0:
        return None
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.pie(values2, labels=labels2, autopct="%1.0f%%", colors=CHART_PALETTE,
           textprops={"fontsize": 8})
    ax.set_title(title, fontsize=11)
    _save_chart(fig, out_path)
    return out_path


def chart_hbar(labels, values, title, xlabel, out_path, color=CHART_PALETTE[4]):
    if not labels:
        return None
    fig_h = max(len(labels) * 0.4 + 1, 2.5)
    fig, ax = plt.subplots(figsize=(6, fig_h))
    y_pos = range(len(labels))
    ax.barh(y_pos, values, color=color)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color="#eeeeee", linewidth=0.8)
    _save_chart(fig, out_path)
    return out_path


def chart_image_flowable(path, caption=None, max_width=CONTENT_WIDTH, max_height=85 * mm):
    if not path or not os.path.exists(path):
        return []
    img = Image(path)
    iw, ih = img.imageWidth, img.imageHeight
    scale = min(max_width / iw, max_height / ih, 1.0)
    img.drawWidth = iw * scale
    img.drawHeight = ih * scale
    flows = [img]
    if caption:
        flows.append(Paragraph(esc(caption), STYLE_CAPTION))
    return flows


# --------------------------------------------------------------------------- #
# Section builders — each returns a list of flowables
# --------------------------------------------------------------------------- #

def section_heading(num, title, key):
    return [
        Bookmark(key, f"{num}. {title}", level=0),
        anchor(key),
        Paragraph(esc(f"{num}. {title}"), STYLE_H1),
        HRFlowable(width="100%", thickness=1, color=RULE, spaceAfter=10, spaceBefore=0),
    ]


def build_company(data, charts_dir):
    cd = data.get("company-details", {})
    profile = cd.get("profile", cd)
    flows = []
    pairs = [
        ("Legal name", safe(profile, "legal_name")),
        ("Description", safe(profile, "short_description")),
        ("Website", safe(profile, "website_url")),
        ("Country", safe(profile, "country_code")),
        ("Founded", safe(profile, "founded_on")),
        ("Employees", safe(profile, "num_employees_enum")),
        ("Total funding", safe(profile, "total_funding_usd")),
    ]
    t = kv_table(pairs)
    if t:
        flows.append(t)
        flows.append(Spacer(1, 6 * mm))

    people = profile.get("people", []) if isinstance(profile, dict) else []
    rows = [[safe(p, "name"), safe(p, "title")] for p in people if isinstance(p, dict)]
    if rows:
        flows.append(Paragraph("Key people", STYLE_H2))
        dt = data_table(["Name", "Title"], rows, col_widths=[55 * mm, CONTENT_WIDTH - 55 * mm])
        if dt:
            flows.append(dt)
            flows.append(Spacer(1, 4 * mm))

    gaps = flatten_gaps(cd.get("data_gaps"))
    gb = gap_box(gaps)
    if gb:
        flows.append(gb)
    return flows


def build_turnover(data, charts_dir):
    tv = data.get("turnover", {})
    rows_data = tv.get("rows", [])
    flows = []
    chart_labels, chart_values, table_rows = [], [], []

    for row in (rows_data or []):
        if isinstance(row, dict):
            year = safe(row, "year", "fiscal_year", "date")
            rev = safe(row, "revenue", "revenue_usd", "value", "amount")
            note = safe(row, "label", "metric", "note")
            table_rows.append([year, rev, note])
            chart_labels.append(str(year))
            chart_values.append(to_float(rev))

    if table_rows:
        dt = data_table(["Period", "Revenue / Value", "Note"], table_rows,
                         col_widths=[28 * mm, 38 * mm, CONTENT_WIDTH - 66 * mm])
        flows.append(dt)
        flows.append(Spacer(1, 4 * mm))
    else:
        flows.append(Paragraph(
            "No structured financial data retrieved. This company may be private "
            "or a paid-API tier limit applied.", STYLE_MUTED))

    if chart_labels and any(v > 0 for v in chart_values):
        path = chart_bar(chart_labels, chart_values, "Revenue by Period", "Revenue (USD)",
                          os.path.join(charts_dir, "turnover_bar.png"))
        flows.extend(chart_image_flowable(path, caption="Figure — Revenue over time"))

    meta_pairs = [(k, safe(tv, v)) for k, v in
                  [("Source", "source_label"), ("Public", "is_public"), ("Ticker", "ticker")]]
    mt = kv_table(meta_pairs)
    if mt:
        flows.append(mt)
        flows.append(Spacer(1, 4 * mm))

    gb = gap_box(flatten_gaps(tv.get("data_gaps")))
    if gb:
        flows.append(gb)
    return flows


def build_patents(data, charts_dir):
    pt = data.get("patents", {})
    patents_list = pt.get("patents", [])
    flows = []
    total = safe(pt, "count", default=str(len(patents_list) if isinstance(patents_list, list) else 0))
    flows.append(Paragraph(f"Total records: <b>{esc(total)}</b>", STYLE_SUBNOTE))

    tech = pt.get("tech_areas", [])
    if tech and isinstance(tech, list) and len(tech) >= 2:
        labels = [str(t) for t in tech[:8]]
        values = [1] * len(labels)
        path = chart_pie(labels, values, "Patent Portfolio — Technology Areas",
                          os.path.join(charts_dir, "patents_pie.png"))
        flows.extend(chart_image_flowable(path, caption="Figure — Distribution across major tech areas",
                                           max_height=70 * mm))

    for pat in (patents_list or []):
        if not isinstance(pat, dict):
            continue
        title = safe(pat, "title")
        link = safe(pat, "link")
        pub = safe(pat, "publication_date")
        abstr = safe(pat, "abstract_snippet")
        assign = safe(pat, "assignee")
        flows.append(info_card(title, [assign, pub], abstr, link=link if link != "—" else None))
        flows.append(Spacer(1, 3 * mm))

    gb = gap_box(flatten_gaps(pt.get("data_gaps")))
    if gb:
        flows.append(gb)
    return flows


def build_trends(data, charts_dir):
    tr = data.get("trends", {})
    flows = []
    meta = kv_table([("Product", safe(tr, "product")), ("Geography", safe(tr, "geo")),
                      ("Since", safe(tr, "since"))])
    if meta:
        flows.append(meta)
        flows.append(Spacer(1, 4 * mm))

    timeline = tr.get("timeline", [])
    chart_labels, chart_values = [], []
    for entry in (timeline or []):
        if isinstance(entry, dict):
            date = safe(entry, "date")
            vals = entry.get("values", [])
            val = 0
            if isinstance(vals, list) and vals:
                v0 = vals[0]
                try:
                    val = int(v0.get("extracted_value", 0)) if isinstance(v0, dict) else int(v0)
                except Exception:
                    val = 0
            elif isinstance(vals, dict):
                try:
                    val = int(safe(vals, "extracted_value", "value", default=0))
                except Exception:
                    val = 0
            chart_labels.append(str(date))
            chart_values.append(val)

    if chart_labels:
        path = chart_line(chart_labels, chart_values, "Search Interest Over Time", "Interest Index (0-100)",
                           os.path.join(charts_dir, "trend_line.png"))
        flows.extend(chart_image_flowable(path, caption="Figure — Interest over time"))

    rq = tr.get("related_queries", {})
    if isinstance(rq, dict):
        for grp, items in rq.items():
            if isinstance(items, list) and items:
                flows.append(Paragraph(f"Related queries — {esc(grp)}", STYLE_H2))
                bullets = []
                for item in items:
                    if isinstance(item, dict):
                        q = safe(item, "query", "title")
                        bullets.append(ListItem(Paragraph(esc(q), STYLE_BODY), leftIndent=10))
                if bullets:
                    flows.append(ListFlowable(bullets, bulletType="bullet", start="circle"))

    gb = gap_box(flatten_gaps(tr.get("data_gaps")))
    if gb:
        flows.append(gb)
    return flows


def build_competitors(data, charts_dir):
    comp = data.get("competitors", {})
    competitors_list = comp.get("competitors", [])
    flows = []
    count = len(competitors_list) if isinstance(competitors_list, list) else 0
    flows.append(Paragraph(f"Market peers identified: <b>{count}</b>", STYLE_SUBNOTE))

    named = [c for c in (competitors_list or []) if isinstance(c, dict) and
             safe(c, "name") != "—" and
             not any(x in safe(c, "name", default="").lower()
                     for x in ["market size", "market share", "report", "forecast", "industry"])]

    for c in named:
        name = safe(c, "name")
        desc = safe(c, "description")
        url = safe(c, "website")
        fund = safe(c, "funding_usd")
        found = safe(c, "founded")
        meta_bits = [x for x in [f"Funding: {fund}" if fund != "—" else "",
                                  f"Founded: {found}" if found != "—" else ""] if x]
        flows.append(info_card(name, meta_bits, desc, link=url if url != "—" else None))
        flows.append(Spacer(1, 3 * mm))

    if not named and competitors_list:
        rows = []
        for c in competitors_list:
            if isinstance(c, dict):
                name = safe(c, "name")
                desc = safe(c, "description")
                desc_short = (desc[:160] + "…") if isinstance(desc, str) and len(desc) > 160 else desc
                rows.append([name, desc_short])
        dt = data_table(["Source", "Summary"], rows, col_widths=[45 * mm, CONTENT_WIDTH - 45 * mm])
        if dt:
            flows.append(dt)

    gb = gap_box(flatten_gaps(comp.get("data_gaps")))
    if gb:
        flows.append(gb)
    return flows


def build_research(data, charts_dir):
    rp = data.get("research-papers", {})
    papers = rp.get("papers", [])
    flows = []
    count = safe(rp, "count", default=str(len(papers) if isinstance(papers, list) else 0))
    flows.append(Paragraph(f"Academic papers retrieved: <b>{esc(count)}</b>", STYLE_SUBNOTE))

    citable = [(safe(p, "title"), safe(p, "cited_by")) for p in (papers or []) if isinstance(p, dict)]
    citable = [(t[:48] + "…" if isinstance(t, str) and len(t) > 48 else t, c)
               for t, c in citable if c and c != "—"]
    try:
        citable = sorted([(t, int(str(c).replace(",", ""))) for t, c in citable], key=lambda x: -x[1])[:8]
    except Exception:
        citable = []

    if citable:
        clabels = [t for t, _ in citable]
        cvals = [v for _, v in citable]
        path = chart_hbar(clabels, cvals, "Citations per Paper", "Citations",
                           os.path.join(charts_dir, "papers_hbar.png"))
        flows.extend(chart_image_flowable(path, caption="Figure — Most-cited papers", max_height=110 * mm))

    for paper in (papers or []):
        if not isinstance(paper, dict):
            continue
        title = safe(paper, "title")
        authors = safe(paper, "authors")
        year = safe(paper, "year")
        venue = safe(paper, "venue")
        cited = safe(paper, "cited_by")
        snippet = safe(paper, "snippet")
        link = safe(paper, "link")
        meta_bits = [authors, year, venue]
        if cited and cited != "—":
            title = f"{title}  (cited {cited}×)"
        flows.append(info_card(title, meta_bits, snippet, link=link if link != "—" else None))
        flows.append(Spacer(1, 3 * mm))

    gb = gap_box(flatten_gaps(rp.get("data_gaps")))
    if gb:
        flows.append(gb)
    return flows


def build_quality(data, charts_dir):
    section_map = {
        "company-details": "Company overview", "turnover": "Financial overview",
        "patents": "Patents", "trends": "Market trends",
        "competitors": "Competitive landscape", "research-papers": "Research papers",
    }
    flows = [Paragraph("Automatically logged by the OpenClaw intelligence pipeline.", STYLE_BODY)]
    found = False
    for key, label in section_map.items():
        sec = data.get(key, {})
        gaps = flatten_gaps(sec.get("data_gaps") if isinstance(sec, dict) else None)
        if gaps:
            found = True
            flows.append(Paragraph(esc(label), STYLE_H2))
            bullets = [ListItem(Paragraph(esc(g), STYLE_BODY), leftIndent=10) for g in gaps]
            flows.append(ListFlowable(bullets, bulletType="bullet", start="circle"))
    if not found:
        flows.append(Paragraph("No data gaps recorded for this run.", STYLE_MUTED))
    return flows


SECTIONS = [
    ("sec1", "Company & Product Overview", "company-details", build_company),
    ("sec2", "Financial Overview", "turnover", build_turnover),
    ("sec3", "Patents & Intellectual Property", "patents", build_patents),
    ("sec4", "Market Trends & Demand Signals", "trends", build_trends),
    ("sec5", "Competitive Landscape", "competitors", build_competitors),
    ("sec6", "Research & Literature", "research-papers", build_research),
    ("sec7", "Data Quality Notes", None, build_quality),
]


# --------------------------------------------------------------------------- #
# Cover page, TOC, header/footer
# --------------------------------------------------------------------------- #

def build_cover(raw, data, title):
    company = safe(raw, "company", default=safe(data, "company-details", "company", default="Company"))
    product = safe(raw, "product", default="Product")
    as_of = safe(raw, "as_of", default="")
    flows = [Spacer(1, 50 * mm)]
    flows.append(Paragraph("OPENCLAW R&amp;D INTELLIGENCE PLATFORM", STYLE_EYEBROW))
    flows.append(Spacer(1, 4 * mm))
    flows.append(Paragraph(esc(title), STYLE_TITLE))
    flows.append(Paragraph(f"{esc(company)} &middot; {esc(product)}", STYLE_SUBTITLE))
    if as_of and as_of != "—":
        flows.append(Spacer(1, 3 * mm))
        flows.append(Paragraph(esc(as_of), STYLE_EYEBROW))
    flows.append(Spacer(1, 6 * mm))
    flows.append(Paragraph("Confidential — for internal use only", STYLE_MUTED))
    return flows


def build_toc():
    flows = [Paragraph("Table of Contents", STYLE_H1), Spacer(1, 4 * mm)]
    for i, (key, title, _, _) in enumerate(SECTIONS, start=1):
        flows.append(Paragraph(f'<link href="#{key}">{i}. {esc(title)}</link>', STYLE_TOC_LINK))
    return flows


def header_footer(canvas_obj, doc):
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(INK4)
    canvas_obj.drawString(MARGIN, PAGE_H - 13 * mm, doc.report_title)
    canvas_obj.drawRightString(PAGE_W - MARGIN, 13 * mm, f"Page {doc.page}")
    canvas_obj.setStrokeColor(RULE)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(MARGIN, PAGE_H - 15 * mm, PAGE_W - MARGIN, PAGE_H - 15 * mm)
    canvas_obj.restoreState()


def first_page(canvas_obj, doc):
    """No header rule on the cover page itself — just the page number."""
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(INK4)
    canvas_obj.drawRightString(PAGE_W - MARGIN, 13 * mm, f"Page {doc.page}")
    canvas_obj.restoreState()


# --------------------------------------------------------------------------- #
# Main build
# --------------------------------------------------------------------------- #

def build_pdf(raw, data, title, out_path, charts_dir):
    os.makedirs(charts_dir, exist_ok=True)

    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        topMargin=MARGIN + 4 * mm, bottomMargin=MARGIN,
        leftMargin=MARGIN, rightMargin=MARGIN,
        title=title,
    )
    doc.report_title = title

    story = []
    story.extend(build_cover(raw, data, title))
    story.append(PageBreak())
    story.extend(build_toc())
    story.append(PageBreak())

    for i, (key, sec_title, data_key, builder) in enumerate(SECTIONS, start=1):
        story.extend(section_heading(i, sec_title, key))
        story.extend(builder(data, charts_dir))
        if i < len(SECTIONS):
            story.append(PageBreak())

    doc.build(story, onFirstPage=first_page, onLaterPages=header_footer)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="OpenClaw report exporter v4.0 (real PDF, ReportLab)")
    sub = parser.add_subparsers(dest="command")

    ep = sub.add_parser("export")
    ep.add_argument("--title", default="R&D Intelligence Report")
    ep.add_argument("--input", required=True, help="Path to report.json")
    ep.add_argument("--output", required=True, help="Path to write the .pdf")
    ep.add_argument("--charts-dir", default=None, help="Where to write chart PNGs (defaults next to output)")

    args = parser.parse_args()
    if args.command != "export":
        parser.print_help()
        return

    inp = os.path.expanduser(args.input)
    out = os.path.expanduser(args.output)
    if not out.endswith(".pdf"):
        out = str(Path(out).with_suffix(".pdf"))

    if not os.path.exists(inp):
        print(f"[error] Input not found: {inp}", file=sys.stderr)
        sys.exit(1)

    with open(inp, "r", encoding="utf-8") as f:
        raw = json.load(f)

    data = raw
    if isinstance(raw, dict):
        if "sections" in raw:
            data = raw["sections"]
        elif "data" in raw:
            data = raw["data"]

    charts_dir = args.charts_dir or str(Path(out).parent / "charts")
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    build_pdf(raw, data, args.title, out, charts_dir)
    print(f"[export_report] PDF generated -> {out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
dhf_suture.py - Evidence-cautious DHF Builder for Surgical Sutures

Key changes in this version:
- Removes hard-coded market-share claims, fake predicate K-numbers, and unsupported quantitative claims.
- Clearly labels live retrieved evidence vs. reference checklists vs. items requiring SME confirmation.
- Adds evidence confidence scoring and "known unknowns" sections.
- Avoids presenting patents, competitors, standards, or predicates as confirmed unless retrieved from a source.
- Keeps the PDF useful for DHF drafting while reducing hallucination risk.

Install:
  pip install requests beautifulsoup4 lxml reportlab

Usage:
  python3 dhf_suture.py --intake intake.json --out DHF_Suture.pdf
  python3 dhf_suture.py --intake intake.json --cache data.json --out DHF.pdf
  python3 dhf_suture.py --intake intake.json --cache data.json --cached --out DHF.pdf
"""

import argparse
import html
import json
import os
import re
import textwrap
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAGE_W, PAGE_H = A4
MARGIN = 1.8 * cm
CONTENT_W = PAGE_W - 2 * MARGIN
TODAY = date.today().isoformat()
RETRY = 2
DELAY = 0.8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

SOURCES = [
    "PubMed",
    "FDA 510(k)",
    "FDA Recalls",
    "FDA Classification",
    "ClinicalTrials.gov",
    "Europe PMC",
    "Semantic Scholar",
    "Google Patents",
    "WIPO",
    "EMA",
]

C_INK = HexColor("#0D1117")
C_NAVY = HexColor("#0F2D52")
C_BLUE = HexColor("#1A5FA8")
C_TEAL = HexColor("#0E9F8E")
C_RULE = HexColor("#CBD5E1")
C_SHADE = HexColor("#F1F5F9")
C_WARN_BG = HexColor("#FFFBEB")
C_WARN = HexColor("#B45309")
C_GREEN = HexColor("#16A34A")
C_RED = HexColor("#DC2626")
C_SLATE = HexColor("#475569")
C_WHITE = colors.white


def safe(value):
    if value is None:
        return ""
    value = str(value).strip()
    value = re.sub(r"<[^>]*>", "", value)
    return html.escape(value)


def trunc(value, n=80):
    value = str(value or "").strip()
    return value[: n - 1] + "…" if len(value) > n else value


def style(name, **kwargs):
    return ParagraphStyle(name, **kwargs)


ST = {
    "cover_title": style(
        "cover_title",
        fontName="Helvetica-Bold",
        fontSize=25,
        leading=31,
        alignment=TA_CENTER,
        textColor=C_WHITE,
    ),
    "cover_sub": style(
        "cover_sub",
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        textColor=HexColor("#DDE7F2"),
    ),
    "h1": style(
        "h1",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=C_NAVY,
        spaceBefore=12,
        spaceAfter=5,
        keepWithNext=True,
    ),
    "h2": style(
        "h2",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=C_BLUE,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    ),
    "body": style(
        "body",
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=C_INK,
        alignment=TA_JUSTIFY,
        spaceAfter=4,
    ),
    "small": style(
        "small",
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=C_INK,
    ),
    "th": style(
        "th",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=C_WHITE,
    ),
    "td": style(
        "td",
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=C_INK,
    ),
    "label": style(
        "label",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=C_SLATE,
    ),
    "value": style(
        "value",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=C_INK,
    ),
    "notice": style(
        "notice",
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=12,
        textColor=C_SLATE,
        alignment=TA_JUSTIFY,
    ),
    "caption": style(
        "caption",
        fontName="Helvetica-Oblique",
        fontSize=7.5,
        leading=10,
        alignment=TA_CENTER,
        textColor=C_SLATE,
    ),
}


USP_SIZE_TABLE = [
    ("11-0", "0.1", 0.010, 0.019, "Verify against current USP <861>/<881>"),
    ("10-0", "0.2", 0.020, 0.029, "Verify against current USP <861>/<881>"),
    ("9-0", "0.3", 0.030, 0.039, "Verify against current USP <861>/<881>"),
    ("8-0", "0.4", 0.040, 0.049, "Verify against current USP <861>/<881>"),
    ("7-0", "0.5", 0.050, 0.069, "Verify against current USP <861>/<881>"),
    ("6-0", "0.7", 0.070, 0.099, "Verify against current USP <861>/<881>"),
    ("5-0", "1.0", 0.100, 0.149, "Verify against current USP <861>/<881>"),
    ("4-0", "1.5", 0.150, 0.199, "Verify against current USP <861>/<881>"),
    ("3-0", "2.0", 0.200, 0.249, "Verify against current USP <861>/<881>"),
    ("2-0", "3.0", 0.300, 0.339, "Verify against current USP <861>/<881>"),
    ("0", "3.5", 0.350, 0.399, "Verify against current USP <861>/<881>"),
    ("1", "4.0", 0.400, 0.499, "Verify against current USP <861>/<881>"),
    ("2", "5.0", 0.500, 0.599, "Verify against current USP <861>/<881>"),
]


MATERIAL_REFERENCE = [
    (
        "Polyglactin 910 / PGLA",
        "Synthetic absorbable",
        "Braided",
        "Commonly used for soft tissue approximation. Exact tensile-retention and absorption profile must be verified from current IFU and bench testing.",
    ),
    (
        "Polyglycolic Acid / PGA",
        "Synthetic absorbable",
        "Braided",
        "Common absorbable braided material. Use current standards and supplier resin data for design inputs.",
    ),
    (
        "Polydioxanone / PDS",
        "Synthetic absorbable",
        "Monofilament",
        "Often selected where longer strength retention is needed. Verify profile against predicate IFU and test data.",
    ),
    (
        "Poliglecaprone 25",
        "Synthetic absorbable",
        "Monofilament",
        "Often used for lower-drag short-term support. Confirm use case and absorption profile with testing.",
    ),
    (
        "Polypropylene",
        "Synthetic non-absorbable",
        "Monofilament",
        "Used where permanent support is desired. Verify indications and biocompatibility endpoint set.",
    ),
    (
        "Nylon",
        "Synthetic non-absorbable",
        "Mono or braided",
        "May gradually lose tensile strength in vivo. Confirm claims using current literature and IFU.",
    ),
    (
        "Polyester",
        "Synthetic non-absorbable",
        "Braided",
        "High strength, braided handling. Coating and tissue response must be characterized.",
    ),
    (
        "Silk",
        "Natural non-absorbable classification varies by jurisdiction",
        "Braided",
        "Known tissue reaction considerations. Regulatory classification and degradation claims require confirmation.",
    ),
]


BASELINE_HAZARDS = [
    (
        "Mechanical",
        "Suture breakage",
        "Insufficient tensile strength, material defect, damage during handling",
        "Wound dehiscence, re-operation",
        "USP tensile testing, incoming inspection, lot release",
    ),
    (
        "Mechanical",
        "Knot slippage",
        "Poor knot security, coating/lubricity mismatch, incorrect technique",
        "Wound opening, bleeding, delayed healing",
        "Knot security testing, IFU knot guidance, surgeon usability validation",
    ),
    (
        "Mechanical",
        "Needle detachment",
        "Swage/crimp defect or excessive pull force",
        "Retained needle, tissue injury, procedure delay",
        "Needle attachment pull testing and process controls",
    ),
    (
        "Biological",
        "Excessive tissue reaction",
        "Material, dye, coating, residue, degradation product",
        "Inflammation, granuloma, delayed healing",
        "ISO 10993 biological evaluation and chemical characterization",
    ),
    (
        "Biological",
        "Surgical site infection",
        "Contamination, capillary effect in braided materials, handling error",
        "SSI, sepsis in severe cases",
        "Sterility validation, packaging validation, optional antimicrobial risk-benefit analysis",
    ),
    (
        "Manufacturing",
        "Diameter out of specification",
        "Extrusion/drawing/braiding process drift",
        "Incorrect USP size classification or performance mismatch",
        "Diameter inspection, SPC, batch release criteria",
    ),
    (
        "Manufacturing",
        "Sterile barrier failure",
        "Seal defect, material puncture, transport damage",
        "Loss of sterility",
        "ISO 11607 packaging validation, seal strength, dye leak, transport testing",
    ),
    (
        "Use-related",
        "Wrong suture selected",
        "Unclear labeling, IFU ambiguity, training gap",
        "Insufficient support or unnecessary foreign body burden",
        "Clear labeling, indications matrix, usability engineering",
    ),
]


STANDARD_CHECKLIST = [
    ("ISO 13485", "Quality management system", "Confirm current edition and certification scope"),
    ("ISO 14971", "Risk management", "Use for hazard analysis and residual risk acceptability"),
    ("ISO 10993-1", "Biological evaluation planning", "Endpoint selection depends on contact type and duration"),
    ("ISO 10993-5", "Cytotoxicity", "Usually relevant for patient-contacting sutures"),
    ("ISO 10993-6", "Local effects after implantation", "Usually relevant for implantable sutures"),
    ("ISO 10993-10 / ISO 10993-23", "Sensitization and irritation", "Confirm current endpoint split"),
    ("ISO 10993-7", "Ethylene oxide residuals", "Relevant if EtO sterilized"),
    ("ISO 11135", "Ethylene oxide sterilization", "Relevant if EtO sterilized"),
    ("ISO 11137", "Radiation sterilization", "Relevant if radiation sterilized"),
    ("ISO 11607-1/-2", "Sterile barrier packaging", "Relevant for sterile product"),
    ("ISO 15223-1", "Medical device symbols", "Relevant for labeling"),
    ("IEC 62366-1", "Usability engineering", "Relevant for use-related risk controls"),
    ("USP <861>", "Suture diameter", "Use current official text for numeric limits"),
    ("USP <871>", "Needle attachment", "Use current official text for acceptance criteria"),
    ("USP <881>", "Tensile strength", "Use current official text for acceptance criteria"),
    ("Ph. Eur. suture monographs", "European pharmacopoeial requirements", "Confirm exact monograph by absorbable/non-absorbable type"),
    ("ASTM F88", "Seal strength", "Common packaging verification method"),
    ("ASTM F1929", "Dye penetration", "Common porous package leak test"),
    ("ASTM F1980", "Accelerated aging", "Use with justified Q10 and real-time aging plan"),
]


@dataclass
class EvidenceItem:
    source: str
    title: str
    year: str = ""
    identifier: str = ""
    url: str = ""
    detail: str = ""
    confidence: str = "Retrieved"


class Bookmark(Flowable):
    def __init__(self, key, title, level=0):
        super().__init__()
        self.key = key
        self.title = title
        self.level = level
        self.width = 0
        self.height = 0

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=False)


class SectionHeader(Flowable):
    def __init__(self, num, title, subtitle=""):
        super().__init__()
        self.num = str(num)
        self.title = title
        self.subtitle = subtitle
        self.height = 48

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(C_NAVY)
        c.roundRect(0, 0, self.width, self.height, 5, fill=1, stroke=0)
        c.setFillColor(C_TEAL)
        c.roundRect(0, 0, 38, self.height, 5, fill=1, stroke=0)
        c.rect(30, 0, 12, self.height, fill=1, stroke=0)
        c.setFillColor(C_WHITE)
        c.setFont("Helvetica-Bold", 15)
        c.drawCentredString(19, 17, self.num)
        c.setFont("Helvetica-Bold", 12.5)
        c.drawString(52, 27, self.title)
        if self.subtitle:
            c.setFont("Helvetica", 7.5)
            c.setFillColor(HexColor("#DDE7F2"))
            c.drawString(52, 13, self.subtitle)


class BarChart(Flowable):
    def __init__(self, counts, width, height=150):
        super().__init__()
        self.counts = counts
        self.width = width
        self.height = height

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        max_v = max([v for v in self.counts.values()] + [1])
        x0 = 20
        y0 = 30
        plot_w = self.width - 40
        plot_h = self.height - 55
        labels = list(self.counts.keys())
        bar_gap = 4
        bar_w = max(8, (plot_w / max(1, len(labels))) - bar_gap)

        c.setStrokeColor(C_RULE)
        c.line(x0, y0, x0 + plot_w, y0)
        c.line(x0, y0, x0, y0 + plot_h)

        for i, label in enumerate(labels):
            value = self.counts[label]
            h = (value / max_v) * plot_h
            x = x0 + i * (bar_w + bar_gap)
            c.setFillColor(C_BLUE if value else C_RULE)
            c.rect(x, y0, bar_w, h, fill=1, stroke=0)
            c.setFillColor(C_INK)
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(x + bar_w / 2, y0 + h + 3, str(value))
            c.setFillColor(C_SLATE)
            c.setFont("Helvetica", 5.5)
            c.saveState()
            c.translate(x + bar_w / 2, 12)
            c.rotate(25)
            c.drawCentredString(0, 0, label[:16])
            c.restoreState()


def sp(height=6):
    return Spacer(1, height)


def hr():
    return HRFlowable(width="100%", thickness=0.6, color=C_RULE, spaceBefore=4, spaceAfter=6)


def anchor(key):
    return Paragraph(f'<a name="{key}"/>', ParagraphStyle("_anchor", fontSize=1, leading=1))


def sec(story, num, title, key, subtitle=""):
    story.extend([Bookmark(key, f"{num}. {title}"), anchor(key), SectionHeader(num, title, subtitle), sp(8)])


def para(text):
    return Paragraph(text, ST["body"])


def notice(text, accent=C_BLUE, bg=HexColor("#E0F2FE")):
    t = Table([[Paragraph(text, ST["notice"])]], colWidths=[CONTENT_W])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
                ("BOX", (0, 0), (-1, -1), 0.4, C_RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return t


def grid(headers, rows, widths=None, small=False):
    if not rows:
        return notice("No rows available for this section.", accent=C_WARN, bg=C_WARN_BG)

    style_td = ST["small"] if small else ST["td"]
    data = [[Paragraph(safe(h), ST["th"]) for h in headers]]
    for row in rows:
        data.append([Paragraph(safe(cell), style_td) for cell in row])

    col_widths = widths or [CONTENT_W / len(headers)] * len(headers)
    t = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), C_NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_SHADE]),
                ("BOX", (0, 0), (-1, -1), 0.45, C_RULE),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, C_RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def kv_table(pairs):
    rows = []
    for key, value in pairs:
        rows.append([Paragraph(safe(key), ST["label"]), Paragraph(safe(value), ST["value"])])
    t = Table(rows, colWidths=[4.3 * cm, CONTENT_W - 4.3 * cm], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_SHADE]),
                ("BOX", (0, 0), (-1, -1), 0.45, C_RULE),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, C_RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


class PageDecor:
    def __init__(self, intake):
        self.device = safe(intake.get("device_name", "Suture Device"))
        self.model = safe(intake.get("model_number", "TBD"))

    def __call__(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_NAVY)
        canvas.rect(MARGIN, PAGE_H - 1.45 * cm, CONTENT_W, 0.65 * cm, fill=1, stroke=0)
        canvas.setFillColor(C_WHITE)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawString(MARGIN + 5, PAGE_H - 1.05 * cm, "DESIGN HISTORY FILE DRAFT - EVIDENCE CAUTIOUS")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(
            PAGE_W - MARGIN - 5,
            PAGE_H - 1.05 * cm,
            f"{self.device} | {self.model}",
        )
        canvas.setStrokeColor(C_RULE)
        canvas.line(MARGIN, 1.25 * cm, PAGE_W - MARGIN, 1.25 * cm)
        canvas.setFillColor(C_SLATE)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(
            MARGIN,
            0.85 * cm,
            f"Generated {TODAY}. Draft content requires SME, regulatory, clinical, and legal review before submission.",
        )
        canvas.drawRightString(PAGE_W - MARGIN, 0.85 * cm, f"Page {doc.page}")
        canvas.restoreState()


class ResearchEngine:
    def __init__(self, device_name, intended_use="", fda_class="II"):
        self.device_name = device_name
        self.intended_use = intended_use
        self.fda_class = fda_class
        self.query = device_name if "suture" in device_name.lower() else f"{device_name} suture"
        self.q = quote_plus(self.query)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.results = {
            "pubmed": [],
            "fda_510k": [],
            "fda_recalls": [],
            "fda_classification": [],
            "clinical_trials": [],
            "europe_pmc": [],
            "semantic_scholar": [],
            "google_patents": [],
            "wipo": [],
            "ema": [],
            "errors": [],
        }

    def _get(self, url, params=None, json_r=False, timeout=18):
        for attempt in range(RETRY):
            try:
                r = self.session.get(url, params=params, timeout=timeout)
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", DELAY * (attempt + 2)))
                    time.sleep(wait)
                    continue
                if 200 <= r.status_code < 300:
                    return r.json() if json_r else r
                self.results["errors"].append(
                    {"url": url, "status": r.status_code, "message": trunc(r.text, 120)}
                )
                return None
            except Exception as exc:
                self.results["errors"].append({"url": url, "status": "EXCEPTION", "message": str(exc)})
                time.sleep(DELAY)
        return None

    def fetch_pubmed(self):
        data = self._get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            json_r=True,
            params={
                "db": "pubmed",
                "term": f"{self.query}[Title/Abstract]",
                "retmax": 12,
                "retmode": "json",
                "sort": "relevance",
            },
        )
        ids = (data or {}).get("esearchresult", {}).get("idlist", [])
        if not ids:
            return

        summary = self._get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            json_r=True,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        )
        result = (summary or {}).get("result", {})
        for uid in result.get("uids", []):
            item = result.get(uid, {})
            self.results["pubmed"].append(
                {
                    "title": item.get("title", ""),
                    "year": item.get("pubdate", "")[:4],
                    "journal": item.get("source", ""),
                    "authors": ", ".join(a.get("name", "") for a in item.get("authors", [])[:4]),
                    "pmid": uid,
                    "pubtype": ", ".join(item.get("pubtype", [])[:3]),
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                }
            )

    def fetch_fda(self):
        data = self._get(
            "https://api.fda.gov/device/510k.json",
            json_r=True,
            params={
                "search": f'device_name:"{self.query}"',
                "limit": 10,
                "sort": "decision_date:desc",
            },
        )
        for item in (data or {}).get("results", []):
            self.results["fda_510k"].append(
                {
                    "k_number": item.get("k_number", ""),
                    "device_name": item.get("device_name", ""),
                    "applicant": item.get("applicant", ""),
                    "decision": item.get("decision", ""),
                    "decision_date": item.get("decision_date", "")[:10],
                    "product_code": item.get("product_code", ""),
                }
            )

        recalls = self._get(
            "https://api.fda.gov/device/recall.json",
            json_r=True,
            params={"search": f'product_description:"{self.query}"', "limit": 10},
        )
        for item in (recalls or {}).get("results", []):
            self.results["fda_recalls"].append(
                {
                    "recall_number": item.get("recall_number", ""),
                    "recall_class": item.get("recall_class", ""),
                    "firm": item.get("recalling_firm", ""),
                    "date": item.get("event_date_initiated", "")[:10],
                    "reason": item.get("reason_for_recall", ""),
                }
            )

        classif = self._get(
            "https://api.fda.gov/device/classification.json",
            json_r=True,
            params={"search": f'device_name:"{self.query}"', "limit": 8},
        )
        for item in (classif or {}).get("results", []):
            self.results["fda_classification"].append(
                {
                    "device_name": item.get("device_name", ""),
                    "product_code": item.get("product_code", ""),
                    "device_class": item.get("device_class", ""),
                    "regulation_number": item.get("regulation_number", ""),
                    "medical_specialty": item.get("medical_specialty", ""),
                }
            )

    def fetch_clinical_trials(self):
        data = self._get(
            "https://clinicaltrials.gov/api/v2/studies",
            json_r=True,
            params={"query.term": self.query, "pageSize": 10},
        )
        for study in (data or {}).get("studies", []):
            protocol = study.get("protocolSection", {})
            ident = protocol.get("identificationModule", {})
            status = protocol.get("statusModule", {})
            design = protocol.get("designModule", {})
            cond = protocol.get("conditionsModule", {})
            self.results["clinical_trials"].append(
                {
                    "nct_id": ident.get("nctId", ""),
                    "title": ident.get("briefTitle", ""),
                    "status": status.get("overallStatus", ""),
                    "phase": ", ".join(design.get("phases", [])),
                    "enrollment": str(design.get("enrollmentInfo", {}).get("count", "")),
                    "conditions": ", ".join(cond.get("conditions", [])[:4]),
                    "url": f"https://clinicaltrials.gov/study/{ident.get('nctId', '')}",
                }
            )

    def fetch_europe_pmc(self):
        data = self._get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json_r=True,
            params={
                "query": self.query,
                "resultType": "lite",
                "pageSize": 10,
                "format": "json",
                "sort": "CITED desc",
            },
        )
        for item in (data or {}).get("resultList", {}).get("result", []):
            self.results["europe_pmc"].append(
                {
                    "title": item.get("title", ""),
                    "year": str(item.get("pubYear", "")),
                    "journal": item.get("journalTitle", ""),
                    "authors": item.get("authorString", ""),
                    "doi": item.get("doi", ""),
                    "cited": str(item.get("citedByCount", "")),
                }
            )

    def fetch_semantic_scholar(self):
        data = self._get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            json_r=True,
            params={
                "query": self.query,
                "limit": 10,
                "fields": "title,year,authors,citationCount,externalIds,venue",
            },
        )
        for item in (data or {}).get("data", []):
            self.results["semantic_scholar"].append(
                {
                    "title": item.get("title", ""),
                    "year": str(item.get("year", "")),
                    "venue": item.get("venue", ""),
                    "authors": ", ".join(a.get("name", "") for a in item.get("authors", [])[:4]),
                    "cited": str(item.get("citationCount", "")),
                    "doi": item.get("externalIds", {}).get("DOI", ""),
                }
            )

    def fetch_google_patents(self):
        response = self._get(
            f"https://patents.google.com/xhr/query?url=q%3D{self.q}%26num%3D10&exp=&tags="
        )
        if not response:
            return
        try:
            data = response.json()
        except Exception:
            return

        for cluster in data.get("results", {}).get("cluster", [])[:3]:
            for item in cluster.get("result", [])[:5]:
                patent = item.get("patent", {})
                title = patent.get("title", "")
                pub = patent.get("publication_number", "")
                if not title and not pub:
                    continue
                assignees = patent.get("assignee", [])
                assignees = [a for a in assignees if isinstance(a, str) and a.strip()]
                self.results["google_patents"].append(
                    {
                        "publication": pub,
                        "title": title,
                        "assignee": ", ".join(assignees[:2]),
                        "date": patent.get("publication_date", ""),
                        "url": f"https://patents.google.com/patent/{pub}" if pub else "",
                    }
                )

    def fetch_wipo(self):
        response = self._get(
            "https://patentscope.wipo.int/search/en/result.jsf",
            params={"query": self.query, "maxRec": "10", "sortOption": "Relevance"},
        )
        if not response:
            return

        soup = BeautifulSoup(response.text, "lxml")
        for row in soup.select(".ps-patent-result,.resultrow")[:8]:
            title_el = row.select_one(".ps-patent-result--title,.title a,.pdfLink")
            number_el = row.select_one(".ps-patent-result--patent-number,.patentNumber")
            date_el = row.select_one(".ps-patent-result--date,.pubDate")
            if title_el:
                self.results["wipo"].append(
                    {
                        "title": title_el.get_text(strip=True),
                        "number": number_el.get_text(strip=True) if number_el else "",
                        "date": date_el.get_text(strip=True) if date_el else "",
                    }
                )

    def fetch_ema(self):
        response = self._get(
            "https://www.ema.europa.eu/en/search",
            params={"search_api_fulltext": self.query},
        )
        if not response:
            return

        soup = BeautifulSoup(response.text, "lxml")
        for el in soup.select(".ecl-content-item__title a,.search-result-title a")[:8]:
            title = el.get_text(strip=True)
            href = el.get("href", "")
            if not title:
                continue
            if href and not href.startswith("http"):
                href = "https://www.ema.europa.eu" + href
            self.results["ema"].append({"title": title, "url": href})

    def run_all(self):
        fetchers = [
            self.fetch_pubmed,
            self.fetch_fda,
            self.fetch_clinical_trials,
            self.fetch_europe_pmc,
            self.fetch_semantic_scholar,
            self.fetch_google_patents,
            self.fetch_wipo,
            self.fetch_ema,
        ]
        print(f"\nResearch query: {self.query}")
        for fetcher in fetchers:
            name = fetcher.__name__.replace("fetch_", "")
            print(f"  Fetching {name}...")
            try:
                fetcher()
            except Exception as exc:
                self.results["errors"].append({"source": name, "message": str(exc)})
            time.sleep(DELAY)
        print(f"Retrieved {self.total_count()} records.\n")
        return self.results

    def total_count(self):
        return sum(len(v) for k, v in self.results.items() if isinstance(v, list) and k != "errors")

    def counts(self):
        return {
            "PubMed": len(self.results["pubmed"]),
            "FDA 510(k)": len(self.results["fda_510k"]),
            "FDA Recalls": len(self.results["fda_recalls"]),
            "FDA Class": len(self.results["fda_classification"]),
            "CT.gov": len(self.results["clinical_trials"]),
            "Europe PMC": len(self.results["europe_pmc"]),
            "S2": len(self.results["semantic_scholar"]),
            "GPatents": len(self.results["google_patents"]),
            "WIPO": len(self.results["wipo"]),
            "EMA": len(self.results["ema"]),
        }

    def evidence_rows(self):
        rows = []
        for p in self.results["pubmed"][:8]:
            rows.append(["PubMed", p["year"], trunc(p["title"], 70), p["pmid"], "Retrieved"])
        for p in self.results["europe_pmc"][:6]:
            rows.append(["Europe PMC", p["year"], trunc(p["title"], 70), p.get("doi", ""), "Retrieved"])
        for p in self.results["semantic_scholar"][:6]:
            rows.append(["Semantic Scholar", p["year"], trunc(p["title"], 70), p.get("doi", ""), "Retrieved"])
        return rows

    def known_unknowns(self):
        unknowns = []
        if not self.results["fda_510k"]:
            unknowns.append("No FDA 510(k) predicates were retrieved for the exact query. Perform manual predicate search by product code, material, and intended use.")
        if not self.results["fda_classification"]:
            unknowns.append("No FDA classification record was retrieved for the exact query. Confirm product code and regulation number manually.")
        if not self.results["clinical_trials"]:
            unknowns.append("No ClinicalTrials.gov studies were retrieved for the exact query. This does not prove no clinical evidence exists.")
        if not self.results["google_patents"] and not self.results["wipo"]:
            unknowns.append("No live patent records were retrieved. Manual USPTO/EPO/WIPO/FTO review remains mandatory.")
        if self.results["errors"]:
            unknowns.append("One or more source queries failed or returned errors. See source error section.")
        return unknowns


def cover_page(story, intake, engine):
    title = intake.get("device_name", "Surgical Suture Device")
    subtitle = "Evidence-cautious Design History File draft"

    hero = Table(
        [[Paragraph(safe(title), ST["cover_title"]), Paragraph(safe(subtitle), ST["cover_sub"])]],
        colWidths=[CONTENT_W],
    )
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
                ("TOPPADDING", (0, 0), (-1, -1), 28),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 28),
            ]
        )
    )

    meta = kv_table(
        [
            ("Document Type", "DHF draft for surgical suture device"),
            ("Generated", TODAY),
            ("Model Number", intake.get("model_number", "TBD")),
            ("Manufacturer", intake.get("manufacturer", "TBD")),
            ("Intended Use", intake.get("intended_use", "TBD")),
            ("Material", intake.get("material", "TBD")),
            ("Suture Type", intake.get("suture_type", "TBD")),
            ("USP Size Range", intake.get("size_range", "TBD")),
            ("Target Markets", ", ".join(intake.get("target_markets", [])) or "TBD"),
            ("Live Records Retrieved", str(engine.total_count())),
            ("Evidence Position", "Retrieved facts are separated from reference checklists and SME-confirmation items."),
        ]
    )

    story.extend(
        [
            sp(30),
            hero,
            sp(16),
            notice(
                "This document is a draft aid. It must not be used as a regulatory submission, clinical claim, market claim, "
                "or freedom-to-operate opinion without qualified review. Numeric acceptance criteria are marked for verification "
                "against current official standards and internal test reports.",
                accent=C_WARN,
                bg=C_WARN_BG,
            ),
            sp(14),
            meta,
            PageBreak(),
        ]
    )


def toc_page(story):
    sections = [
        ("1", "Evidence Boundary & Retrieval Summary", "sec1"),
        ("2", "Device Profile", "sec2"),
        ("3", "Design Inputs", "sec3"),
        ("4", "Verification Plan", "sec4"),
        ("5", "Risk Management", "sec5"),
        ("6", "Clinical & Literature Evidence", "sec6"),
        ("7", "FDA and Regulatory Evidence", "sec7"),
        ("8", "Patent Landscape", "sec8"),
        ("9", "Materials Reference", "sec9"),
        ("10", "Competitor Intelligence", "sec10"),
        ("11", "Traceability Matrix", "sec11"),
        ("A", "Standards Checklist", "seca"),
        ("B", "Known Unknowns & Source Errors", "secb"),
    ]
    story.extend([Bookmark("toc", "Table of Contents"), Paragraph("Table of Contents", ST["h1"]), hr()])
    rows = []
    for num, title, key in sections:
        rows.append([num, f'<link href="#{key}">{safe(title)}</link>'])
    story.append(grid(["Section", "Title"], rows, widths=[2 * cm, CONTENT_W - 2 * cm]))
    story.append(PageBreak())


def sec_retrieval(story, engine):
    sec(story, 1, "Evidence Boundary & Retrieval Summary", "sec1", "What is known, what is retrieved, and what needs confirmation")
    story.extend(
        [
            notice(
                "Anti-hallucination rule used by this script: only live database records are presented as retrieved evidence. "
                "Reference tables are labeled as checklists. Numeric claims and regulatory classifications are marked for confirmation unless directly retrieved.",
                accent=C_TEAL,
                bg=HexColor("#ECFDF5"),
            ),
            sp(8),
            Paragraph("1.1 Source Retrieval Counts", ST["h2"]),
            KeepTogether([BarChart(engine.counts(), CONTENT_W, 155), Paragraph("Figure 1.1 - Records retrieved by source.", ST["caption"])]),
            sp(8),
            grid(
                ["Source", "Records", "Evidence Use", "Limitation"],
                [
                    ["PubMed", len(engine.results["pubmed"]), "Peer-reviewed biomedical literature", "Query may miss papers using different terms"],
                    ["FDA 510(k)", len(engine.results["fda_510k"]), "Potential predicate devices", "Exact query only; manual product-code search required"],
                    ["FDA Recalls", len(engine.results["fda_recalls"]), "Known recall signals", "Absence of results is not proof of no recalls"],
                    ["FDA Classification", len(engine.results["fda_classification"]), "Product code/class clues", "Exact query only"],
                    ["ClinicalTrials.gov", len(engine.results["clinical_trials"]), "Clinical study records", "Device names may differ from generic terms"],
                    ["Europe PMC", len(engine.results["europe_pmc"]), "Literature and citation context", "Citation count is not evidence quality"],
                    ["Semantic Scholar", len(engine.results["semantic_scholar"]), "Literature discovery", "Metadata may be incomplete"],
                    ["Google Patents", len(engine.results["google_patents"]), "Prior-art discovery", "Not a legal FTO search"],
                    ["WIPO", len(engine.results["wipo"]), "PCT patent discovery", "Scraped results may be incomplete"],
                    ["EMA", len(engine.results["ema"]), "EU regulatory resource discovery", "May not return device-specific documents"],
                ],
                widths=[3.2 * cm, 1.5 * cm, 5.3 * cm, CONTENT_W - 10 * cm],
                small=True,
            ),
            PageBreak(),
        ]
    )


def sec_device(story, intake):
    sec(story, 2, "Device Profile", "sec2", "Input data supplied by user")
    story.extend(
        [
            Paragraph("2.1 Device Identification", ST["h2"]),
            kv_table(
                [
                    ("Device Name", intake.get("device_name", "TBD")),
                    ("Model Number", intake.get("model_number", "TBD")),
                    ("Manufacturer", intake.get("manufacturer", "TBD")),
                    ("Intended Use", intake.get("intended_use", "TBD")),
                    ("Indications for Use", intake.get("indications_for_use", "TBD")),
                    ("Suture Type", intake.get("suture_type", "TBD")),
                    ("Material", intake.get("material", "TBD")),
                    ("USP Size Range", intake.get("size_range", "TBD")),
                    ("Needle Type", intake.get("needle_type", "TBD")),
                    ("Absorbable", "Yes" if intake.get("absorbable") else "No / TBD"),
                    ("Sterile", "Yes" if intake.get("sterile") else "No / TBD"),
                    ("Patient Contacting", "Yes" if intake.get("patient_contacting") else "No / TBD"),
                    ("FDA Class Claimed in Intake", intake.get("fda_class", "TBD")),
                    ("EU MDR Class Claimed in Intake", intake.get("eu_mdr_class", "TBD")),
                    ("Target Markets", ", ".join(intake.get("target_markets", [])) or "TBD"),
                ]
            ),
            sp(8),
            notice(
                "Classification fields above are user-supplied unless confirmed by FDA/EU source records later in the report.",
                accent=C_WARN,
                bg=C_WARN_BG,
            ),
            PageBreak(),
        ]
    )


def sec_inputs(story, intake):
    sec(story, 3, "Design Inputs", "sec3", "Requirements written as confirmable engineering statements")
    rows = [
        ["DI-001", "Suture diameter", "Within applicable USP/Ph. Eur. size limits", "USP <861> / Ph. Eur.", "Verify current official values"],
        ["DI-002", "Knot-pull tensile strength", "Meets applicable size/material minimum", "USP <881>", "Verify current official values"],
        ["DI-003", "Needle attachment strength", "Meets applicable needle-suture pull requirement", "USP <871>", "Verify current official values"],
        ["DI-004", "Knot security", "No unacceptable slippage under defined knot configuration", "Internal + applicable standards", "Define knot method"],
        ["DI-005", "Biocompatibility", "No unacceptable biological risk for contact type/duration", "ISO 10993 series", "Endpoint matrix required"],
        ["DI-006", "Sterility", "Sterility assurance level justified for sterile labeled product", "ISO 11135 / ISO 11137", "Depends on sterilization method"],
        ["DI-007", "Packaging integrity", "Sterile barrier maintained through shelf life and distribution", "ISO 11607", "Aging and transport validation required"],
        ["DI-008", "Labeling", "Clear material, size, needle, sterility, single-use and warnings", "ISO 15223-1 / FDA UDI", "Market-specific review required"],
        ["DI-009", "Usability", "Surgeon can select, load, pass, knot, and trim device safely", "IEC 62366-1", "Formative/summative validation required"],
    ]
    story.extend(
        [
            Paragraph("3.1 Core Design Inputs", ST["h2"]),
            grid(["ID", "Requirement", "Draft Acceptance Target", "Source", "Anti-Hallucination Note"], rows, small=True),
            sp(8),
            Paragraph("3.2 USP Size Reference Checklist", ST["h2"]),
            grid(
                ["USP Size", "Metric", "Diameter Min mm", "Diameter Max mm", "Tensile Criterion"],
                [[s, m, f"{dmin:.3f}", f"{dmax:.3f}", note] for s, m, dmin, dmax, note in USP_SIZE_TABLE],
                widths=[1.6 * cm, 1.6 * cm, 2.4 * cm, 2.4 * cm, CONTENT_W - 8 * cm],
                small=True,
            ),
            sp(6),
            notice(
                "The table above is a design checklist only. Confirm all numeric limits against the current official USP/Ph. Eur. text and approved internal specifications before use.",
                accent=C_WARN,
                bg=C_WARN_BG,
            ),
            PageBreak(),
        ]
    )


def sec_verification(story):
    sec(story, 4, "Verification Plan", "sec4", "Tests mapped to design inputs")
    rows = [
        ["DV-001", "DI-001", "Diameter measurement", "Laser micrometer or validated equivalent", "Per official size table", "Planned"],
        ["DV-002", "DI-002", "Knot-pull tensile", "Validated tensile tester", "Per official material/size requirement", "Planned"],
        ["DV-003", "DI-003", "Needle attachment pull", "Tensile pull to detachment", "Per applicable requirement", "Planned"],
        ["DV-004", "DI-004", "Knot security", "Defined knot configuration and wet/dry condition", "No unacceptable slip/failure", "Planned"],
        ["DV-005", "DI-005", "Biocompatibility", "ISO 10993 endpoint testing/rationale", "No unacceptable biological risk", "Planned"],
        ["DV-006", "DI-006", "Sterilization validation", "ISO 11135 or ISO 11137", "Validated SAL and residual limits", "Planned"],
        ["DV-007", "DI-007", "Package validation", "Seal strength, leak, aging, transport", "Pass predefined criteria", "Planned"],
        ["DV-008", "DI-008", "Label review", "Regulatory and usability review", "No critical labeling gaps", "Planned"],
        ["DV-009", "DI-009", "Usability validation", "Representative users and simulated use", "Critical tasks successful", "Planned"],
    ]
    story.extend(
        [
            grid(["DV-ID", "DI Ref", "Verification", "Method", "Acceptance Basis", "Status"], rows, small=True),
            sp(8),
            notice(
                "No PASS result is generated by this script. Results should only be marked PASS after controlled test reports are approved.",
                accent=C_WARN,
                bg=C_WARN_BG,
            ),
            PageBreak(),
        ]
    )


def sec_risk(story, engine):
    sec(story, 5, "Risk Management", "sec5", "Baseline hazards plus retrieved recall signals")
    recall_rows = []
    for r in engine.results["fda_recalls"]:
        recall_rows.append(
            [
                r.get("recall_number", ""),
                r.get("recall_class", ""),
                r.get("date", ""),
                trunc(r.get("firm", ""), 30),
                trunc(r.get("reason", ""), 70),
            ]
        )

    story.extend(
        [
            Paragraph("5.1 FDA Recall Signals Retrieved", ST["h2"]),
            grid(["Recall #", "Class", "Date", "Firm", "Reason"], recall_rows, small=True)
            if recall_rows
            else notice("No FDA recall records were retrieved for the exact query. This does not prove that no relevant recalls exist.", accent=C_WARN, bg=C_WARN_BG),
            sp(8),
            Paragraph("5.2 Baseline Suture Hazard Checklist", ST["h2"]),
            grid(
                ["Category", "Hazard", "Possible Cause", "Potential Harm", "Risk Control"],
                BASELINE_HAZARDS,
                widths=[2.2 * cm, 3.0 * cm, 4.0 * cm, 3.6 * cm, CONTENT_W - 12.8 * cm],
                small=True,
            ),
            sp(8),
            notice(
                "Severity, probability, detectability, residual risk, and benefit-risk acceptability are intentionally not auto-filled. They require product-specific data and risk-team approval.",
                accent=C_TEAL,
                bg=HexColor("#ECFDF5"),
            ),
            PageBreak(),
        ]
    )


def sec_clinical(story, engine):
    sec(story, 6, "Clinical & Literature Evidence", "sec6", "Retrieved literature only")
    rows = engine.evidence_rows()
    story.extend(
        [
            Paragraph("6.1 Retrieved Literature", ST["h2"]),
            grid(["Source", "Year", "Title", "Identifier", "Status"], rows, small=True)
            if rows
            else notice("No literature records were retrieved for the exact query.", accent=C_WARN, bg=C_WARN_BG),
            sp(8),
            Paragraph("6.2 ClinicalTrials.gov Records", ST["h2"]),
            grid(
                ["NCT ID", "Title", "Status", "Phase", "Enrollment", "Conditions"],
                [
                    [
                        t.get("nct_id", ""),
                        trunc(t.get("title", ""), 60),
                        t.get("status", ""),
                        t.get("phase", ""),
                        t.get("enrollment", ""),
                        trunc(t.get("conditions", ""), 45),
                    ]
                    for t in engine.results["clinical_trials"]
                ],
                small=True,
            )
            if engine.results["clinical_trials"]
            else notice("No ClinicalTrials.gov records were retrieved for the exact query.", accent=C_WARN, bg=C_WARN_BG),
            sp(8),
            notice(
                "This section does not infer safety or effectiveness. It lists retrieved records for SME review and clinical evaluation planning.",
                accent=C_TEAL,
                bg=HexColor("#ECFDF5"),
            ),
            PageBreak(),
        ]
    )


def sec_fda(story, engine):
    sec(story, 7, "FDA and Regulatory Evidence", "sec7", "Retrieved FDA records only")
    story.extend(
        [
            Paragraph("7.1 FDA 510(k) Records", ST["h2"]),
            grid(
                ["K Number", "Device", "Applicant", "Decision", "Date", "Code"],
                [
                    [
                        p.get("k_number", ""),
                        trunc(p.get("device_name", ""), 45),
                        trunc(p.get("applicant", ""), 30),
                        p.get("decision", ""),
                        p.get("decision_date", ""),
                        p.get("product_code", ""),
                    ]
                    for p in engine.results["fda_510k"]
                ],
                small=True,
            )
            if engine.results["fda_510k"]
            else notice("No FDA 510(k) records were retrieved for the exact query.", accent=C_WARN, bg=C_WARN_BG),
            sp(8),
            Paragraph("7.2 FDA Classification Records", ST["h2"]),
            grid(
                ["Device Name", "Product Code", "Class", "Regulation", "Specialty"],
                [
                    [
                        trunc(c.get("device_name", ""), 45),
                        c.get("product_code", ""),
                        c.get("device_class", ""),
                        c.get("regulation_number", ""),
                        c.get("medical_specialty", ""),
                    ]
                    for c in engine.results["fda_classification"]
                ],
                small=True,
            )
            if engine.results["fda_classification"]
            else notice("No FDA classification records were retrieved for the exact query.", accent=C_WARN, bg=C_WARN_BG),
            sp(8),
            notice(
                "Do not treat missing FDA search results as regulatory clearance or absence of predicates. Manual FDA search by product code, regulation number, material, and intended use is required.",
                accent=C_WARN,
                bg=C_WARN_BG,
            ),
            PageBreak(),
        ]
    )


def sec_patents(story, engine):
    sec(story, 8, "Patent Landscape", "sec8", "Discovery only, not FTO")
    patent_rows = []
    for p in engine.results["google_patents"]:
        patent_rows.append(["Google Patents", p.get("publication", ""), trunc(p.get("title", ""), 60), trunc(p.get("assignee", ""), 35), p.get("date", "")])
    for p in engine.results["wipo"]:
        patent_rows.append(["WIPO", p.get("number", ""), trunc(p.get("title", ""), 60), "", p.get("date", "")])

    story.extend(
        [
            grid(["Source", "Publication", "Title", "Assignee", "Date"], patent_rows, small=True)
            if patent_rows
            else notice("No patent records were retrieved for the exact query.", accent=C_WARN, bg=C_WARN_BG),
            sp(8),
            notice(
                "Patent results are discovery leads only. They are not a freedom-to-operate opinion, validity opinion, or infringement analysis. Qualified patent counsel must review claims, family status, jurisdictions, expiry, and design-around options.",
                accent=C_WARN,
                bg=C_WARN_BG,
            ),
            PageBreak(),
        ]
    )


def sec_materials(story):
    sec(story, 9, "Materials Reference", "sec9", "Checklist, not confirmed product claims")
    story.extend(
        [
            grid(
                ["Material", "Class", "Structure", "Design Notes"],
                MATERIAL_REFERENCE,
                widths=[3.5 * cm, 3.0 * cm, 2.4 * cm, CONTENT_W - 8.9 * cm],
                small=True,
            ),
            sp(8),
            notice(
                "Material properties vary by supplier, molecular weight, processing, coating, sterilization, and storage. Use supplier CoA, internal testing, predicate IFU, and current standards before making claims.",
                accent=C_WARN,
                bg=C_WARN_BG,
            ),
            PageBreak(),
        ]
    )


def sec_competitors(story):
    sec(story, 10, "Competitor Intelligence", "sec10", "Non-quantitative unless independently sourced")
    rows = [
        ["Ethicon / J&J MedTech", "Vicryl, PDS, Prolene, Stratafix", "Broad global portfolio; antimicrobial and barbed variants exist in market", "Confirm SKUs and claims from current IFU/labeling"],
        ["Medtronic / Covidien", "Polysorb, Maxon, Surgipro, V-Loc", "Broad global portfolio; knotless/barbed products exist in market", "Confirm current ownership and SKU availability"],
        ["B. Braun / Aesculap", "Safil, Monosyn, MonoPlus, Optilene", "Established EU/global suture supplier", "Confirm market availability by country"],
        ["Mani", "Sutures and surgical needles", "Known for needle/instrument manufacturing", "Confirm exact suture portfolio by market"],
        ["Healthium / Sutures India", "Trusynth, Truglyde, Truprolene", "Emerging-market and international supplier", "Confirm regulatory status by SKU"],
        ["Peters Surgical", "Suture portfolio varies by region", "European surgical device company", "Confirm current brands and indications"],
        ["Demetech", "Suture portfolio varies", "US-based suture supplier", "Confirm current regulatory status"],
    ]
    story.extend(
        [
            grid(["Company", "Example Brands", "Non-Quantitative Observation", "Confirmation Needed"], rows, small=True),
            sp(8),
            notice(
                "This script intentionally removes market-share percentages and revenue claims. Add them only from cited analyst reports, annual reports, or verified market research.",
                accent=C_TEAL,
                bg=HexColor("#ECFDF5"),
            ),
            PageBreak(),
        ]
    )


def sec_traceability(story):
    sec(story, 11, "Traceability Matrix", "sec11", "Draft links from needs to verification")
    rows = [
        ["UN-001", "Provide tissue approximation support", "DI-001/002/004", "DV-001/002/004", "Mechanical failure hazards"],
        ["UN-002", "Remain biologically acceptable", "DI-005", "DV-005", "Biological hazards"],
        ["UN-003", "Remain sterile until use", "DI-006/007", "DV-006/007", "Sterility and packaging hazards"],
        ["UN-004", "Support safe surgical handling", "DI-003/009", "DV-003/009", "Needle and use-related hazards"],
        ["UN-005", "Carry clear labeling", "DI-008", "DV-008", "Wrong selection / misuse hazards"],
    ]
    story.extend([grid(["User Need", "Statement", "Design Inputs", "Verification", "Risk Link"], rows, small=True), PageBreak()])


def sec_standards(story):
    sec(story, "A", "Standards Checklist", "seca", "Confirm editions before use")
    story.extend(
        [
            grid(
                ["Standard", "Scope", "Use Note"],
                STANDARD_CHECKLIST,
                widths=[4.2 * cm, 5.0 * cm, CONTENT_W - 9.2 * cm],
                small=True,
            ),
            sp(8),
            notice(
                "Always confirm current editions, recognized consensus status, transition dates, and market-specific requirements before submission.",
                accent=C_WARN,
                bg=C_WARN_BG,
            ),
            PageBreak(),
        ]
    )


def sec_unknowns(story, engine):
    sec(story, "B", "Known Unknowns & Source Errors", "secb", "Items requiring follow-up")
    unknowns = engine.known_unknowns()
    rows = [[f"KU-{i+1:03d}", u] for i, u in enumerate(unknowns)] or [["KU-000", "No major retrieval gaps detected by the script. Manual review is still required."]]

    error_rows = []
    for e in engine.results.get("errors", [])[:20]:
        error_rows.append([e.get("source", ""), e.get("status", ""), trunc(e.get("url", ""), 55), trunc(e.get("message", ""), 90)])

    story.extend(
        [
            Paragraph("B.1 Known Unknowns", ST["h2"]),
            grid(["ID", "Follow-up Item"], rows, widths=[2 * cm, CONTENT_W - 2 * cm]),
            sp(8),
            Paragraph("B.2 Source Errors", ST["h2"]),
            grid(["Source", "Status", "URL", "Message"], error_rows, small=True)
            if error_rows
            else para("No source errors recorded."),
            sp(8),
            notice(
                "Recommended next step: manually verify predicates, classification, standards editions, material claims, and acceptance criteria before using this DHF draft for design review.",
                accent=C_TEAL,
                bg=HexColor("#ECFDF5"),
            ),
        ]
    )


def build_pdf(intake, engine, output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=f"DHF Draft - {intake.get('device_name', 'Suture Device')}",
        author="dhf_suture.py",
        subject="Evidence-cautious DHF draft",
    )

    story = []
    cover_page(story, intake, engine)
    toc_page(story)
    sec_retrieval(story, engine)
    sec_device(story, intake)
    sec_inputs(story, intake)
    sec_verification(story)
    sec_risk(story, engine)
    sec_clinical(story, engine)
    sec_fda(story, engine)
    sec_patents(story, engine)
    sec_materials(story)
    sec_competitors(story)
    sec_traceability(story)
    sec_standards(story)
    sec_unknowns(story, engine)

    doc.build(story, onFirstPage=PageDecor(intake), onLaterPages=PageDecor(intake))


def load_intake(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "device_name" not in data:
        raise ValueError("intake.json must include device_name")
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Evidence-cautious DHF Builder for Surgical Sutures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Example intake.json:
            {
              "device_name": "BioMime Absorbable Surgical Suture",
              "model_number": "BM-SUT-001",
              "manufacturer": "BioMime",
              "intended_use": "Approximation of soft tissue",
              "indications_for_use": "General soft tissue approximation and/or ligation",
              "suture_type": "Synthetic absorbable braided",
              "material": "Polyglactin 910",
              "size_range": "6-0 to 2",
              "needle_type": "Taper and reverse-cutting",
              "absorbable": true,
              "sterile": true,
              "patient_contacting": true,
              "fda_class": "II",
              "eu_mdr_class": "IIb",
              "target_markets": ["US", "EU"]
            }
            """
        ),
    )
    parser.add_argument("--intake", required=True)
    parser.add_argument("--out", default="DHF_Suture.pdf")
    parser.add_argument("--cache", default=None)
    parser.add_argument("--cached", action="store_true")
    args = parser.parse_args()

    intake = load_intake(args.intake)
    engine = ResearchEngine(
        intake.get("device_name", "Suture Device"),
        intake.get("intended_use", ""),
        intake.get("fda_class", "II"),
    )

    print("=" * 72)
    print(f"DHF Suture Builder - Evidence-cautious mode")
    print(f"Device: {intake.get('device_name')}")
    print("=" * 72)

    if args.cached and args.cache and Path(args.cache).exists():
        print(f"Loading cached data from {args.cache}")
        engine.results = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    else:
        engine.run_all()
        if args.cache:
            Path(args.cache).write_text(json.dumps(engine.results, indent=2), encoding="utf-8")
            print(f"Cache written: {args.cache}")

    print(f"Building PDF: {args.out}")
    build_pdf(intake, engine, args.out)
    print(f"Done: {args.out}")


if __name__ == "__main__":
    main()

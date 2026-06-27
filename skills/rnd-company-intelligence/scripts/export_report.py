#!/usr/bin/env python3
"""
Generalized ReportLab PDF Generation Engine with Hyperlinked Table of Contents
"""
import json
import os
import sys
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, Image, KeepTogether
)
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas as _cv

class NumberedCanvas(_cv.Canvas):
    """Two-pass canvas to dynamically compute and render total page counts in footers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(total)
            super().showPage()
        super().save()

    def draw_footer(self, total):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(HexColor("#666666"))
        
        doc = getattr(self, '_doctemplate', None)
        footer_text = getattr(doc, 'footer_text', "Corporate R&D Research Report")
        
        self.drawString(2 * cm, 1.0 * cm, footer_text)
        self.drawRightString(19 * cm, 1.0 * cm, f"Page {self._pageNumber} of {total}")
        
        self.setStrokeColor(HexColor("#808080"))
        self.line(2 * cm, 1.3 * cm, 19 * cm, 1.3 * cm)
        self.restoreState()


class DocumentEngine:
    def __init__(self, theme_colors=None):
        colors_config = theme_colors or {}
        self.NAVY = HexColor(colors_config.get("primary", "#1A2E4F"))
        self.AZURE = HexColor(colors_config.get("secondary", "#1F4E79"))
        self.MID = HexColor(colors_config.get("accent", "#2E75B6"))
        self.SHADE = HexColor(colors_config.get("neutral_light", "#F2F2F2"))
        self.RULE = HexColor(colors_config.get("border", "#808080"))
        self.WHITE = colors.white

        self.CONTENT_W = 17.5 * cm
        self.styles = getSampleStyleSheet()
        self._init_styles()

    def _init_styles(self):
        self.H1 = ParagraphStyle("H1", parent=self.styles["Title"], fontName="Helvetica-Bold", 
                                 fontSize=22, textColor=self.NAVY, alignment=TA_LEFT, spaceAfter=8)
        self.H2 = ParagraphStyle("H2", parent=self.styles["Heading2"], fontName="Helvetica-Bold", 
                                 fontSize=15, textColor=self.NAVY, spaceBefore=14, spaceAfter=6)
        self.H3 = ParagraphStyle("H3", parent=self.styles["Heading3"], fontName="Helvetica-Bold", 
                                 fontSize=11, textColor=self.AZURE, spaceBefore=10, spaceAfter=4)
        self.BODY = ParagraphStyle("BODY", parent=self.styles["BodyText"], fontName="Helvetica", 
                                   fontSize=9.5, leading=13.5, alignment=TA_JUSTIFY, spaceAfter=4)
        self.SMALL = ParagraphStyle("SMALL", parent=self.BODY, fontSize=8, leading=10.5, textColor=HexColor("#404040"))
        self.CAP = ParagraphStyle("CAP", parent=self.BODY, fontSize=8, leading=10, alignment=TA_CENTER,
                                  fontName="Helvetica-Oblique", textColor=HexColor("#505050"))
        self.TH = ParagraphStyle("TH", parent=self.BODY, fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=self.WHITE)
        self.TD = ParagraphStyle("TD", parent=self.BODY, fontSize=8.5, leading=11)
        
        # New Style for Clickable Links within Tables/Body
        self.LINK = ParagraphStyle("LINK", parent=self.TD, textColor=self.AZURE)

    def P(self, text, style=None):
        return Paragraph(str(text), style or self.BODY)

    def hr(self):
        return HRFlowable(width="100%", thickness=0.5, color=self.RULE, spaceBefore=2, spaceAfter=6)

    def build_grid(self, headers, rows, widths=None, header_color=None, use_link_style=False):
        h_color = header_color or self.NAVY
        cw = widths or [self.CONTENT_W / len(headers)] * len(headers)
        hrow = [Paragraph(str(h), self.TH) for h in headers]
        
        # Determine the text style to use for cells
        cell_style = self.LINK if use_link_style else self.TD
        brows = [[Paragraph(str(c), cell_style) for c in r] for r in rows]
        
        t = Table([hrow] + brows, colWidths=cw, hAlign="LEFT", repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), h_color),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [self.WHITE, self.SHADE]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, self.RULE),
            ("BOX", (0, 0), (-1, -1), 0.5, h_color),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    def build_info_box(self, title, body, bg=None, border=None):
        bg_color = bg or self.SHADE
        border_color = border or self.AZURE
        inner = [Paragraph(f"<b>{title}</b>", self.H3), Paragraph(body, self.TD)]
        t = Table([[inner]], colWidths=[self.CONTENT_W])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_color),
            ("LINEBEFORE", (0, 0), (0, -1), 3, border_color),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        return t

    def build_quadrant_cell(self, label, items, bg_color):
        inner = [Paragraph(f"<b>{label}</b>", self.TH)]
        inner += [Paragraph(f"• {it}", self.TD) for it in items]
        t = Table([[inner]], colWidths=[8.6 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg_color),
            ("BOX", (0, 0), (-1, -1), 0.5, self.NAVY),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return t

    def build_quadrant_grid(self, quadrants):
        cells = []
        for q in quadrants:
            cells.append(self.build_quadrant_cell(q["title"], q["items"], HexColor(q["bg_color"])))
        
        matrix_data = [[cells[0], cells[1]], [cells[2], cells[3]]]
        t = Table(matrix_data, colWidths=[8.7 * cm, 8.7 * cm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return t

    def build_chart_box(self, charts_dir, filename, caption, w=15 * cm, h=10 * cm):
        path = os.path.join(charts_dir, filename)
        if not os.path.exists(path):
            return self.P(f"[Chart missing: {filename}]", self.SMALL)
        return KeepTogether([
            Image(path, width=w, height=h, hAlign="CENTER"),
            Spacer(1, 2),
            self.P(caption, self.CAP),
            Spacer(1, 6),
        ])

    def generate_pdf(self, config, output_path):
        story = []
        charts_dir = config.get("charts_directory", "")

        # 1. Cover Page Construction
        cover = config.get("cover_page", {})
        story += [
            Spacer(1, 3.2 * cm),
            self.P(cover.get("organization", "ORGANIZATION"), self.H3),
            self.P(cover.get("title", "REPORT TITLE"), self.H1),
            Spacer(1, 6),
            self.P(cover.get("subtitle", ""), self.H2),
            Spacer(1, 0.5 * cm),
            self.hr(),
            Spacer(1, 0.2 * cm),
        ]
        
        meta_grid = cover.get("metadata", [])
        if meta_grid:
            story += [self.build_grid(["Metadata Field", "Value"], meta_grid, widths=[4.5 * cm, 13 * cm])]
        
        notice = cover.get("notice_box")
        if notice:
            story += [Spacer(1, 1.5 * cm), self.build_info_box(
                notice.get("title", "Note"), 
                notice.get("body", ""), 
                bg=HexColor(notice.get("bg", "#FFF8E1")), 
                border=HexColor(notice.get("border", "#B58900"))
            )]
        story += [PageBreak()]

        # 2. Automated Hyperlinked Table of Contents Construction
        sections = config.get("sections", [])
        if config.get("include_toc", True):
            story += [self.P("Table of Contents", self.H2), self.hr()]
            toc_rows = []
            for idx, s in enumerate(sections, 1):
                anchor = f"sec_{idx}"
                # Using <u> tag for a traditional link aesthetic; <a href="#anchor"> maps the target destination
                link_num = f'<a href="#{anchor}"><b>{idx}</b></a>'
                link_title = f'<a href="#{anchor}">{s.get("title", "")}</a>'
                link_page = f'<a href="#{anchor}">↳ Go to page</a>'
                toc_rows.append([link_num, link_title, link_page])
                
            story += [self.build_grid(["#", "Section Name", "Link"], toc_rows, widths=[1 * cm, 13.5 * cm, 3 * cm], use_link_style=True)]
            story += [PageBreak()]

        # 3. Dynamic Section Layout Processing
        for s_idx, sec in enumerate(sections, 1):
            anchor = f"sec_{s_idx}"
            # Embed the destination anchor tags inline with the Section Headings
            story += [self.P(f'<a name="{anchor}"/>{s_idx}. {sec.get("title")}', self.H2), self.hr()]
            
            for element in sec.get("elements", []):
                e_type = element.get("type")
                
                if e_type == "paragraph":
                    story += [self.P(element.get("text"))]
                elif e_type == "heading":
                    level = element.get("level", 3)
                    style = self.H2 if level == 2 else self.H3
                    story += [self.P(element.get("text"), style)]
                elif e_type == "grid":
                    story += [self.build_grid(
                        element.get("headers", []), 
                        element.get("rows", []), 
                        widths=[w * cm for w in element.get("widths", [])] or None
                    )]
                elif e_type == "info_box":
                    story += [self.build_info_box(element.get("title", ""), element.get("body", ""))]
                elif e_type == "quadrant_matrix":
                    story += [self.build_quadrant_grid(element.get("quadrants", []))]
                elif e_type == "chart":
                    story += [self.build_chart_box(
                        charts_dir,
                        element.get("filename"),
                        element.get("caption"),
                        w=element.get("width_cm", 15) * cm,
                        h=element.get("height_cm", 10) * cm
                    )]
                elif e_type == "spacer":
                    story += [Spacer(1, element.get("height_pt", 6))]
                elif e_type == "page_break":
                    story += [PageBreak()]
            
            if sec.get("break_after", True) and s_idx < len(sections):
                story += [PageBreak()]

        # Build Document
        doc = SimpleDocTemplate(
            output_path, 
            pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm,
            title=config.get("document_title", "Corporate Report"),
            author=config.get("document_author", "R&D Engine")
        )
        doc.footer_text = config.get("footer_text", "Internal Corporate Report Blueprint")
        doc.build(story, canvasmaker=NumberedCanvas)


if __name__ == "__main__":
    example_report_payload = {
        "document_title": "Project Nova Execution Strategy",
        "document_author": "Global Core R&D Operations",
        "footer_text": "Confidential • Project Nova Operations Framework",
        "charts_directory": "/tmp/charts",
        "include_toc": True,
        "cover_page": {
            "organization": "NOVA MEDICAL SYSTEMS INC",
            "title": "EXECUTIVE MANAGEMENT STRATEGY DOCUMENT",
            "subtitle": "Phased Integration Matrix of Bio-compatible Structures",
            "metadata": [
                ["Generation Date", date.today().isoformat()],
                ["Classification", "Restricted Corporate Asset"],
                ["Strategic Domain", "Surgical Systems Manufacturing Validation"]
            ],
            "notice_box": {
                "title": "Strategic Implementation Constraint Notice",
                "body": "This document isolates target data models utilizing open pipeline definitions.",
                "bg": "#FFF8E1",
                "border": "#B58900"
            }
        },
        "sections": [
            {
                "title": "Executive Context Outline",
                "break_after": True,
                "elements": [
                    {"type": "paragraph", "text": "This text block showcases the generalized rendering blueprint capabilities. The Table of Contents links are now dynamically mapped using internal anchors."}
                ]
            },
            {
                "title": "Analytical Risk Profiles",
                "break_after": False,
                "elements": [
                    {"type": "paragraph", "text": "This section represents page two. Clicking the TOC item directly scrolls the viewport context down to this page."}
                ]
            }
        ]
    }

    output_target = os.path.expanduser("~/Downloads/Generalized_Corporate_Report.pdf")
    engine = DocumentEngine(theme_colors={"primary": "#1A2E4F", "secondary": "#1F4E79"})
    engine.generate_pdf(example_report_payload, output_target)
    print(f"Report generation finalized with cross-linked TOC references: {output_target}")

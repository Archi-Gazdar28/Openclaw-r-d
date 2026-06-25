#!/usr/bin/env python3
"""
diagrams.py — Professional SVG diagram generators matching corporate styling
=============================================================================
Style reference:
  Box fill:    #DDEAF6  stroke: #1F4E79
  Green fill:  #D6EDDC  stroke: #2E7D32
  Amber fill:  #FFF3CD  stroke: #E6980A
  Text:        #37474F
  Footer bg:   #ECEFF1
  Arrow:       #37474F
"""

import os
import math
from pathlib import Path

FONT   = "Arial, Helvetica, sans-serif"
C_BOX  = "#DDEAF6";  C_BOX_S  = "#1F4E79"
C_GRN  = "#D6EDDC";  C_GRN_S  = "#2E7D32"
C_AMB  = "#FFF3CD";  C_AMB_S  = "#E6980A"
C_RED  = "#FDDCDC";  C_RED_S  = "#C0392B"
C_TXT  = "#37474F"
C_FTR  = "#ECEFF1"
C_ARR  = "#37474F"
C_DLN  = "#7986CB"   # dashed purple for V-model traceability

# Color mapping helper based on database identity keys
SOURCE_COLORS = {
    "PubMed": "#E53935", "FDA": "#1D3557", "ClinicalTrials": "#457B9D",
    "Europe PMC": "#2D6A4F", "Semantic Scholar": "#6A1B9A", "CORE": "#E6980A",
    "Google Scholar": "#1A5FA8", "Google Patents": "#2E7D32", "WIPO": "#C0392B", "EMA": "#0E9F8E"
}

def _svg_open(w, h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="{FONT}">\n'
            f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>\n')

def _svg_close(): 
    return "</svg>\n"

def _title(w, y, text, size=15):
    text = str(text).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (f'<text x="{w//2}" y="{y}" font-size="{size}" fill="{C_TXT}" '
            f'text-anchor="middle" font-weight="bold" '
            f'dominant-baseline="middle">{text}</text>\n')

def _footer(w, h, line1, line2="Automated System Traceability Loop — Controlled DHF Record."):
    fh = 50
    y0 = h - fh
    line1 = str(line1).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    line2 = str(line2).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (f'<rect x="0" y="{y0}" width="{w}" height="{fh}" fill="{C_FTR}" stroke="none"/>\n'
            f'<text x="{w//2}" y="{y0+18}" font-size="11" fill="{C_TXT}" '
            f'text-anchor="middle" font-weight="bold" dominant-baseline="middle">{line1}</text>\n'
            f'<text x="{w//2}" y="{y0+36}" font-size="9" fill="{C_TXT}" '
            f'text-anchor="middle" font-weight="normal" dominant-baseline="middle">{line2}</text>\n')

def _box(x, y, w, h, fill, stroke, lines, bold=True, fontsize=11):
    fw = "bold" if bold else "normal"
    s  = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" ry="6" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>\n'
    n  = len(lines)
    lh = fontsize + 4
    start_y = y + h/2 - (n-1)*lh/2
    for i, line in enumerate(lines):
        yy = start_y + i * lh
        line_safe = str(line).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        s += (f'<text x="{x+w//2}" y="{yy}" font-size="{fontsize}" fill="{C_TXT}" '
              f'text-anchor="middle" font-weight="{fw}" dominant-baseline="middle">{line_safe}</text>\n')
    return s

def _arrow(x1, y1, x2, y2, dashed=False, color=None):
    col   = color or C_ARR
    dash  = ' stroke-dasharray="6,3"' if dashed else ""
    dx, dy = x2-x1, y2-y1
    length = math.hypot(dx, dy)
    if length == 0: return ""
    ux, uy = dx/length, dy/length
    px, py = -uy, ux
    sz = 8
    tip = (x2, y2)
    b1  = (x2 - ux*sz + px*sz*0.45, y2 - uy*sz + py*sz*0.45)
    b2  = (x2 - ux*sz - px*sz*0.45, y2 - uy*sz - py*sz*0.45)
    s = (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
         f'stroke="{col}" stroke-width="1.4"{dash}/>\n')
    s += (f'<polygon points="{tip[0]:.1f},{tip[1]:.1f} '
          f'{b1[0]:.1f},{b1[1]:.1f} {b2[0]:.1f},{b2[1]:.1f}" '
          f'fill="{col}" stroke="none"/>\n')
    return s

def _label(x, y, text, fontsize=11, color=None):
    col = color or C_TXT
    text = str(text).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (f'<text x="{x}" y="{y}" font-size="{fontsize}" fill="{col}" '
            f'text-anchor="middle" dominant-baseline="middle">{text}</text>\n')

def gen_vmodel(device_name: str, out_path: str, W=1100, H=550):
    s = _svg_open(W, H)
    s += _title(W, 35, f"Design Control V-Model — {device_name}")
    BW, BH = 220, 55
    PAD = 70
    ys = [95, 190, 285, 380]
    lx, rx = PAD, W - PAD - BW
    
    left_steps = ["User Needs (Clinical Context)", "Design Inputs (Technical Specs)", "System Architecture (BOM Design)", "Detailed Component Blueprint"]
    right_steps = ["Design Validation (Clinical Evaluation)", "System Verification (Full Test)", "Integration Verification (Swage Grip)", "Unit Verification (Raw Material Testing)"]
    
    for i in range(4):
        s += _box(lx, ys[i], BW, BH, C_BOX, C_BOX_S, [left_steps[i]], fontsize=11)
        s += _box(rx, ys[i], BW, BH, C_GRN, C_GRN_S, [right_steps[i]], fontsize=11)
        s += _arrow(lx + BW, ys[i] + BH//2, rx, ys[i] + BH//2, dashed=True, color=C_DLN)
        if i < 3:
            s += _arrow(lx + BW//2, ys[i] + BH, lx + BW//2, ys[i+1], color=C_BOX_S)
            s += _arrow(rx + BW//2, ys[i+1], rx + BW//2, ys[i], color=C_GRN_S)
            
    s += _footer(W, H, f"System Loop Traceability Architecture for {device_name}")
    s += _svg_close()
    Path(out_path).write_text(s, encoding="utf-8")
    return out_path

def gen_risk_matrix(hazards: list, out_path: str, W=650, H=480):
    s = _svg_open(W, H)
    s += _title(W, 30, "System Risk Acceptability Matrix (ISO 14971)")
    
    OFF_X, OFF_Y, CELL = 110, 80, 55
    for ri in range(5):
        s += _label(OFF_X - 35, OFF_Y + ri*CELL + CELL//2, f"Prob Level {5-ri}", fontsize=10)
        for ci in range(5):
            x, y = OFF_X + ci*CELL, OFF_Y + ri*CELL
            fill = C_RED if (4-ri)*ci >= 6 else (C_AMB if (4-ri)*ci >= 3 else C_GRN)
            stroke = C_RED_S if (4-ri)*ci >= 6 else (C_AMB_S if (4-ri)*ci >= 3 else C_GRN_S)
            s += f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" fill="{fill}" stroke="{stroke}" opacity="0.6"/>\n'
            
    for ci in range(5):
        s += _label(OFF_X + ci*CELL + CELL//2, OFF_Y + 5*CELL + 18, f"Sev Class {ci+1}", fontsize=10)

    for h in hazards:
        cx = OFF_X + (int(h.get("sev", 3)) - 1) * CELL + CELL//2
        cy = OFF_Y + (5 - int(h.get("prob", 2))) * CELL + CELL//2
        s += f'<circle cx="{cx}" cy="{cy}" r="9" fill="{C_BOX_S}"/>\n'
        s += f'<text x="{cx}" y="{cy+2.5}" font-size="8" fill="#FFF" text-anchor="middle" font-weight="bold">{h["id"]}</text>\n'

    s += _footer(W, H, "Plotted Operational Defect Matrix (Severity vs Probability)")
    s += _svg_close()
    Path(out_path).write_text(s, encoding="utf-8")
    return out_path

def gen_evidence_chart(counts: dict, out_path: str, W=850, H=420):
    s = _svg_open(W, H)
    s += _title(W, 30, "Live API Document Query Performance Architecture")
    
    PAD_L, PAD_T, BH, GAP = 190, 80, 22, 8
    items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    max_v = max([v for k, v in items] + [1])
    
    for i, (k, v) in enumerate(items):
        y = PAD_T + i * (BH + GAP)
        bw = int(520 * v / max_v) or 5
        bar_color = SOURCE_COLORS.get(k, C_BOX_S)
        s += f'<text x="{PAD_L - 12}" y="{y + BH//2 + 3.5}" font-size="11" font-weight="bold" text-anchor="end" fill="{C_TXT}">{k}</text>\n'
        s += f'<rect x="{PAD_L}" y="{y}" width="{bw}" height="{BH}" fill="{bar_color}" stroke="{C_BOX_S}" fill-opacity="0.75" rx="3"/>\n'
        s += f'<text x="{PAD_L + bw + 8}" y="{y + BH//2 + 3.5}" font-size="10" font-weight="bold" fill="{C_TXT}">{v}</text>\n'
        
    s += _footer(W, H, "Empirical Real-Time Systematic Search Evidence Summary")
    s += _svg_close()
    Path(out_path).write_text(s, encoding="utf-8")
    return out_path

class SectionDiv(flowable_obj := type('Flowable', (object,), {})):
    """Procedural structural class instantiated natively inside the main compiler loop."""
    pass

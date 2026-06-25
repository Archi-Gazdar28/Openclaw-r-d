"""
diagrams.py — Professional SVG diagram generators matching the uploaded style
=============================================================================
Style reference:
  Box fill:    #DDEAF6  stroke: #1F4E79
  Green fill:  #D6EDDC  stroke: #2E7D32
  Amber fill:  #FFF3CD  stroke: #E6980A
  Text:        #37474F
  Footer bg:   #ECEFF1
  Arrow:       #37474F
"""

import os, math

# ── Shared SVG primitives ─────────────────────────────────────────────────
FONT   = "Arial, Helvetica, sans-serif"
C_BOX  = "#DDEAF6";  C_BOX_S  = "#1F4E79"
C_GRN  = "#D6EDDC";  C_GRN_S  = "#2E7D32"
C_AMB  = "#FFF3CD";  C_AMB_S  = "#E6980A"
C_RED  = "#FDDCDC";  C_RED_S  = "#C0392B"
C_PRP  = "#EDE7F6";  C_PRP_S  = "#6A1B9A"
C_TXT  = "#37474F"
C_FTR  = "#ECEFF1"
C_ARR  = "#37474F"
C_DLN  = "#7986CB"   # dashed purple for V-model traceability

def _svg_open(w, h):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="{FONT}">\n'
            f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>\n')

def _svg_close(): return "</svg>\n"

def _title(w, y, text, size=16):
    text = str(text).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (f'<text x="{w//2}" y="{y}" font-size="{size}" fill="{C_TXT}" '
            f'text-anchor="middle" font-weight="bold" '
            f'dominant-baseline="middle">{text}</text>\n')

def _footer(w, h, line1, line2="AI-generated; verify before regulatory use."):
    fh = 50
    y0 = h - fh
    line1 = str(line1).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    line2 = str(line2).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (f'<rect x="0" y="{y0}" width="{w}" height="{fh}" fill="{C_FTR}" stroke="none"/>\n'
            f'<text x="{w//2}" y="{y0+18}" font-size="12" fill="{C_TXT}" '
            f'text-anchor="middle" font-weight="bold" dominant-baseline="middle">{line1}</text>\n'
            f'<text x="{w//2}" y="{y0+36}" font-size="9" fill="{C_TXT}" '
            f'text-anchor="middle" font-weight="normal" dominant-baseline="middle">{line2}</text>\n')

def _box(x, y, w, h, fill, stroke, lines, bold=True, fontsize=12):
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
    # compute arrowhead
    dx, dy = x2-x1, y2-y1
    length = math.hypot(dx, dy)
    if length == 0: return ""
    ux, uy = dx/length, dy/length
    px, py = -uy, ux
    sz = 9
    tip = (x2, y2)
    b1  = (x2 - ux*sz + px*sz*0.45, y2 - uy*sz + py*sz*0.45)
    b2  = (x2 - ux*sz - px*sz*0.45, y2 - uy*sz - py*sz*0.45)
    s = (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
         f'stroke="{col}" stroke-width="1.4"{dash}/>\n')
    s += (f'<polygon points="{tip[0]:.1f},{tip[1]:.1f} '
          f'{b1[0]:.1f},{b1[1]:.1f} {b2[0]:.1f},{b2[1]:.1f}" '
          f'fill="{col}" stroke="none"/>\n')
    return s

def _arrow_dbl(x1, y1, x2, y2, dashed=False, color=None):
    """Double-headed arrow."""
    s  = _arrow(x1, y1, x2, y2, dashed=dashed, color=color)
    s += _arrow(x2, y2, x1, y1, dashed=dashed, color=color)
    return s

def _edge_points(bx, by, bw, bh, side):
    """Return (x,y) of box edge midpoint for a given side: T/B/L/R."""
    cx, cy = bx + bw/2, by + bh/2
    if side == "T": return cx, by
    if side == "B": return cx, by+bh
    if side == "L": return bx, cy
    if side == "R": return bx+bw, cy

def _label(x, y, text, fontsize=11, color=None):
    col = color or C_TXT
    text = str(text).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return (f'<text x="{x}" y="{y}" font-size="{fontsize}" fill="{col}" '
            f'text-anchor="middle" dominant-baseline="middle">{text}</text>\n')

# ══════════════════════════════════════════════════════════════════════════
# 1. V-MODEL  — matches uploaded 01_vmodel.png style exactly
# ══════════════════════════════════════════════════════════════════════════
def gen_vmodel(device_name: str, out_path: str, W=1200, H=800):
    """
    Left (blue): User Needs → Design Inputs → Architecture → Detailed Design
    Right (green): Unit Verification → Integration Verification → System Verification → Validation
    Dashed purple: traceability arrows crossing
    Solid diagonal: V shape lines
    """
    s = _svg_open(W, H)
    s += _title(W, 28, f"Design Control V-Model — {device_name}")

    BW, BH = 200, 55   # box width/height
    PAD = 80           # left/right margin

    # Left column positions (descending)
    left_labels = [
        ["User Needs"],
        ["Design Inputs"],
        ["Architecture"],
        ["Detailed Design"],
    ]
    right_labels = [
        ["Unit", "Verification"],
        ["Integration", "Verification"],
        ["System", "Verification"],
        ["Validation"],
    ]

    # Y positions for 4 rows
    ys = [110, 220, 330, 440]
    lx = PAD               # left col x
    rx = W - PAD - BW      # right col x

    # Draw V-shape backbone lines (solid dark)
    # Left side going down-right to bottom
    mid_x = W // 2
    bot_y  = 580
    # left spine
    for i in range(3):
        x1 = lx + BW; y1 = ys[i] + BH/2
        x2 = lx + BW; y2 = ys[i+1] + BH/2
        # slight diagonal toward centre
        xm = lx + BW + (mid_x - lx - BW) * (i+1)/4
        ym = ys[i+1] + BH/2
        s += f'<line x1="{x1}" y1="{y1}" x2="{lx+BW + (mid_x-lx-BW)*(i)/4}" y2="{ys[i]+BH//2}" stroke="{C_TXT}" stroke-width="1.4"/>\n'

    # Draw V left & right spine as two diagonal lines meeting at bottom
    s += f'<line x1="{lx+BW}" y1="{ys[3]+BH//2}" x2="{mid_x}" y2="{bot_y}" stroke="{C_GRN_S}" stroke-width="2.0"/>\n'
    s += f'<line x1="{rx}" y1="{ys[3]+BH//2}" x2="{mid_x}" y2="{bot_y}" stroke="{C_GRN_S}" stroke-width="2.0"/>\n'
    # Left angled lines
    for i in range(4):
        x1l = lx + BW;           y1l = ys[i] + BH//2
        x2l = lx + BW + (mid_x - lx - BW) * i/3 if i<3 else mid_x
        y2l = ys[i] + BH//2
        if i < 3:
            s += f'<line x1="{lx+BW}" y1="{ys[i]+BH//2}" x2="{lx+BW+(mid_x-lx-BW)*(i+1)//4}" y2="{ys[i+1]+BH//2}" stroke="{C_TXT}" stroke-width="1.4"/>\n'
    # Right angled lines
    for i in range(3):
        s += f'<line x1="{rx}" y1="{ys[i]+BH//2}" x2="{rx-(rx-mid_x)*(i+1)//4}" y2="{ys[i+1]+BH//2}" stroke="{C_TXT}" stroke-width="1.4"/>\n'

    # Dashed traceability arrows (purple, crossing)
    trace_pairs = [(0,0),(1,1),(2,2),(3,3)]  # left[i] → right[i]
    for li, ri in trace_pairs:
        x1 = lx + BW;  y1 = ys[li] + BH//2
        x2 = rx;        y2 = ys[ri] + BH//2
        s += _arrow(x1, y1, x2, y2, dashed=True, color=C_DLN)

    # Left boxes (blue)
    for i, lbls in enumerate(left_labels):
        s += _box(lx, ys[i], BW, BH, C_BOX, C_BOX_S, lbls, fontsize=13)

    # Right boxes (green)
    for i, lbls in enumerate(right_labels):
        s += _box(rx, ys[i], BW, BH, C_GRN, C_GRN_S, lbls, fontsize=13)

    # Bottom label
    s += _label(mid_x, bot_y+30, "Design Transfer & Build", fontsize=12, color=C_GRN_S)

    s += _footer(W, H, f"Figure: Design Control V-Model with Traceability")
    s += _svg_close()
    with open(out_path, "w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# 2. ISO 14971 RISK MANAGEMENT PROCESS — matches uploaded SVG exactly
# ══════════════════════════════════════════════════════════════════════════
def gen_iso14971(out_path: str, W=900, H=750):
    s = _svg_open(W, H)
    s += _title(W, 30, "ISO 14971:2019 Risk Management Process")

    BW, BH = 180, 70

    # Node positions (cx, cy)
    nodes = {
        "ra":  (450, 100,  ["Risk Analysis", "§5"]),
        "re":  (700, 250,  ["Risk Evaluation", "§6"]),
        "rc":  (700, 450,  ["Risk Control", "§7"]),
        "rr":  (450, 580,  ["Evaluation of Overall", "Residual Risk §8"]),
        "rmr": (200, 450,  ["Risk Management", "Report §4.5"]),
        "pp":  (200, 250,  ["Production & Post-Production", "Information §10"]),
    }

    # Draw boxes
    for key, (cx, cy, lbls) in nodes.items():
        s += _box(cx-BW//2, cy-BH//2, BW, BH, C_BOX, C_BOX_S, lbls, fontsize=12)

    # Draw arrows between nodes
    def mid_edge(key, side):
        cx, cy, _ = nodes[key]
        if side=="T": return cx, cy-BH//2
        if side=="B": return cx, cy+BH//2
        if side=="L": return cx-BW//2, cy
        if side=="R": return cx+BW//2, cy

    arrows = [
        ("ra","B","re","T"),   # Risk Analysis → Risk Evaluation (right-down)
        ("re","B","rc","T"),   # Risk Evaluation → Risk Control
        ("rc","B","rr","R"),   # Risk Control → Overall Residual
        ("rr","L","rmr","B"),  # Overall Residual → Risk Mgmt Report
        ("rmr","T","pp","B"),  # Report → Post-Production
        ("pp","R","ra","L"),   # Post-Production → Risk Analysis (feedback)
    ]
    # Custom arrow endpoints for the angled ones
    s += _arrow(*mid_edge("ra","B"), *mid_edge("re","T"))
    s += _arrow(*mid_edge("re","B"), *mid_edge("rc","T"))
    s += _arrow(700, 450+BH//2, 450+BW//2, 580-BH//2)  # rc → rr
    s += _arrow(450-BW//2, 580+BH//2-10, 200+BW//2, 450+BH//2)  # rr → rmr
    s += _arrow(*mid_edge("rmr","T"), *mid_edge("pp","B"))
    s += _arrow(200-BW//2+20, 250-BH//2+10, 450-BW//2, 100-BH//2+10)  # pp → ra

    s += _label(450, 660, "(Risk Management File is the cumulative record of all stages)", fontsize=11)
    s += _footer(W, H, "Figure: Risk Management Process per ISO 14971:2019")
    s += _svg_close()
    with open(out_path, "w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# 3. RISK MATRIX — matches uploaded 09_risk_matrix.png exactly
# ══════════════════════════════════════════════════════════════════════════
def gen_risk_matrix(hazards: list, out_path: str, W=1100, H=900):
    """
    hazards: list of dicts with keys: label, sev(1-5), prob_initial(1-5),
             sev_residual(1-5), prob_residual(1-5)
    """
    s = _svg_open(W, H)
    s += _title(W, 28, "Risk Acceptability Matrix")
    s += _label(W//2, 52, "(Severity × Probability)", fontsize=13)

    # Severity axis label (top)
    s += (f'<text x="{W//2}" y="88" font-size="14" fill="{C_TXT}" text-anchor="middle" '
          f'font-weight="bold">Severity →</text>\n')

    # Probability axis label (rotated, left)
    s += (f'<text transform="rotate(-90,38,480)" x="38" y="480" font-size="14" '
          f'fill="{C_TXT}" text-anchor="middle" font-weight="bold">← Probability</text>\n')

    sev_labels  = ["Negligible","Minor","Serious","Critical","Catastrophic"]
    prob_labels = ["Frequent","Probable","Occasional","Remote","Improbable"]

    # Grid layout
    OFF_X = 140; OFF_Y = 115
    CELL  = 150; GAP = 2

    # Colour map: (row, col) → fill, border
    # From image: green bottom-left → yellow → pink/red top-right
    green  = "#D6EDDC"; green_b  = "#4CAF50"
    yellow = "#FFF9C4"; yellow_b = "#E6980A"
    pink   = "#FDDEDE"; pink_b   = "#E53935"

    def cell_color(r, c):  # r=0 top (Frequent), c=0 left (Negligible)
        score = (4-r+1) * (c+1)  # prob * sev
        if score <= 4:   return green,  green_b
        if score <= 9:   return yellow, yellow_b
        return pink, pink_b

    # Column headers
    for ci, lbl in enumerate(sev_labels):
        x = OFF_X + ci*CELL + CELL//2
        s += _label(x, OFF_Y - 22, lbl, fontsize=13)

    # Row headers + cells
    for ri in range(5):
        # Row label
        y_mid = OFF_Y + ri*CELL + CELL//2
        s += _label(OFF_X - 15, y_mid, prob_labels[ri], fontsize=13)

        for ci in range(5):
            x = OFF_X + ci*CELL
            y = OFF_Y + ri*CELL
            fill, border = cell_color(ri, ci)
            s += (f'<rect x="{x+GAP}" y="{y+GAP}" width="{CELL-GAP*2}" height="{CELL-GAP*2}" '
                  f'rx="4" fill="{fill}" stroke="{border}" stroke-width="1.5"/>\n')

    # Plot hazard dots
    def cell_center(sev1, prob1):
        # sev: 1=Negligible→col0, 5=Catastrophic→col4
        # prob: 1=Improbable→row4, 5=Frequent→row0
        col = sev1 - 1
        row = 5 - prob1
        x = OFF_X + col*CELL + CELL//2
        y = OFF_Y + row*CELL + CELL//2
        return x, y

    for hz in hazards:
        xi, yi = cell_center(hz.get("sev",3), hz.get("prob_initial",3))
        xr, yr = cell_center(hz.get("sev_residual", max(1,hz.get("sev",3)-1)),
                              hz.get("prob_residual", max(1,hz.get("prob_initial",3)-1)))
        # Initial (red)
        s += f'<circle cx="{xi}" cy="{yi}" r="14" fill="#E53935" opacity="0.85"/>\n'
        # Residual (green)
        s += f'<circle cx="{xr}" cy="{yr}" r="14" fill="{C_GRN_S}" opacity="0.85"/>\n'
        # Arrow from initial to residual
        if xi != xr or yi != yr:
            s += _arrow(xi, yi, xr, yr, color="#555555")
        # Label
        lbl = hz.get("label","")
        s += (f'<text x="{xi}" y="{yi}" font-size="9" fill="white" '
              f'text-anchor="middle" dominant-baseline="middle" font-weight="bold">{lbl}</text>\n')

    # Legend
    leg_y = OFF_Y + 5*CELL + 25
    s += f'<circle cx="{OFF_X+40}" cy="{leg_y}" r="12" fill="#E53935" opacity="0.85"/>\n'
    s += _label(OFF_X+100, leg_y, "Initial risk", fontsize=12)
    s += f'<circle cx="{OFF_X+220}" cy="{leg_y}" r="12" fill="{C_GRN_S}" opacity="0.85"/>\n'
    s += _label(OFF_X+320, leg_y, "Residual risk (after controls)", fontsize=12)

    s += _footer(W, H, "Figure: Risk Acceptability Matrix with Plotted Items")
    s += _svg_close()
    with open(out_path, "w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# 4. BIOCOMPATIBILITY FLOW — matches uploaded 02_biocompat_flow.png
# ══════════════════════════════════════════════════════════════════════════
def gen_biocompat_flow(contact_type: str, contact_duration: str, out_path: str, W=1200, H=800):
    s = _svg_open(W, H)
    s += _title(W, 28, "Biocompatibility Evaluation Flow (ISO 10993-1)")

    BW, BH = 260, 80
    # Three top input boxes
    inputs = [
        (170, 90,  ["Identify contact type:", contact_type]),
        (460, 90,  ["Identify contact duration:", contact_duration]),
        (780, 90,  ["Chemical characterisation", "(ISO 10993-18)"]),
    ]
    for x, y, lbls in inputs:
        s += _box(x, y, BW, BH, C_BOX, C_BOX_S, lbls, fontsize=12)

    # Central collection point
    mid_x = W // 2; conv_y = 270
    # Lines from 3 boxes to converge point
    for x, y, _ in inputs:
        cx = x + BW//2
        s += _arrow(cx, y+BH, mid_x, conv_y, color=C_TXT)

    # Middle flow boxes (amber)
    steps = [
        (conv_y + 20,  ["Determine test panel", "from ISO 10993-1 Table A.1"]),
        (conv_y + 170, ["Conduct risk-based", "biological evaluation"]),
        (conv_y + 320, ["Biological Evaluation", "Report (BER)"]),
    ]
    BW2 = 320; by_prev = None
    for y, lbls in steps:
        fill = C_AMB if y < conv_y+300 else C_GRN
        stroke = C_AMB_S if y < conv_y+300 else C_GRN_S
        s += _box(mid_x - BW2//2, y, BW2, BH, fill, stroke, lbls, fontsize=13)
        if by_prev is not None:
            s += _arrow(mid_x, by_prev + BH, mid_x, y)
        by_prev = y

    s += _footer(W, H, "Figure: Biocompatibility Evaluation per ISO 10993-1 (risk-based)")
    s += _svg_close()
    with open(out_path, "w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# 5. IEC 62304 SOFTWARE CLASSIFICATION TREE (new diagram)
# ══════════════════════════════════════════════════════════════════════════
def gen_sw_classification(out_path: str, W=1000, H=750):
    s = _svg_open(W, H)
    s += _title(W, 28, "IEC 62304 Software Safety Classification")

    BW, BH = 300, 65

    # Boxes (cx, cy, labels, fill, stroke)
    boxes = {
        "q1": (500, 100, ["Software present", "in medical device?"],      C_BOX, C_BOX_S),
        "q2": (500, 260, ["Failure could cause", "hazardous situation?"],  C_BOX, C_BOX_S),
        "q3": (500, 420, ["Severity: serious injury", "or death possible?"],C_BOX, C_BOX_S),
        "ca": (180, 580, ["CLASS A", "(No hazard)"],                        C_GRN, C_GRN_S),
        "cb": (500, 580, ["CLASS B", "(Non-serious)"],                      C_AMB, C_AMB_S),
        "cc": (820, 580, ["CLASS C", "(Fatal / Serious)"],                  C_RED, C_RED_S),
    }
    for key,(cx,cy,lbls,fill,stroke) in boxes.items():
        s += _box(cx-BW//2, cy-BH//2, BW, BH, fill, stroke, lbls, fontsize=13)

    def T(key): cx,cy,*_ = boxes[key]; return cx, cy-BH//2
    def B(key): cx,cy,*_ = boxes[key]; return cx, cy+BH//2
    def L(key): cx,cy,*_ = boxes[key]; return cx-BW//2, cy
    def R(key): cx,cy,*_ = boxes[key]; return cx+BW//2, cy

    # Arrows
    s += _arrow(*B("q1"), *T("q2"))
    s += _arrow(*B("q2"), *T("q3"))
    s += _arrow(*B("q3"), *T("cc"))                      # Yes → Class C
    s += _arrow(*L("q2"), *T("ca"))                      # No → Class A
    s += _arrow(*B("q3"), *T("cb"))                      # No (sev) → Class B
    # "No" from q1 (device has no SW) → Class A
    s += _arrow(500-BW//2-20, 100, 180-BW//2+10, 580-BH//2)

    # Labels on arrows
    s += _label(560, 190, "Yes",  fontsize=12, color=C_TXT)
    s += _label(560, 350, "Yes",  fontsize=12, color=C_TXT)
    s += _label(350, 310, "No → Class A", fontsize=11, color=C_GRN_S)
    s += _label(680, 500, "Yes → Class C", fontsize=11, color=C_RED_S)
    s += _label(510, 510, "No → Class B", fontsize=11, color=C_AMB_S)

    s += _footer(W, H, "Figure: IEC 62304:2006+AMD1 Software Safety Classification Tree")
    s += _svg_close()
    with open(out_path, "w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# 6. DESIGN CONTROL TRACEABILITY CHAIN
# ══════════════════════════════════════════════════════════════════════════
def gen_traceability_chain(out_path: str, W=1300, H=320):
    s = _svg_open(W, H)
    s += _title(W, 26, "DHF Traceability Chain (21 CFR §820.30(j) / ISO 13485 §7.3.10)")

    nodes = [
        ("User\nNeeds",     C_BOX, C_BOX_S),
        ("Design\nInputs",  C_BOX, C_BOX_S),
        ("Design\nOutputs", C_BOX, C_BOX_S),
        ("Verification",    C_GRN, C_GRN_S),
        ("Validation",      C_GRN, C_GRN_S),
        ("Risk\nControls",  C_AMB, C_AMB_S),
    ]
    n  = len(nodes)
    BW = 160; BH = 65; GAP = 20
    total = n*BW + (n-1)*GAP
    start_x = (W - total) // 2
    y = 100

    for i,(lbl,fill,stroke) in enumerate(nodes):
        x = start_x + i*(BW+GAP)
        lbls = lbl.split("\n")
        s += _box(x, y, BW, BH, fill, stroke, lbls, fontsize=13)
        if i < n-1:
            s += _arrow(x+BW, y+BH//2, x+BW+GAP, y+BH//2)

    # Bidirectional bottom return arrow
    ax1 = start_x
    ax2 = start_x + total
    arr_y = y + BH + 35
    s += (f'<line x1="{ax1}" y1="{arr_y}" x2="{ax2}" y2="{arr_y}" '
          f'stroke="{C_BOX_S}" stroke-width="1.2" stroke-dasharray="5,3"/>\n')
    s += _arrow(ax1, arr_y, ax1-1, arr_y, color=C_BOX_S)
    s += _arrow(ax2, arr_y, ax2+1, arr_y, color=C_BOX_S)
    s += _label(W//2, arr_y+18, "← Bidirectional Traceability →", fontsize=11, color=C_BOX_S)

    s += _footer(W, H, "Figure: DHF Traceability Chain — All nodes must be fully populated before DHF closure")
    s += _svg_close()
    with open(out_path, "w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# 7. FMEA RISK PRIORITY CHART (bar chart style, matching the clean aesthetic)
# ══════════════════════════════════════════════════════════════════════════
def gen_fmea_chart(hazards: list, out_path: str, W=1000, H=600):
    """Bar chart of RPN values per hazard."""
    s = _svg_open(W, H)
    s += _title(W, 28, "FMEA — Risk Priority Number (RPN) by Hazard")

    if not hazards:
        s += _label(W//2, H//2, "No hazard data available", fontsize=14)
        s += _footer(W, H, "Figure: FMEA RPN Overview")
        s += _svg_close()
        with open(out_path,"w") as f: f.write(s)
        return out_path

    PAD_L = 280; PAD_R = 80; PAD_T = 70; PAD_B = 100
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B

    rpns = [hz.get("sev",3) * hz.get("prob_initial",3) * hz.get("det",2) for hz in hazards]
    max_rpn = max(rpns) if rpns else 25

    def bar_color(rpn):
        if rpn <= 6:  return C_GRN,  C_GRN_S
        if rpn <= 12: return C_AMB,  C_AMB_S
        return C_RED, C_RED_S

    bar_h = min(40, (chart_h - 10*(len(hazards)-1)) // len(hazards))
    gap   = 10

    for i, (hz, rpn) in enumerate(zip(hazards, rpns)):
        y    = PAD_T + i*(bar_h + gap)
        bw   = int(chart_w * rpn / max_rpn)
        fill, stroke = bar_color(rpn)

        # Label (left)
        lbl = hz.get("hazard","Hazard")[:35]
        s += (f'<text x="{PAD_L-8}" y="{y+bar_h//2}" font-size="11" fill="{C_TXT}" '
              f'text-anchor="end" dominant-baseline="middle">{lbl}</text>\n')

        # Bar
        s += (f'<rect x="{PAD_L}" y="{y}" width="{bw}" height="{bar_h}" '
              f'rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1"/>\n')

        # RPN value
        s += (f'<text x="{PAD_L+bw+6}" y="{y+bar_h//2}" font-size="11" fill="{C_TXT}" '
              f'dominant-baseline="middle" font-weight="bold">'
              f'RPN {rpn}  (S{hz.get("sev",3)}·O{hz.get("prob_initial",3)}·D{hz.get("det",2)})</text>\n')

    # X axis line
    s += (f'<line x1="{PAD_L}" y1="{PAD_T + len(hazards)*(bar_h+gap)}" '
          f'x2="{PAD_L+chart_w}" y2="{PAD_T + len(hazards)*(bar_h+gap)}" '
          f'stroke="{C_TXT}" stroke-width="1"/>\n')
    s += _label(PAD_L + chart_w//2,
                PAD_T + len(hazards)*(bar_h+gap) + 25,
                "Risk Priority Number (RPN = Severity × Occurrence × Detectability)",
                fontsize=11)

    s += _footer(W, H, "Figure: FMEA Hazard RPN Overview — Values require SME confirmation")
    s += _svg_close()
    with open(out_path,"w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# 8. REGULATORY PATHWAY MAP
# ══════════════════════════════════════════════════════════════════════════
def gen_regulatory_map(markets: list, out_path: str, W=1100, H=550):
    s = _svg_open(W, H)
    s += _title(W, 28, "Target Market Regulatory Pathways")

    market_info = {
        "US":        ("FDA",            "510(k) / De Novo / PMA",       C_BOX, C_BOX_S),
        "EU":        ("EU MDR",         "2017/745 + Notified Body",      C_GRN, C_GRN_S),
        "Canada":    ("Health Canada",  "Medical Device Licence",        C_AMB, C_AMB_S),
        "Australia": ("TGA",            "ARTG Registration",             C_PRP, C_PRP_S),
        "Japan":     ("PMDA",           "Shonin Approval",               C_BOX, C_BOX_S),
        "UK":        ("UKCA / MHRA",    "UK CA Marking",                 C_GRN, C_GRN_S),
    }

    show = [m for m in markets if m in market_info]
    if not show:
        show = list(market_info.keys())[:4]

    BW = 220; BH = 80
    n = len(show)
    cols = min(n, 3); rows = math.ceil(n/cols)
    total_w = cols*BW + (cols-1)*40
    total_h = rows*BH + (rows-1)*30
    sx = (W - total_w)//2; sy = 80

    for i, market in enumerate(show):
        r, c = divmod(i, cols)
        x = sx + c*(BW+40)
        y = sy + r*(BH+30)
        agency, pathway, fill, stroke = market_info[market]
        s += _box(x, y, BW, BH, fill, stroke,
                  [f"{market} — {agency}", pathway], fontsize=12)

    s += _footer(W, H, "Figure: Target Market Regulatory Pathway Overview — Verify with RA Lead")
    s += _svg_close()
    with open(out_path,"w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# 9. DATABASE EVIDENCE CHART (horizontal bars, clean style)
# ══════════════════════════════════════════════════════════════════════════
def gen_evidence_chart(counts: dict, out_path: str, W=900, H=600):
    s = _svg_open(W, H)
    s += _title(W, 28, "Real-Time Research Data Retrieved Per Database")

    items = [(k,v) for k,v in counts.items() if isinstance(v,int)]
    items.sort(key=lambda x: x[1], reverse=True)

    if not items:
        s += _label(W//2, H//2, "No data", fontsize=14)
        s += _footer(W, H, "Figure: Database Records Retrieved")
        s += _svg_close()
        with open(out_path,"w") as f: f.write(s)
        return out_path

    PAD_L=220; PAD_R=120; PAD_T=60; PAD_B=70
    chart_w = W - PAD_L - PAD_R
    chart_h = H - PAD_T - PAD_B
    max_v   = max(v for _,v in items) or 1

    src_fills = {
        "PubMed":"#E53935","FDA":"#1D3557","ClinicalTrials":"#457B9D",
        "Europe PMC":"#2D6A4F","Semantic Scholar":"#6A1B9A","CORE":"#E6980A",
        "Google Scholar":"#1A5FA8","Google Patents":"#2E7D32","WIPO":"#C0392B","EMA":"#0E9F8E",
    }

    n = len(items)
    bar_h = min(42, (chart_h - (n-1)*10) // n); gap = 10

    for i,(name,val) in enumerate(items):
        y   = PAD_T + i*(bar_h+gap)
        bw  = max(4, int(chart_w * val / max_v))
        fill = src_fills.get(name,"#475569")

        s += (f'<text x="{PAD_L-8}" y="{y+bar_h//2}" font-size="12" fill="{C_TXT}" '
              f'text-anchor="end" dominant-baseline="middle" font-weight="bold">{name}</text>\n')
        s += (f'<rect x="{PAD_L}" y="{y}" width="{bw}" height="{bar_h}" '
              f'rx="4" fill="{fill}" opacity="0.88"/>\n')
        s += (f'<text x="{PAD_L+bw+6}" y="{y+bar_h//2}" font-size="12" fill="{C_TXT}" '
              f'dominant-baseline="middle" font-weight="bold">{val}</text>\n')

    # Axis
    ax_y = PAD_T + n*(bar_h+gap)
    s += f'<line x1="{PAD_L}" y1="{ax_y}" x2="{PAD_L+chart_w}" y2="{ax_y}" stroke="{C_TXT}" stroke-width="1"/>\n'
    s += _label(PAD_L+chart_w//2, ax_y+22, "Number of Records Retrieved", fontsize=12)

    s += _footer(W, H, "Figure: Live Database Records Retrieved for This Device Query")
    s += _svg_close()
    with open(out_path,"w") as f: f.write(s)
    print(f"  Saved: {out_path}")
    return out_path

# ══════════════════════════════════════════════════════════════════════════
# MASTER FUNCTION — generate all diagrams for a device
# ══════════════════════════════════════════════════════════════════════════
def generate_all(intake: dict, hazards: list, db_counts: dict, tmp_dir: str) -> dict:
    device  = intake["device_name"]
    contact = "Implant" if intake.get("implantable") else ("Surface/External" if intake.get("patient_contacting") else "None")
    duration = "Long-term (>30d)" if intake.get("implantable") else "Limited (≤24h) / Prolonged (24h-30d)"

    imgs = {}
    imgs["vmodel"]       = gen_vmodel(device, os.path.join(tmp_dir,"vmodel.svg"))
    imgs["iso14971"]     = gen_iso14971(os.path.join(tmp_dir,"iso14971.svg"))
    imgs["risk_matrix"]  = gen_risk_matrix(hazards, os.path.join(tmp_dir,"risk_matrix.svg"))
    imgs["traceability"] = gen_traceability_chain(os.path.join(tmp_dir,"traceability.svg"))
    imgs["fmea_chart"]   = gen_fmea_chart(hazards, os.path.join(tmp_dir,"fmea_chart.svg"))
    imgs["reg_map"]      = gen_regulatory_map(intake.get("target_markets",[]), os.path.join(tmp_dir,"reg_map.svg"))
    imgs["evidence"]     = gen_evidence_chart(db_counts, os.path.join(tmp_dir,"evidence.svg"))

    if intake.get("patient_contacting"):
        imgs["biocompat"] = gen_biocompat_flow(contact, duration, os.path.join(tmp_dir,"biocompat.svg"))
    if intake.get("contains_software"):
        imgs["sw_class"]  = gen_sw_classification(os.path.join(tmp_dir,"sw_class.svg"))

    return imgs

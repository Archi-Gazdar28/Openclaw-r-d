#!/usr/bin/env python3
"""
export_report.py  —  OpenClaw R&D Intelligence Report Exporter  v3.0
Generates a self-contained HTML report with embedded charts.
Open in browser → click "Download PDF" to save.

Usage (unchanged from v2):
    python3 export_report.py export \
        --format pdf \
        --title  "R&D Intelligence Report: Tonometer by Haag-Streit" \
        --input  ~/.openclaw/workspace/reports/haagstriet_tonometer_2026-06-22/report.json \
        --output ~/.openclaw/workspace/reports/haagstriet_tonometer_2026-06-22/report.html

Or use --auto-open to launch the browser immediately after generation:
    python3 export_report.py export ... --auto-open
"""

import argparse, json, os, sys, webbrowser
from datetime import datetime
from pathlib import Path

# ── helpers ──────────────────────────────────────────────────────────────────
def safe(d, *keys, default="—"):
    for k in keys:
        if not isinstance(d, dict): return default
        d = d.get(k, default)
        if d is None or d == "": return default
    return d if d != default else default

def esc(t):
    return str(t).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def flatten_gaps(g):
    if not g: return []
    if isinstance(g, str): return [g]
    if isinstance(g, list): return [str(x) for x in g]
    return [str(g)]

def kv_rows(pairs):
    rows = ""
    for label, val in pairs:
        if val and val != "—":
            rows += f'<tr><td class="kv-label">{esc(label)}</td><td class="kv-val">{esc(val)}</td></tr>'
    return f'<table class="kv-table">{rows}</table>' if rows else ""

def badge(text, cls="badge-default"):
    return f'<span class="badge {cls}">{esc(text)}</span>'

def section_wrap(num, title, icon, content):
    return f'''
<section id="sec{num}">
  <div class="sec-header">
    <span class="sec-icon">{icon}</span>
    <h2>{num}. {esc(title)}</h2>
  </div>
  <div class="sec-body">{content}</div>
</section>'''

def gap_notes(gaps):
    if not gaps: return ""
    items = "".join(f'<li>{esc(g)}</li>' for g in gaps)
    return f'<div class="gap-box"><span class="gap-icon">⚠</span><ul>{items}</ul></div>'

# ── section builders ──────────────────────────────────────────────────────────
def build_company(data):
    cd = data.get("company-details", {})
    profile = cd.get("profile", cd)
    pairs = [
        ("Legal name",   safe(profile,"legal_name")),
        ("Description",  safe(profile,"short_description")),
        ("Website",      safe(profile,"website_url")),
        ("Country",      safe(profile,"country_code")),
        ("Founded",      safe(profile,"founded_on")),
        ("Employees",    safe(profile,"num_employees_enum")),
        ("Total funding",safe(profile,"total_funding_usd")),
    ]
    html = kv_rows(pairs)

    # people
    people = profile.get("people",[]) if isinstance(profile,dict) else []
    if people and isinstance(people,list):
        rows = ""
        for p in people:
            if isinstance(p,dict):
                rows += f'<tr><td>{esc(safe(p,"name"))}</td><td>{esc(safe(p,"title"))}</td></tr>'
        if rows:
            html += f'<h3>Key people</h3><table class="data-table"><thead><tr><th>Name</th><th>Title</th></tr></thead><tbody>{rows}</tbody></table>'

    html += gap_notes(flatten_gaps(cd.get("data_gaps")))
    return html

def build_turnover(data):
    tv = data.get("turnover", {})
    rows_data = tv.get("rows", [])
    html = ""
    chart_labels, chart_values = [], []

    if rows_data and isinstance(rows_data, list):
        trows = ""
        for row in rows_data:
            if isinstance(row, dict):
                year = safe(row,"year","fiscal_year","date")
                rev  = safe(row,"revenue","revenue_usd","value","amount")
                note = safe(row,"label","metric","note")
                trows += f'<tr><td>{esc(year)}</td><td>{esc(rev)}</td><td>{esc(note)}</td></tr>'
                chart_labels.append(str(year))
                try:
                    chart_values.append(float(str(rev).replace(",","").replace("$","").replace("M","e6").replace("B","e9")))
                except: chart_values.append(0)
        if trows:
            html += f'<table class="data-table"><thead><tr><th>Period</th><th>Revenue / Value</th><th>Note</th></tr></thead><tbody>{trows}</tbody></table>'
    else:
        html += '<p class="muted">No structured financial data retrieved. This company may be private or Serper free-tier limits applied.</p>'

    if chart_labels and any(v>0 for v in chart_values):
        html += f'''
<div class="chart-wrap">
  <canvas id="chart-turnover" role="img" aria-label="Revenue over time bar chart"></canvas>
</div>
<script>
(function(){{
  var ctx = document.getElementById('chart-turnover');
  new Chart(ctx, {{
    type: 'bar',
    data: {{
      labels: {json.dumps(chart_labels)},
      datasets: [{{ label: 'Revenue', data: {json.dumps(chart_values)},
        backgroundColor: 'rgba(50,102,173,0.75)', borderColor: '#3266ad',
        borderWidth: 1.5, borderRadius: 4 }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ y: {{ beginAtZero: true, ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(0,0,0,0.06)' }} }},
                 x: {{ ticks: {{ color: '#888' }}, grid: {{ display: false }} }} }}
    }}
  }});
}})();
</script>'''

    meta = [(k, safe(tv,v)) for k,v in [("Source","source_label"),("Public","is_public"),("Ticker","ticker")]]
    html += kv_rows(meta)
    html += gap_notes(flatten_gaps(tv.get("data_gaps")))
    return html

def build_patents(data):
    pt = data.get("patents", {})
    patents_list = pt.get("patents", [])
    total = safe(pt,"count",default=str(len(patents_list) if isinstance(patents_list,list) else 0))
    html = f'<p class="sub-note">Total records: <strong>{esc(total)}</strong></p>'

    # tech area pie chart
    tech = pt.get("tech_areas",[])
    if tech and isinstance(tech,list) and len(tech) >= 2:
        labels = [str(t) for t in tech[:8]]
        vals   = [1]*len(labels)
        colors_js = '["#3266ad","#1d9e75","#d85a30","#ba7517","#533ab7","#d4537e","#639922","#888780"]'
        html += f'''
<div class="chart-wrap chart-wrap--sm">
  <canvas id="chart-tech" role="img" aria-label="Technology areas pie chart"></canvas>
</div>
<script>
(function(){{
  new Chart(document.getElementById('chart-tech'), {{
    type: 'pie',
    data: {{
      labels: {json.dumps(labels)},
      datasets: [{{ data: {json.dumps(vals)}, backgroundColor: {colors_js}, borderWidth: 2, borderColor: '#fff' }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ position: 'right', labels: {{ font: {{ size: 11 }}, color: '#555', boxWidth: 12 }} }} }}
    }}
  }});
}})();
</script>'''

    if patents_list and isinstance(patents_list,list):
        html += '<div class="card-grid">'
        for pat in patents_list:
            if not isinstance(pat,dict): continue
            title  = safe(pat,"title")
            link   = safe(pat,"link")
            pub    = safe(pat,"publication_date")
            abstr  = safe(pat,"abstract_snippet")
            assign = safe(pat,"assignee")
            title_html = f'<a href="{esc(link)}" target="_blank">{esc(title)}</a>' if link != "—" else esc(title)
            meta_parts = [x for x in [assign,pub] if x and x != "—"]
            meta_str = " · ".join(meta_parts)
            abstr_html = f'<p class="card-desc">{esc(abstr)}</p>' if abstr != "—" else ""
            html += f'''
<div class="info-card">
  <div class="card-title">{title_html}</div>
  <div class="card-meta">{esc(meta_str)}</div>
  {abstr_html}
</div>'''
        html += '</div>'

    html += gap_notes(flatten_gaps(pt.get("data_gaps")))
    return html

def build_trends(data):
    tr = data.get("trends", {})
    product = safe(tr,"product")
    geo     = safe(tr,"geo")
    html = kv_rows([("Product",product),("Geography",geo),("Since",safe(tr,"since"))])

    timeline = tr.get("timeline",[])
    chart_labels, chart_values = [], []
    if timeline and isinstance(timeline,list):
        for entry in timeline:
            if isinstance(entry,dict):
                date = safe(entry,"date")
                vals = entry.get("values",[])
                val  = 0
                if isinstance(vals,list) and vals:
                    v0 = vals[0]
                    try: val = int(v0.get("extracted_value",0)) if isinstance(v0,dict) else int(v0)
                    except: val = 0
                elif isinstance(vals,dict):
                    try: val = int(safe(vals,"extracted_value","value",default=0))
                    except: val = 0
                chart_labels.append(str(date))
                chart_values.append(val)

    if chart_labels:
        html += f'''
<div class="chart-wrap">
  <canvas id="chart-trends" role="img" aria-label="Search interest over time line chart"></canvas>
</div>
<script>
(function(){{
  new Chart(document.getElementById('chart-trends'), {{
    type: 'line',
    data: {{
      labels: {json.dumps(chart_labels)},
      datasets: [{{
        label: 'Interest Index (0–100)',
        data: {json.dumps(chart_values)},
        borderColor: '#1d9e75', backgroundColor: 'rgba(29,158,117,0.1)',
        borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#1d9e75',
        fill: true, tension: 0.35
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        y: {{ min: 0, max: 100, ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(0,0,0,0.06)' }} }},
        x: {{ ticks: {{ color: '#888', maxRotation: 45, autoSkip: true, maxTicksLimit: 12 }}, grid: {{ display: false }} }}
      }}
    }}
  }});
}})();
</script>'''

    # related queries
    rq = tr.get("related_queries",{})
    if isinstance(rq,dict):
        for grp, items in rq.items():
            if isinstance(items,list) and items:
                html += f'<h3>Related queries — {esc(grp)}</h3><ul class="tag-list">'
                for item in items:
                    if isinstance(item,dict):
                        q = safe(item,"query","title")
                        html += f'<li>{esc(q)}</li>'
                html += '</ul>'

    html += gap_notes(flatten_gaps(tr.get("data_gaps")))
    return html

def build_competitors(data):
    comp = data.get("competitors", {})
    competitors_list = comp.get("competitors", [])
    count = len(competitors_list) if isinstance(competitors_list,list) else 0
    html = f'<p class="sub-note">Market peers identified: <strong>{count}</strong></p>'

    # bar chart of named companies (non-market-report entries)
    named = [c for c in (competitors_list or []) if isinstance(c,dict) and
             safe(c,"name") not in ("—",) and
             not any(x in safe(c,"name","").lower() for x in ["market size","market share","report","forecast","industry"])]

    if named:
        html += '<div class="card-grid">'
        for c in named:
            name  = safe(c,"name")
            desc  = safe(c,"description")
            url   = safe(c,"website")
            fund  = safe(c,"funding_usd")
            found = safe(c,"founded")
            url_html = f'<a href="{esc(url)}" target="_blank">{esc(url)}</a>' if url != "—" else ""
            pairs = [("Website",url_html if url != "—" else ""),("Funding",fund),("Founded",found)]
            meta_html = "".join(f'<span class="card-kv"><span>{esc(k)}</span>{v}</span>' for k,v in [("Funding",fund),("Founded",found)] if v and v != "—")
            html += f'''
<div class="info-card">
  <div class="card-title">{esc(name)}</div>
  {f'<p class="card-desc">{esc(desc)}</p>' if desc != "—" else ""}
  {f'<div class="card-meta">{url_html}</div>' if url != "—" else ""}
  {f'<div class="card-kv-row">{meta_html}</div>' if meta_html else ""}
</div>'''
        html += '</div>'
    else:
        # market reports as table
        rows = ""
        for c in (competitors_list or []):
            if isinstance(c,dict):
                name = safe(c,"name")
                desc = safe(c,"description")
                url  = safe(c,"website")
                link = f'<a href="{esc(url)}" target="_blank">↗</a>' if url != "—" else ""
                rows += f'<tr><td>{esc(name)}</td><td>{esc(desc[:160])}{"…" if len(str(desc))>160 else ""}</td><td>{link}</td></tr>'
        if rows:
            html += f'<table class="data-table"><thead><tr><th>Source</th><th>Summary</th><th>Link</th></tr></thead><tbody>{rows}</tbody></table>'

    html += gap_notes(flatten_gaps(comp.get("data_gaps")))
    return html

def build_research(data):
    rp = data.get("research-papers", {})
    papers = rp.get("papers", [])
    count  = safe(rp,"count",default=str(len(papers) if isinstance(papers,list) else 0))
    html   = f'<p class="sub-note">Academic papers retrieved: <strong>{esc(count)}</strong></p>'

    # citation count bar chart
    citable = [(safe(p,"title"), safe(p,"cited_by")) for p in (papers or []) if isinstance(p,dict)]
    citable = [(t[:40]+"…" if len(t)>40 else t, c) for t,c in citable if c and c != "—"]
    try:
        citable = sorted([(t, int(str(c).replace(",",""))) for t,c in citable], key=lambda x: -x[1])[:8]
    except: citable = []

    if citable:
        clabels = [t for t,_ in citable]
        cvals   = [v for _,v in citable]
        h = max(len(clabels)*44 + 80, 200)
        html += f'''
<div class="chart-wrap" style="height:{h}px">
  <canvas id="chart-papers" role="img" aria-label="Citations per paper horizontal bar chart"></canvas>
</div>
<script>
(function(){{
  new Chart(document.getElementById('chart-papers'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(clabels)},
      datasets: [{{ label: 'Citations', data: {json.dumps(cvals)},
        backgroundColor: 'rgba(83,74,183,0.75)', borderColor: '#534ab7',
        borderWidth: 1.5, borderRadius: 4 }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{ beginAtZero: true, ticks: {{ color: '#888' }}, grid: {{ color: 'rgba(0,0,0,0.06)' }} }},
        y: {{ ticks: {{ color: '#555', font: {{ size: 11 }} }}, grid: {{ display: false }} }}
      }}
    }}
  }});
}})();
</script>'''

    if papers and isinstance(papers,list):
        html += '<div class="card-grid">'
        for paper in papers:
            if not isinstance(paper,dict): continue
            title   = safe(paper,"title")
            authors = safe(paper,"authors")
            year    = safe(paper,"year")
            venue   = safe(paper,"venue")
            cited   = safe(paper,"cited_by")
            snippet = safe(paper,"snippet")
            link    = safe(paper,"link")
            title_html = f'<a href="{esc(link)}" target="_blank">{esc(title)}</a>' if link != "—" else esc(title)
            meta_parts = [x for x in [authors, year, venue] if x and x != "—"]
            cited_badge = badge(f"Cited {cited}×","badge-purple") if cited and cited != "—" else ""
            html += f'''
<div class="info-card">
  <div class="card-title">{title_html} {cited_badge}</div>
  <div class="card-meta">{esc(" · ".join(meta_parts[:2]))}</div>
  {f'<p class="card-desc">{esc(snippet)}</p>' if snippet != "—" else ""}
</div>'''
        html += '</div>'

    html += gap_notes(flatten_gaps(rp.get("data_gaps")))
    return html

def build_quality(data):
    section_map = {
        "company-details":"Company overview","turnover":"Financial overview",
        "patents":"Patents","trends":"Market trends",
        "competitors":"Competitive landscape","research-papers":"Research papers",
    }
    found = False
    html  = '<p>Automatically logged by the OpenClaw intelligence pipeline.</p>'
    for key, label in section_map.items():
        sec  = data.get(key,{})
        gaps = flatten_gaps(sec.get("data_gaps") if isinstance(sec,dict) else None)
        if gaps:
            found = True
            html += f'<h3>{esc(label)}</h3><ul class="gap-list">'
            for g in gaps: html += f'<li>{esc(g)}</li>'
            html += '</ul>'
    if not found:
        html += '<p class="muted">No data gaps recorded for this run.</p>'
    return html

# ── TOC ───────────────────────────────────────────────────────────────────────
SECTIONS = [
    (1,"Company overview","🏢"),
    (2,"Financial overview","💰"),
    (3,"Patents & IP","📄"),
    (4,"Market trends","📈"),
    (5,"Competitive landscape","🏆"),
    (6,"Research & literature","🔬"),
    (7,"Data quality notes","⚠️"),
]

def build_toc():
    items = "".join(
        f'<li><a href="#sec{n}"><span class="toc-num">{n}</span>{esc(t)}</a></li>'
        for n,t,_ in SECTIONS)
    return f'<nav class="toc"><h2>Contents</h2><ol>{items}</ol></nav>'

# ── Full HTML document ────────────────────────────────────────────────────────
def build_html(data, raw, title):
    company = safe(raw,"company",default=safe(data,"company-details","company",default="Company"))
    product = safe(raw,"product",default="Product")
    as_of   = safe(raw,"as_of",  default=datetime.today().strftime("%Y-%m-%d"))

    sec_html = [
        section_wrap(1,"Company overview","🏢",   build_company(data)),
        section_wrap(2,"Financial overview","💰",  build_turnover(data)),
        section_wrap(3,"Patents & IP","📄",         build_patents(data)),
        section_wrap(4,"Market trends","📈",        build_trends(data)),
        section_wrap(5,"Competitive landscape","🏆",build_competitors(data)),
        section_wrap(6,"Research & literature","🔬",build_research(data)),
        section_wrap(7,"Data quality notes","⚠️",   build_quality(data)),
    ]

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --ink:#1a1a1a;--ink2:#444;--ink3:#777;--ink4:#aaa;
  --bg:#fff;--bg2:#f8f8f6;--bg3:#f2f2ef;
  --rule:#e0e0dc;--blue:#3266ad;--green:#1d9e75;
  --accent:#3266ad;--font:'Segoe UI',system-ui,sans-serif;
  --radius:8px;
}}
@media(prefers-color-scheme:dark){{
  :root{{--ink:#f0ede8;--ink2:#c8c5c0;--ink3:#999;--ink4:#666;
    --bg:#1a1a18;--bg2:#242422;--bg3:#2c2c2a;--rule:#3a3a38}}
}}
body{{font-family:var(--font);font-size:15px;line-height:1.65;color:var(--ink);background:var(--bg);}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
h2{{font-size:20px;font-weight:600;color:var(--ink)}}
h3{{font-size:15px;font-weight:600;color:var(--ink2);margin:1.2rem 0 .5rem}}
p{{color:var(--ink2);margin:.4rem 0}}
strong{{font-weight:600}}

/* ── layout ── */
.page{{max-width:900px;margin:0 auto;padding:2rem 1.5rem 4rem}}

/* ── cover ── */
.cover{{padding:3rem 0 2.5rem;border-bottom:1px solid var(--rule);margin-bottom:2.5rem}}
.cover-eyebrow{{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink4);margin-bottom:.6rem}}
.cover-title{{font-size:30px;font-weight:700;line-height:1.25;color:var(--ink);margin-bottom:.8rem}}
.cover-meta{{font-size:13px;color:var(--ink3)}}
.cover-tags{{display:flex;gap:8px;flex-wrap:wrap;margin:.8rem 0}}

/* ── download button ── */
.dl-btn{{display:inline-flex;align-items:center;gap:6px;background:var(--accent);
  color:#fff;padding:.5rem 1.1rem;border-radius:var(--radius);font-size:14px;
  font-weight:500;cursor:pointer;border:none;margin-top:1.2rem;transition:opacity .15s}}
.dl-btn:hover{{opacity:.88}}
.dl-btn svg{{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}}

/* ── toc ── */
.toc{{background:var(--bg2);border:1px solid var(--rule);border-radius:var(--radius);padding:1.2rem 1.5rem;margin-bottom:2.5rem}}
.toc h2{{font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink3);margin-bottom:.7rem}}
.toc ol{{list-style:none;display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:4px}}
.toc a{{color:var(--ink2);font-size:14px;display:flex;align-items:center;gap:6px;padding:3px 0}}
.toc a:hover{{color:var(--accent)}}
.toc-num{{font-size:11px;font-weight:600;color:var(--ink4);min-width:16px}}

/* ── sections ── */
section{{margin-bottom:2.8rem}}
.sec-header{{display:flex;align-items:center;gap:10px;margin-bottom:1rem;padding-bottom:.5rem;border-bottom:1.5px solid var(--rule)}}
.sec-icon{{font-size:20px}}
.sec-body{{}}

/* ── kv table ── */
.kv-table{{width:100%;border-collapse:collapse;margin:.6rem 0}}
.kv-table tr:nth-child(even){{background:var(--bg2)}}
.kv-label{{font-size:12px;font-weight:600;color:var(--ink3);padding:5px 10px 5px 0;width:140px;vertical-align:top}}
.kv-val{{font-size:14px;color:var(--ink2);padding:5px 0;vertical-align:top}}

/* ── data table ── */
.data-table{{width:100%;border-collapse:collapse;font-size:13px;margin:.8rem 0}}
.data-table th{{background:var(--bg3);font-weight:600;color:var(--ink2);text-align:left;padding:7px 10px;border-bottom:1px solid var(--rule)}}
.data-table td{{padding:6px 10px;border-bottom:.5px solid var(--rule);color:var(--ink2);vertical-align:top}}
.data-table tr:hover td{{background:var(--bg2)}}

/* ── cards ── */
.card-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin:.8rem 0}}
.info-card{{background:var(--bg);border:1px solid var(--rule);border-radius:var(--radius);padding:.9rem 1rem}}
.card-title{{font-size:13.5px;font-weight:600;color:var(--ink);line-height:1.4;margin-bottom:4px}}
.card-meta{{font-size:11.5px;color:var(--ink4);margin-bottom:5px}}
.card-desc{{font-size:12.5px;color:var(--ink3);line-height:1.5;margin-top:5px}}
.card-kv-row{{display:flex;gap:12px;margin-top:6px;flex-wrap:wrap}}
.card-kv{{font-size:11.5px;color:var(--ink4)}}
.card-kv span{{margin-right:3px;font-weight:600}}

/* ── charts ── */
.chart-wrap{{position:relative;width:100%;height:260px;margin:1rem 0 1.5rem}}
.chart-wrap--sm{{height:200px}}

/* ── badges ── */
.badge{{font-size:10.5px;font-weight:600;padding:2px 7px;border-radius:20px;display:inline-block;margin-left:4px;vertical-align:middle}}
.badge-default{{background:var(--bg3);color:var(--ink3)}}
.badge-purple{{background:#ede9ff;color:#4a3eaa}}
@media(prefers-color-scheme:dark){{.badge-purple{{background:#2e2860;color:#c3b9ff}}}}

/* ── misc ── */
.muted{{color:var(--ink3);font-style:italic}}
.sub-note{{font-size:13px;color:var(--ink3);margin-bottom:.6rem}}
.gap-box{{background:#fff8f0;border-left:3px solid #e5890a;border-radius:0 var(--radius) var(--radius) 0;
  padding:.6rem .9rem;margin:.8rem 0;display:flex;gap:8px;align-items:flex-start}}
@media(prefers-color-scheme:dark){{.gap-box{{background:#2a2010;border-color:#a06010}}}}
.gap-icon{{font-size:14px;margin-top:1px}}
.gap-box ul{{list-style:none;font-size:12.5px;color:#a06010}}
@media(prefers-color-scheme:dark){{.gap-box ul{{color:#d4960a}}}}
.gap-list{{padding-left:1.2rem;font-size:13px;color:var(--ink3)}}
.gap-list li{{margin:.3rem 0}}
.tag-list{{display:flex;flex-wrap:wrap;gap:6px;list-style:none;margin:.4rem 0}}
.tag-list li{{font-size:12px;background:var(--bg3);color:var(--ink2);padding:3px 10px;border-radius:20px}}

/* ── print ── */
@media print{{
  .dl-btn,.toc{{display:none}}
  .page{{padding:0}}
  section{{page-break-inside:avoid}}
  .chart-wrap{{height:220px!important}}
}}
</style>
</head>
<body>
<div class="page">

<div class="cover">
  <div class="cover-eyebrow">OpenClaw R&amp;D Intelligence Platform</div>
  <div class="cover-title">{esc(title)}</div>
  <div class="cover-tags">
    <span class="badge badge-default">{esc(company)}</span>
    <span class="badge badge-default">{esc(product)}</span>
    <span class="badge badge-default">{esc(as_of)}</span>
  </div>
  <div class="cover-meta">Confidential — For internal use only</div>
  <button class="dl-btn" onclick="window.print()">
    <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    Download PDF
  </button>
</div>

{build_toc()}

{"".join(sec_html)}

<footer style="margin-top:3rem;padding-top:1rem;border-top:1px solid var(--rule);font-size:12px;color:var(--ink4);text-align:center;">
  Generated by OpenClaw R&amp;D Intelligence · {esc(as_of)} · Confidential
</footer>

</div>
</body>
</html>'''

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="OpenClaw report exporter v3.0")
    sub = parser.add_subparsers(dest="command")

    ep = sub.add_parser("export")
    ep.add_argument("--format",      default="pdf", choices=["pdf","html"])
    ep.add_argument("--title",       default="R&D Intelligence Report")
    ep.add_argument("--input",       required=True)
    ep.add_argument("--output",      required=True)
    ep.add_argument("--auto-open",   action="store_true", help="Open in browser after export")
    # legacy flags (ignored, kept for backward compat)
    ep.add_argument("--markdown-file", default=None)
    ep.add_argument("--charts-dir",    default=None)
    ep.add_argument("--out-dir",       default=None)

    args = parser.parse_args()

    if args.command != "export":
        parser.print_help(); return

    inp = os.path.expanduser(args.input)
    out = os.path.expanduser(args.output)

    # If --out-dir used (legacy), derive output path
    if args.out_dir and not args.output:
        out = os.path.join(os.path.expanduser(args.out_dir),
                           Path(inp).stem + ".html")

    # Always write .html
    if not out.endswith(".html"):
        out = Path(out).with_suffix(".html").as_posix()

    if not os.path.exists(inp):
        print(f"[error] Input not found: {inp}", file=sys.stderr); sys.exit(1)

    with open(inp, "r", encoding="utf-8") as f:
        raw = json.load(f)

    data = raw
    if isinstance(raw, dict):
        if "sections" in raw: data = raw["sections"]
        elif "data"    in raw: data = raw["data"]

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    html = build_html(data, raw, args.title)

    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[export_report] HTML report → {out}")
    print(f"[export_report] Open in browser → click 'Download PDF' to save")

    if args.auto_open:
        webbrowser.open(f"file://{os.path.abspath(out)}")

if __name__ == "__main__":
    main()

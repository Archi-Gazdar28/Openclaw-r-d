#!/usr/bin/env python3
"""
dhf_free.py  —  Dynamic DHF Builder (No API Key Required)
==========================================================
Queries 10 free databases, extracts real device-specific evidence,
generates professional SVG diagrams matching the uploaded style,
then renders a complete Design History File PDF.

Data Sources (all free, no key):
  1. PubMed          (NCBI E-utilities API)
  2. FDA openFDA     (fda.gov API)
  3. ClinicalTrials  (clinicaltrials.gov API v2)
  4. Europe PMC      (europepmc.org REST API)
  5. Semantic Scholar(api.semanticscholar.org)
  6. CORE            (api.core.ac.uk)
  7. Google Scholar  (web scrape)
  8. Google Patents  (web scrape)
  9. WIPO PATENTSCOPE(web scrape)
 10. EMA             (web scrape)

Install:
    pip install requests beautifulsoup4 lxml reportlab cairosvg pillow

Usage:
    python3 dhf_free.py --intake intake.json --out DHF.pdf
    python3 dhf_free.py --intake intake.json --cache data.json --out DHF.pdf
    python3 dhf_free.py --intake intake.json --cache data.json --cached --out DHF.pdf
"""

import argparse, json, math, os, re, sys, textwrap, time, tempfile
from pathlib import Path
from datetime import date
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
import cairosvg

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Flowable, HRFlowable, Image, KeepTogether,
)
from reportlab.lib.colors import HexColor

# ══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════
PAGE_W, PAGE_H = A4
MARGIN    = 1.8 * cm
CONTENT_W = PAGE_W - 2 * MARGIN
TODAY     = date.today().isoformat()
RETRY     = 2
DELAY     = 0.8

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/json,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

SOURCE_COLORS = {
    "PubMed":"#E53935","FDA":"#1D3557","ClinicalTrials":"#457B9D",
    "Europe PMC":"#2D6A4F","Semantic Scholar":"#6A1B9A","CORE":"#E6980A",
    "Google Scholar":"#1A5FA8","Google Patents":"#2E7D32","WIPO":"#C0392B","EMA":"#0E9F8E",
}

# ── Palette ───────────────────────────────────────────────────────────────
C_INK  = HexColor("#0D1117"); C_NAVY = HexColor("#0F2D52")
C_BLUE = HexColor("#1A5FA8"); C_TEAL = HexColor("#0E9F8E")
C_RULE = HexColor("#CBD5E1"); C_SHADE= HexColor("#F1F5F9")
C_SHADE2=HexColor("#E0F2FE"); C_COOL = HexColor("#94A3B8")
C_SLATE= HexColor("#475569"); C_AMBER= HexColor("#D97706")
C_AZURE= HexColor("#2E86C1"); C_WHITE= colors.white

# ── Style sheet ───────────────────────────────────────────────────────────
def _ps(name,**kw): return ParagraphStyle(name,**kw)
ST = {
    "cover_title": _ps("ct", fontName="Helvetica-Bold",   fontSize=30,leading=38,textColor=C_WHITE, alignment=TA_CENTER),
    "cover_tag":   _ps("cta",fontName="Helvetica",        fontSize=13,leading=18,textColor=HexColor("#94A3B8"),alignment=TA_CENTER),
    "h1":          _ps("h1", fontName="Helvetica-Bold",   fontSize=14,leading=19,textColor=C_NAVY, spaceBefore=14,spaceAfter=5, keepWithNext=True),
    "h2":          _ps("h2", fontName="Helvetica-Bold",   fontSize=11,leading=15,textColor=C_BLUE, spaceBefore=10,spaceAfter=3, keepWithNext=True),
    "h3":          _ps("h3", fontName="Helvetica-Bold",   fontSize=9.5,leading=13,textColor=C_SLATE,spaceBefore=8,spaceAfter=2, keepWithNext=True),
    "body":        _ps("bd", fontName="Helvetica",        fontSize=9, leading=13.5,textColor=C_INK,spaceAfter=4, alignment=TA_JUSTIFY),
    "th":          _ps("th", fontName="Helvetica-Bold",   fontSize=8, leading=10,textColor=C_WHITE),
    "td":          _ps("td", fontName="Helvetica",        fontSize=8.5,leading=11,textColor=C_INK),
    "td_sm":       _ps("tds",fontName="Helvetica",        fontSize=7.5,leading=10,textColor=C_INK),
    "label":       _ps("lb", fontName="Helvetica-Bold",   fontSize=8, leading=11,textColor=C_SLATE),
    "value":       _ps("vl", fontName="Helvetica",        fontSize=9, leading=12,textColor=C_INK),
    "toc":         _ps("tc", fontName="Helvetica",        fontSize=10,leading=19,textColor=C_INK, leftIndent=4),
    "toc_sub":     _ps("tcs",fontName="Helvetica",        fontSize=9, leading=16,textColor=C_SLATE,leftIndent=22),
    "reg":         _ps("rg", fontName="Helvetica-Oblique",fontSize=7.5,leading=10,textColor=C_AZURE,spaceAfter=4),
    "caption":     _ps("cp", fontName="Helvetica-Oblique",fontSize=8, leading=11,textColor=C_COOL, alignment=TA_CENTER,spaceBefore=3,spaceAfter=8),
    "src":         _ps("sl", fontName="Helvetica-Oblique",fontSize=7, leading=9, textColor=C_AZURE,spaceAfter=4),
    "notice":      _ps("nt", fontName="Helvetica-Oblique",fontSize=8, leading=12,textColor=C_SLATE,alignment=TA_JUSTIFY),
}

# ══════════════════════════════════════════════════════════════════════════
# CUSTOM FLOWABLES
# ══════════════════════════════════════════════════════════════════════════
class Bookmark(Flowable):
    def __init__(self,key,title,level=0):
        super().__init__(); self.key,self.title,self.level=key,title,level; self.width=self.height=0
    def wrap(self,aw,ah): return 0,0
    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title,self.key,level=self.level,closed=False)

class SectionDiv(Flowable):
    def __init__(self,num,title,subtitle=""):
        super().__init__(); self.num,self.title,self.subtitle=num,title,subtitle; self.height=54
    def wrap(self,aw,ah):
        self.width=aw; return aw,self.height
    def draw(self):
        c=self.canv
        c.setFillColor(C_NAVY); c.roundRect(0,0,self.width,self.height,5,fill=1,stroke=0)
        c.setFillColor(C_AZURE); c.roundRect(0,0,40,self.height,5,fill=1,stroke=0)
        c.rect(30,0,15,self.height,fill=1,stroke=0)
        c.setFont("Helvetica-Bold",16); c.setFillColor(C_WHITE)
        c.drawCentredString(20,(self.height-16)/2+2,str(self.num))
        c.setFont("Helvetica-Bold",13)
        c.drawString(52,(self.height-13)/2+8,self.title)
        if self.subtitle:
            c.setFont("Helvetica",8); c.setFillColor(HexColor("#94A3B8"))
            c.drawString(52,(self.height-13)/2-6,self.subtitle)

# ══════════════════════════════════════════════════════════════════════════
# LAYOUT HELPERS
# ══════════════════════════════════════════════════════════════════════════
def anchor(key): return Paragraph(f'<a name="{key}"/>',_ps("_a",fontSize=1,leading=1))
def hr(t=0.5,c=None): return HRFlowable(width="100%",thickness=t,color=c or C_RULE,spaceBefore=4,spaceAfter=6)
def sp(h=6): return Spacer(1,h)
def reg_ref(*refs):
    pills=" &nbsp;|&nbsp; ".join(f'<font color="#1A5FA8"><b>{r}</b></font>' for r in refs)
    return Paragraph(pills,ST["reg"])
def src_line(srcs): return Paragraph(f'<font color="#94A3B8"><i>Sources: {" · ".join(srcs)}</i></font>',ST["src"])
def trunc(s,n=60): s=str(s or ""); return s[:n]+"…" if len(s)>n else s

def info_box(text,accent=None,bg=None):
    p=Paragraph(text,ST["notice"])
    t=Table([[p]],colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),bg or C_SHADE2),
        ("LINEAFTER",(0,0),(0,-1),4,accent or C_AZURE),
        ("LINEBEFORE",(0,0),(0,-1),4,accent or C_AZURE),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),12),("RIGHTPADDING",(0,0),(-1,-1),12),
    ]))
    return t

def kv_table(pairs,lw=5.0*cm):
    rows=[[Paragraph(str(k),ST["label"]),Paragraph(str(v),ST["value"])] for k,v in pairs if v]
    if not rows: return sp(1)
    t=Table(rows,colWidths=[lw,CONTENT_W-lw],hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,0),(-1,-1),[C_WHITE,C_SHADE]),
        ("LINEBELOW",(0,0),(-1,-1),0.35,C_RULE),("BOX",(0,0),(-1,-1),0.5,C_RULE),
        ("LEFTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    return t

def grid(headers,rows,widths=None,small=False):
    if not rows: return sp(1)
    sty=ST["td_sm"] if small else ST["td"]
    hrow=[Paragraph(h,ST["th"]) for h in headers]
    brows=[[Paragraph(str(c),sty) for c in r] for r in rows]
    cw=widths or [CONTENT_W/len(headers)]*len(headers)
    t=Table([hrow]+brows,colWidths=cw,hAlign="LEFT",repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),C_NAVY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WHITE,C_SHADE]),
        ("LINEBELOW",(0,0),(-1,-1),0.35,C_RULE),("BOX",(0,0),(-1,-1),0.5,C_NAVY),
        ("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    return t

def sec_hdr(story,num,title,key,sub=""):
    story+=[Bookmark(key,f"{num}. {title}"),anchor(key),SectionDiv(num,title,sub),sp(8)]

def svg_img(svg_path,width,height=None):
    """Convert SVG→PNG and return ReportLab Image."""
    png_path = svg_path.replace(".svg",".png")
    cairosvg.svg2png(url=svg_path, write_to=png_path, scale=2.0)
    if height:
        return Image(png_path, width=width, height=height)
    return Image(png_path, width=width)

# ══════════════════════════════════════════════════════════════════════════
# PAGE DECORATOR
# ══════════════════════════════════════════════════════════════════════════
class PageDec:
    def __init__(self,intake):
        self.device=intake["device_name"]; self.model=intake.get("model_number","")
        self.fda=intake.get("fda_class","?")
    def __call__(self,canvas,doc):
        canvas.saveState()
        canvas.setFillColor(C_NAVY)
        canvas.rect(MARGIN,PAGE_H-1.45*cm,CONTENT_W,0.7*cm,fill=1,stroke=0)
        canvas.setFont("Helvetica-Bold",7); canvas.setFillColor(C_WHITE)
        canvas.drawString(MARGIN+5,PAGE_H-1.05*cm,"DESIGN HISTORY FILE  ·  LIVE DATABASE DRIVEN")
        canvas.setFont("Helvetica",7)
        canvas.drawRightString(PAGE_W-MARGIN-4,PAGE_H-1.05*cm,
            f"{self.device}  |  {self.model}  |  FDA Class {self.fda}")
        canvas.setStrokeColor(C_RULE); canvas.setLineWidth(0.5)
        canvas.line(MARGIN,1.25*cm,PAGE_W-MARGIN,1.25*cm)
        canvas.setFont("Helvetica",6.5); canvas.setFillColor(C_COOL)
        canvas.drawString(MARGIN,0.85*cm,
            f"Generated {TODAY}  ·  Data: PubMed · FDA · ClinicalTrials · Europe PMC · Semantic Scholar · CORE · Google Scholar · Patents · WIPO · EMA")
        canvas.setFont("Helvetica-Bold",7.5); canvas.setFillColor(C_SLATE)
        canvas.drawRightString(PAGE_W-MARGIN,0.85*cm,f"Page {doc.page}")
        canvas.restoreState()

# ══════════════════════════════════════════════════════════════════════════
# ████  RESEARCH ENGINE — 10 FREE SOURCES  ████
# ══════════════════════════════════════════════════════════════════════════
class ResearchEngine:
    def __init__(self,device,use="",fda_class="II"):
        self.device=device; self.use=use; self.cls=fda_class
        self.q=quote_plus(device)
        self.results={s:[] for s in SOURCE_COLORS}
        self.results["FDA"]={"predicates":[],"recalls":[],"classification":[]}
        self.session=requests.Session(); self.session.headers.update(HEADERS)

    def _get(self,url,params=None,json_r=False,timeout=15):
        for attempt in range(RETRY):
            try:
                r=self.session.get(url,params=params,timeout=timeout)
                if r.status_code==429:
                    w=int(r.headers.get("Retry-After",DELAY*(attempt+2)))
                    print(f"      Rate-limited — waiting {w}s"); time.sleep(w); continue
                if r.status_code==200:
                    return r.json() if json_r else r
                print(f"      HTTP {r.status_code}: {url[:55]}…"); return None
            except Exception as e:
                print(f"      Attempt {attempt+1}: {e}"); time.sleep(DELAY)
        return None

    def fetch_pubmed(self):
        print("  [1/10] PubMed …")
        d=self._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",json_r=True,
            params={"db":"pubmed","term":f"{self.device}[Title/Abstract]","retmax":10,"retmode":"json","sort":"relevance"})
        ids=(d or {}).get("esearchresult",{}).get("idlist",[])
        if not ids:
            d=self._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",json_r=True,
                params={"db":"pubmed","term":self.device,"retmax":8,"retmode":"json"})
            ids=(d or {}).get("esearchresult",{}).get("idlist",[])
        papers=[]
        if ids:
            s=self._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",json_r=True,
                params={"db":"pubmed","id":",".join(ids[:8]),"retmode":"json"})
            for uid in (s or {}).get("result",{}).get("uids",[]):
                it=s["result"].get(uid,{})
                papers.append({"title":it.get("title",""),"authors":", ".join(a.get("name","") for a in it.get("authors",[])[:3]),
                    "journal":it.get("source",""),"year":it.get("pubdate","")[:4],"pmid":uid})
        self.results["PubMed"]=papers; print(f"      → {len(papers)} articles")

    def fetch_fda(self):
        print("  [2/10] FDA openFDA …")
        preds=[]
        d=self._get("https://api.fda.gov/device/510k.json",json_r=True,
            params={"search":f'device_name:"{self.device}"',"limit":8,"sort":"decision_date:desc"})
        for e in (d or {}).get("results",[]):
            preds.append({"k_number":e.get("k_number",""),"device_name":e.get("device_name",""),
                "applicant":e.get("applicant",""),"decision":e.get("decision",""),
                "date":e.get("decision_date","")[:10],"prod_code":e.get("product_code","")})
        recalls=[]
        d2=self._get("https://api.fda.gov/device/recall.json",json_r=True,
            params={"search":f'product_description:"{self.device}"',"limit":5})
        for e in (d2 or {}).get("results",[]):
            recalls.append({"number":e.get("recall_number",""),"class":e.get("recall_class",""),
                "reason":e.get("reason_for_recall",""),"date":e.get("event_date_initiated","")[:10]})
        classif=[]
        d3=self._get("https://api.fda.gov/device/classification.json",json_r=True,
            params={"search":f'device_name:"{self.device}"',"limit":5})
        for e in (d3 or {}).get("results",[]):
            classif.append({"device_name":e.get("device_name",""),"product_code":e.get("product_code",""),
                "device_class":e.get("device_class",""),"regulation_number":e.get("regulation_number","")})
        self.results["FDA"]={"predicates":preds,"recalls":recalls,"classification":classif}
        print(f"      → {len(preds)} predicates, {len(recalls)} recalls")

    def fetch_clinical_trials(self):
        print("  [3/10] ClinicalTrials.gov …")
        d=self._get("https://clinicaltrials.gov/api/v2/studies",json_r=True,
            params={"query.term":self.device,"pageSize":8,
                "fields":"NCTId,BriefTitle,OverallStatus,Phase,EnrollmentCount,StartDate,CompletionDate,BriefSummary,Condition"})
        trials=[]
        for s in (d or {}).get("studies",[]):
            pm=s.get("protocolSection",{})
            id_m=pm.get("identificationModule",{}); st_m=pm.get("statusModule",{})
            ds_m=pm.get("designModule",{}); dc_m=pm.get("descriptionModule",{})
            co_m=pm.get("conditionsModule",{})
            trials.append({"nct_id":id_m.get("nctId",""),"title":id_m.get("briefTitle",""),
                "status":st_m.get("overallStatus",""),"phase":", ".join(ds_m.get("phases",[])),
                "enrollment":str(ds_m.get("enrollmentInfo",{}).get("count","")),
                "conditions":", ".join(co_m.get("conditions",[])[:3]),
                "summary":dc_m.get("briefSummary","")[:200]})
        self.results["ClinicalTrials"]=trials; print(f"      → {len(trials)} trials")

    def fetch_europe_pmc(self):
        print("  [4/10] Europe PMC …")
        d=self._get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",json_r=True,
            params={"query":self.device,"resultType":"lite","pageSize":8,"format":"json","sort":"CITED desc"})
        papers=[]
        for it in (d or {}).get("resultList",{}).get("result",[]):
            papers.append({"title":it.get("title",""),"authors":it.get("authorString",""),
                "journal":it.get("journalTitle",""),"year":str(it.get("pubYear","")),
                "doi":it.get("doi",""),"cited":int(it.get("citedByCount",0)),
                "abstract":(it.get("abstractText") or "")[:200]})
        papers.sort(key=lambda x:x["cited"],reverse=True)
        self.results["Europe PMC"]=papers; print(f"      → {len(papers)} papers")

    def fetch_semantic_scholar(self):
        print("  [5/10] Semantic Scholar …")
        d=self._get("https://api.semanticscholar.org/graph/v1/paper/search",json_r=True,
            params={"query":self.device,"limit":8,"fields":"title,abstract,year,authors,citationCount,externalIds,venue"})
        papers=[]
        for it in (d or {}).get("data",[]):
            papers.append({"title":it.get("title",""),"abstract":(it.get("abstract") or "")[:200],
                "year":str(it.get("year","")),"authors":", ".join(a.get("name","") for a in it.get("authors",[])[:3]),
                "cited":it.get("citationCount",0),"venue":it.get("venue",""),"doi":it.get("externalIds",{}).get("DOI","")})
        papers.sort(key=lambda x:x["cited"],reverse=True)
        self.results["Semantic Scholar"]=papers; print(f"      → {len(papers)} papers")

    def fetch_core(self):
        print("  [6/10] CORE …")
        d=self._get("https://api.core.ac.uk/v3/search/works",json_r=True,params={"q":self.device,"limit":8})
        papers=[]
        for it in (d or {}).get("results",[]):
            papers.append({"title":it.get("title",""),"abstract":(it.get("abstract") or "")[:200],
                "year":str(it.get("yearPublished","")),"doi":it.get("doi","")})
        self.results["CORE"]=papers; print(f"      → {len(papers)} papers")

    def fetch_google_scholar(self):
        print("  [7/10] Google Scholar …")
        r=self._get(f"https://scholar.google.com/scholar?q={self.q}+medical+device&hl=en&num=10")
        papers=[]
        if r:
            soup=BeautifulSoup(r.text,"lxml")
            for div in soup.select(".gs_r.gs_or.gs_scl")[:8]:
                te=div.select_one(".gs_rt a") or div.select_one(".gs_rt")
                me=div.select_one(".gs_a"); se=div.select_one(".gs_rs")
                ce=div.find("a",string=re.compile(r"Cited by"))
                if te:
                    cited=""
                    if ce:
                        m=re.search(r"\d+",ce.get_text()); cited=m.group() if m else ""
                    papers.append({"title":te.get_text(strip=True),"meta":me.get_text(strip=True) if me else "",
                        "snippet":(se.get_text(strip=True)[:200] if se else ""),"cited":cited,
                        "url":te.get("href","") if te.name=="a" else ""})
        self.results["Google Scholar"]=papers; print(f"      → {len(papers)} results")

    def fetch_google_patents(self):
        print("  [8/10] Google Patents …")
        patents=[]
        r=self._get(f"https://patents.google.com/xhr/query?url=q%3D{self.q}%26num%3D10&exp=&tags=")
        if r:
            try:
                data=r.json()
                for cluster in data.get("results",{}).get("cluster",[])[:2]:
                    for item in cluster.get("result",[])[:6]:
                        p=item.get("patent",{})
                        patents.append({"id":p.get("publication_number",""),"title":p.get("title",""),
                            "assignee":", ".join(p.get("assignee",[])[:2]),
                            "inventor":", ".join(p.get("inventor",[])[:2]),
                            "date":p.get("publication_date",""),"abstract":p.get("abstract","")[:200],
                            "country":p.get("country_code","")})
            except Exception:
                pass
        if not patents:
            r2=self._get(f"https://patents.google.com/?q={self.q}&num=10")
            if r2:
                soup=BeautifulSoup(r2.text,"lxml")
                for item in soup.select("article.search-result")[:6]:
                    ti=item.select_one("h3"); ai=item.select_one(".assignee")
                    if ti: patents.append({"id":"","title":ti.get_text(strip=True),
                        "assignee":ai.get_text(strip=True) if ai else "","inventor":"","date":"","abstract":"","country":""})
        self.results["Google Patents"]=patents; print(f"      → {len(patents)} patents")

    def fetch_wipo(self):
        print("  [9/10] WIPO PATENTSCOPE …")
        r=self._get("https://patentscope.wipo.int/search/en/result.jsf",
            params={"query":self.device,"office":"","redir":"true","maxRec":"8","sortOption":"Relevance"})
        patents=[]
        if r:
            soup=BeautifulSoup(r.text,"lxml")
            for row in soup.select(".ps-patent-result,.resultrow")[:8]:
                te=row.select_one(".ps-patent-result--title,.title a,.pdfLink")
                ne=row.select_one(".ps-patent-result--patent-number,.patentNumber")
                de=row.select_one(".ps-patent-result--date,.pubDate")
                if te: patents.append({"title":te.get_text(strip=True)[:100],
                    "number":ne.get_text(strip=True) if ne else "","date":de.get_text(strip=True) if de else "","inventor":""})
        self.results["WIPO"]=patents; print(f"      → {len(patents)} patents")

    def fetch_ema(self):
        print("  [10/10] EMA …")
        guidelines=[]
        r=self._get("https://www.ema.europa.eu/en/search",
            params={"search_api_fulltext":self.device,"f[0]":"content_type:ema_document_type/scientific_guideline"})
        if r:
            soup=BeautifulSoup(r.text,"lxml")
            for el in soup.select(".ecl-content-item__title a,.search-result-title a")[:5]:
                t=el.get_text(strip=True); href=el.get("href","")
                if t and len(t)>5:
                    guidelines.append({"title":t,"url":href if href.startswith("http") else "https://www.ema.europa.eu"+href,"type":"Guideline"})
        for page_url in ["https://www.ema.europa.eu/en/human-regulatory-overview/research-development/scientific-guidelines"]:
            r2=self._get(page_url)
            if r2:
                soup2=BeautifulSoup(r2.text,"lxml")
                for a in soup2.select("a.ecl-link,.ecl-content-item a")[:8]:
                    t=a.get_text(strip=True)
                    if len(t)>8 and any(kw in t.lower() for kw in ["device","clinical","safety","validation","guidance","guideline","medical"]):
                        href=a.get("href","")
                        if not any(g["title"]==t for g in guidelines):
                            guidelines.append({"title":t[:120],"url":href if href.startswith("http") else "https://www.ema.europa.eu"+href,"type":"EMA Resource"})
        self.results["EMA"]=guidelines[:10]; print(f"      → {len(guidelines)} EMA resources")

    def run_all(self):
        bar="═"*62
        print(f"\n{bar}\n  RESEARCH ENGINE — {self.device}\n{bar}")
        for fn in [self.fetch_pubmed,self.fetch_fda,self.fetch_clinical_trials,
                   self.fetch_europe_pmc,self.fetch_semantic_scholar,self.fetch_core,
                   self.fetch_google_scholar,self.fetch_google_patents,self.fetch_wipo,self.fetch_ema]:
            try: fn()
            except Exception as e: print(f"      [ERROR] {fn.__name__}: {e}")
            time.sleep(DELAY)
        total=self._count()
        print(f"{bar}\n  Total records: {total}\n{bar}\n")
        return self.results

    def _count(self):
        n=0
        for v in self.results.values():
            if isinstance(v,list): n+=len(v)
            elif isinstance(v,dict): n+=sum(len(vv) for vv in v.values() if isinstance(vv,list))
        return n

    def db_counts(self):
        counts={}
        for src in SOURCE_COLORS:
            v=self.results.get(src,[])
            if isinstance(v,list): counts[src]=len(v)
            elif isinstance(v,dict): counts[src]=sum(len(vv) for vv in v.values() if isinstance(vv,list))
            else: counts[src]=0
        return counts

    # ── Smart extraction ──────────────────────────────────────────────────
    def extract_user_needs(self):
        needs=[]; seen=set()
        for t in self.results.get("ClinicalTrials",[]):
            for cond in t.get("conditions","").split(","):
                cond=cond.strip()
                if cond and cond not in seen and len(cond)>3:
                    needs.append({"id":f"UN-{len(needs)+1:03d}","need":f"Device must support management of {cond}",
                        "user":"Clinician / Patient","source":f"ClinicalTrials {t['nct_id']}"})
                    seen.add(cond)
        for p in self.results.get("PubMed",[]):
            for kw in ["accuracy","safety","efficacy","sensitivity","specificity","reliability","usability","monitoring","detection"]:
                if kw in p.get("title","").lower() and kw not in seen:
                    needs.append({"id":f"UN-{len(needs)+1:03d}","need":f"Device must demonstrate high {kw} in clinical use",
                        "user":"Clinician","source":f"PubMed PMID:{p['pmid']}"})
                    seen.add(kw)
        for p in self.results.get("Semantic Scholar",[]):
            for kw in ["non-invasive","continuous","portable","wearable","real-time","wireless"]:
                if kw in (p.get("abstract","")+p.get("title","")).lower() and kw not in seen:
                    needs.append({"id":f"UN-{len(needs)+1:03d}","need":f"Device should support {kw} operation",
                        "user":"Clinical User","source":f"Semantic Scholar — {trunc(p['title'],40)}"})
                    seen.add(kw)
        if not needs:
            needs=[{"id":"UN-001","need":f"Device must perform primary {self.device} function safely","user":"Clinician","source":"Regulatory baseline"},
                   {"id":"UN-002","need":"Device must be usable by intended clinical staff without extensive training","user":"Nurse/Technician","source":"IEC 62366-1"},
                   {"id":"UN-003","need":"Device must integrate with existing clinical information systems","user":"IT/Admin","source":"Market analysis"}]
        return needs[:8]

    def extract_hazards(self):
        hazards=[]
        for r in (self.results.get("FDA") or {}).get("recalls",[]):
            cls=r.get("class",""); sev={"Class I":5,"Class II":3,"Class III":2}.get(cls,3)
            hazards.append({"label":f"H{len(hazards)+1}","hazard":"Device failure/malfunction",
                "cause":trunc(r.get("reason",""),60),"harm":"Patient injury or delayed treatment",
                "sev":sev,"prob_initial":2,"sev_residual":sev,"prob_residual":1,"det":2,
                "level":"Unacceptable" if sev>=5 else "ALARP","control":"Enhanced design validation","source":f"FDA Recall {r.get('number','')}"},)
        kw_map={"alarm":("Alarm fatigue/missed alert","Patient deterioration undetected",4,3),
                "interference":("EMI/interference","Erroneous readings",4,2),"software":("SW malfunction","Incorrect data",4,2),
                "battery":("Power failure","Device shutdown in use",4,2),"calibration":("Calibration drift","Inaccurate measurements",3,3),
                "infection":("Device-associated infection","Patient infection",4,2),"lead":("Lead/probe failure","Signal loss",3,3),
                "skin":("Skin irritation","Patient discomfort",2,4)}
        seen=set()
        for src in ["PubMed","Semantic Scholar","Europe PMC"]:
            for p in self.results.get(src,[]):
                txt=(p.get("title","")+p.get("abstract","")).lower()
                for kw,(haz,harm,sev,prob) in kw_map.items():
                    if kw in txt and kw not in seen:
                        prob_r=max(1,prob-1); level="Unacceptable" if sev*prob>=15 else "ALARP" if sev*prob>=6 else "Acceptable"
                        hazards.append({"label":f"H{len(hazards)+1}","hazard":haz,"cause":f"{kw.capitalize()} — from literature",
                            "harm":harm,"sev":sev,"prob_initial":prob,"sev_residual":sev,"prob_residual":prob_r,"det":2,
                            "level":level,"control":"Design control + test protocol","source":src})
                        seen.add(kw)
        if len(hazards)<3:
            hazards+=[{"label":f"H{len(hazards)+1}","hazard":"Biocompatibility reaction","cause":"Material patient contact",
                "harm":"Allergic/toxic reaction","sev":3,"prob_initial":2,"sev_residual":3,"prob_residual":1,"det":2,
                "level":"ALARP","control":"ISO 10993 biocompatibility testing","source":"ISO 10993-1"},
                {"label":f"H{len(hazards)+2}","hazard":"Use error","cause":"Incorrect operator action",
                "harm":"Delayed/incorrect treatment","sev":3,"prob_initial":3,"sev_residual":3,"prob_residual":2,"det":3,
                "level":"ALARP","control":"IEC 62366-1 usability engineering","source":"IEC 62366-1"}]
        return hazards[:8]

    def clinical_summary(self):
        lines=[]
        pm=self.results.get("PubMed",[])
        if pm: lines.append(f"PubMed returned {len(pm)} relevant publications. Key article: {trunc(pm[0]['title'],80)} ({pm[0]['year']}, {pm[0]['journal']}).")
        ct=self.results.get("ClinicalTrials",[])
        if ct:
            active=[t for t in ct if "RECRUIT" in t.get("status","").upper()]
            comp=[t for t in ct if "COMPLET" in t.get("status","").upper()]
            lines.append(f"ClinicalTrials.gov: {len(ct)} studies ({len(active)} recruiting, {len(comp)} completed).")
            if ct: lines.append(f"Notable: {trunc(ct[0]['title'],70)} ({ct[0]['nct_id']}, n={ct[0]['enrollment']}).")
        emc=self.results.get("Europe PMC",[])
        if emc:
            top=sorted(emc,key=lambda x:x["cited"],reverse=True)[:1]
            lines.append(f"Europe PMC top-cited: {trunc(top[0]['title'],60)} ({top[0]['year']}, cited {top[0]['cited']}x).")
        ss=self.results.get("Semantic Scholar",[])
        if ss: lines.append(f"Semantic Scholar: {len(ss)} papers. Top: {trunc(ss[0]['title'],50)} ({ss[0]['cited']} citations).")
        if not lines: lines.append(f"No clinical literature retrieved for '{self.device}'. Manual literature search required.")
        return " ".join(lines)

    def patent_summary(self):
        gp=self.results.get("Google Patents",[]); wp=self.results.get("WIPO",[])
        all_p=gp+wp
        if not all_p: return "No patents retrieved. Manual patent search via USPTO/EPO/WIPO recommended."
        assignees=[p.get("assignee","") for p in gp if p.get("assignee")]
        text=f"{len(all_p)} patents identified across Google Patents and WIPO PATENTSCOPE. "
        if assignees:
            top=list(dict.fromkeys(assignees))[:4]
            text+=f"Key assignees: {', '.join(top)}. "
        text+="Freedom-to-operate analysis by qualified patent counsel recommended before commercialisation."
        return text

    def extract_standards(self,intake):
        stds=[{"standard":"ISO 13485:2016","scope":"Quality Management System","applicable":"Yes"},
              {"standard":"ISO 14971:2019","scope":"Risk Management","applicable":"Yes"},
              {"standard":"IEC 62366-1:2015+AMD1","scope":"Usability Engineering","applicable":"Yes"},
              {"standard":"21 CFR Part 820","scope":"FDA Quality System","applicable":"Yes" if "US" in intake.get("target_markets",[]) else "No"},
              {"standard":"EU MDR 2017/745","scope":"EU Market Authorization","applicable":"Yes" if "EU" in intake.get("target_markets",[]) else "No"}]
        if intake.get("contains_software"):
            stds+=[{"standard":"IEC 62304:2006+AMD1","scope":"Software Lifecycle","applicable":"Yes"},
                   {"standard":"IEC 81001-5-1:2021","scope":"Cybersecurity","applicable":"Yes"}]
        if intake.get("electromedical"):
            stds+=[{"standard":"IEC 60601-1:2005+AMD2","scope":"Electrical Safety","applicable":"Yes"},
                   {"standard":"IEC 60601-1-2:2014+AMD1","scope":"EMC","applicable":"Yes"}]
        if intake.get("patient_contacting"):
            stds.append({"standard":"ISO 10993-1:2018","scope":"Biocompatibility","applicable":"Yes"})
        if intake.get("sterile"):
            stds.append({"standard":"ISO 11135/11137","scope":"Sterilization Validation","applicable":"Yes"})
        if intake.get("reusable"):
            stds.append({"standard":"ISO 17664-1:2021","scope":"Reprocessing Instructions","applicable":"Yes"})
        if intake.get("implantable"):
            stds.append({"standard":"ISO 14630","scope":"Non-active Surgical Implants","applicable":"Yes"})
        for g in self.results.get("EMA",[])[:2]:
            stds.append({"standard":trunc(g["title"],45),"scope":"EMA Guidance","applicable":"Review"})
        return stds

# ══════════════════════════════════════════════════════════════════════════
# PDF SECTIONS
# ══════════════════════════════════════════════════════════════════════════
def cover_page(story,intake,engine):
    total=engine._count(); markets=", ".join(intake.get("target_markets",[]))
    hero=Table([[Paragraph(intake["device_name"],ST["cover_title"])]],colWidths=[CONTENT_W])
    hero.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_NAVY),("TOPPADDING",(0,0),(-1,-1),36),
        ("BOTTOMPADDING",(0,0),(-1,-1),36),("ROUNDEDCORNERS",(0,0),(-1,-1),[8,8,8,8])]))
    accent=Table([[""]],colWidths=[CONTENT_W],rowHeights=[0.22*cm])
    accent.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_TEAL)]))
    meta_rows=[
        [Paragraph("Document Type",ST["label"]), Paragraph("Design History File (DHF) — Live Database Generated",ST["value"])],
        [Paragraph("Model Number",ST["label"]),  Paragraph(intake.get("model_number","[TBD]"),ST["value"])],
        [Paragraph("FDA Class",ST["label"]),     Paragraph(f"Class {intake.get('fda_class','?')}",ST["value"])],
        [Paragraph("EU MDR Class",ST["label"]),  Paragraph(f"Class {intake.get('eu_mdr_class','?')}",ST["value"])],
        [Paragraph("Target Markets",ST["label"]),Paragraph(markets,ST["value"])],
        [Paragraph("Manufacturer",ST["label"]),  Paragraph(intake.get("manufacturer","[TBD]"),ST["value"])],
        [Paragraph("Data Sources",ST["label"]),  Paragraph("PubMed · FDA · ClinicalTrials · Europe PMC · Semantic Scholar · CORE · Google Scholar · Google Patents · WIPO · EMA",ST["value"])],
        [Paragraph("Records Retrieved",ST["label"]),Paragraph(f"{total} live records from 10 databases",ST["value"])],
        [Paragraph("Generated",ST["label"]),     Paragraph(TODAY,ST["value"])],
    ]
    meta=Table(meta_rows,colWidths=[4.5*cm,CONTENT_W-4.5*cm])
    meta.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ROWBACKGROUNDS",(0,0),(-1,-1),[C_WHITE,C_SHADE]),
        ("LINEBELOW",(0,0),(-1,-1),0.35,C_RULE),("BOX",(0,0),(-1,-1),0.5,C_RULE),
        ("LEFTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    story+=[sp(28),hero,accent,sp(14),Paragraph("Design History File  ·  Live Database Driven",ST["cover_tag"]),sp(22),meta,sp(18),PageBreak()]

def toc_page(story):
    sections=[
        ("1","Research Evidence Overview",      "sec1","10 Live Databases"),
        ("2","Device Profile & Classification", "sec2","21 CFR §820.30(b) · ISO 13485 §7.3.2"),
        ("3","Design Inputs & User Needs",      "sec3","21 CFR §820.30(c) · Clinical Evidence"),
        ("4","Design Outputs",                  "sec4","21 CFR §820.30(d) · ISO 13485 §7.3.4"),
        ("5","Design Verification",             "sec5","21 CFR §820.30(f) · ISO 13485 §7.3.6"),
        ("6","Risk Management File",            "sec6","ISO 14971:2019 · FDA Recall Data"),
        ("7","Clinical Evidence Summary",       "sec7","PubMed · Europe PMC · ClinicalTrials"),
        ("8","Predicate Device Analysis",       "sec8","FDA 510(k) Database"),
        ("9","Patent Landscape",                "sec9","Google Patents · WIPO PATENTSCOPE"),
        ("10","Regulatory Traceability Matrix", "sec10","21 CFR §820.30(j) · EU MDR Annex II"),
        ("A","Applicable Standards",            "secA","ISO · IEC · FDA · EMA"),
    ]
    story+=[Bookmark("toc","Table of Contents"),anchor("toc"),Paragraph("Table of Contents",ST["h1"]),hr(1.5,C_NAVY),sp(6)]
    for num,title,key,refs in sections:
        row=Table([[Paragraph(f'<link href="#{key}"><b>{num}</b></link>',ST["toc"]),
                    Paragraph(f'<link href="#{key}">{title}</link>',ST["toc"]),
                    Paragraph(refs,ST["toc_sub"])]],colWidths=[1.0*cm,8.5*cm,CONTENT_W-9.5*cm])
        row.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),3),
            ("BOTTOMPADDING",(0,0),(-1,-1),3),("LINEBELOW",(0,0),(-1,-1),0.25,C_RULE)]))
        story.append(row)
    story.append(PageBreak())

def sec_research(story,engine,imgs):
    sec_hdr(story,1,"Research Evidence Overview","sec1","Live data from 10 free databases")
    fda=engine.results.get("FDA",{})
    story+=[reg_ref("PubMed","FDA","ClinicalTrials","Europe PMC","Semantic Scholar","CORE","Google Scholar","Google Patents","WIPO","EMA"),sp(4),
        Paragraph(f"This DHF was built from real-time data retrieved from 10 authoritative free databases on {TODAY}. All content is specific to the queried device.",ST["body"]),sp(6),
        Paragraph("1.1 Records Retrieved Per Source",ST["h2"]),
        KeepTogether([svg_img(imgs["evidence"],CONTENT_W,4.0*cm),
            Paragraph("Figure 1.1 — Live records retrieved per database for this device query.",ST["caption"])]),sp(6),
        Paragraph("1.2 Database Coverage",ST["h2"]),
        grid(["Source","Records","Content","Access"],
            [["PubMed",str(len(engine.results.get("PubMed",[]))),"Clinical literature, safety studies","NCBI E-utilities API"],
             ["FDA openFDA",str(len(fda.get("predicates",[]))+len(fda.get("recalls",[]))),"510(k)s, recalls, classifications","FDA openFDA API"],
             ["ClinicalTrials",str(len(engine.results.get("ClinicalTrials",[]))),"Clinical trials, enrollment","ClinicalTrials.gov API v2"],
             ["Europe PMC",str(len(engine.results.get("Europe PMC",[]))),"Biomedical papers (by citations)","EBI REST API"],
             ["Semantic Scholar",str(len(engine.results.get("Semantic Scholar",[]))),"Research with citation counts","S2 Graph API"],
             ["CORE",str(len(engine.results.get("CORE",[]))),"Open-access publications","CORE API v3"],
             ["Google Scholar",str(len(engine.results.get("Google Scholar",[]))),"Broad literature, cited counts","Web scrape"],
             ["Google Patents",str(len(engine.results.get("Google Patents",[]))),"Design prior art, competitors","Web scrape"],
             ["WIPO PATENTSCOPE",str(len(engine.results.get("WIPO",[]))),"International PCT patents","Web scrape"],
             ["EMA",str(len(engine.results.get("EMA",[]))),"EU regulatory guidelines","Web scrape"]],
            widths=[3.0*cm,1.8*cm,6.0*cm,CONTENT_W-10.8*cm]),
        sp(4),src_line(list(SOURCE_COLORS.keys())),PageBreak()]

def sec_device_profile(story,intake,engine,imgs):
    sec_hdr(story,2,"Device Profile & Classification","sec2","21 CFR §820.30(b) · ISO 13485 §7.3.2")
    story+=[reg_ref("21 CFR §820.30(b)","ISO 13485:2016 §7.3.2","EU MDR Annex II §3"),sp(6),
        Paragraph("2.1 Device Identification",ST["h2"]),
        kv_table([("Device Name",intake["device_name"]),("Model Number",intake.get("model_number","")),
            ("Intended Use",intake.get("intended_use","")),("Indications for Use",intake.get("indications_for_use","")),
            ("FDA Classification",f"Class {intake.get('fda_class','?')}"),("EU MDR Classification",f"Class {intake.get('eu_mdr_class','?')}"),
            ("Target Markets",", ".join(intake.get("target_markets",[])))],lw=5.0*cm),sp(8),
        Paragraph("2.2 Design Control V-Model",ST["h2"]),
        KeepTogether([svg_img(imgs["vmodel"],CONTENT_W,5.5*cm),
            Paragraph("Figure 2.1 — Design Control V-Model. Dashed arrows show bidirectional V&V traceability.",ST["caption"])]),
        sp(4),src_line(["FDA","EMA"]),PageBreak()]

def sec_design_inputs(story,intake,engine,imgs):
    sec_hdr(story,3,"Design Inputs & User Needs","sec3","21 CFR §820.30(c) · ISO 13485 §7.3.3")
    un=engine.extract_user_needs()
    story+=[reg_ref("21 CFR §820.30(c)","ISO 13485:2016 §7.3.3","EU MDR Annex I (GSPR)"),sp(6),
        Paragraph("3.1 User Needs (Derived from Live Clinical Evidence)",ST["h2"]),
        Paragraph("User needs were derived by analysing clinical trial conditions, PubMed abstracts, and Semantic Scholar data in real time.",ST["body"]),sp(4),
        grid(["UN-ID","User Need Statement","User Type","Evidence Source"],
             [[n["id"],n["need"],n["user"],n["source"]] for n in un],
             widths=[1.5*cm,6.5*cm,2.8*cm,CONTENT_W-10.8*cm]),
        sp(4),src_line(["ClinicalTrials","PubMed","Semantic Scholar"]),sp(8),
        Paragraph("3.2 Functional Requirements",ST["h2"]),
        grid(["DI-ID","Requirement","Source","Acceptance Criterion","Method"],
            [["DI-F-001","Primary functional performance","UN-001","Per applicable standard","Bench test"],
             ["DI-F-002","Accuracy / precision","UN-001","±X% (literature benchmark)","Measurement test"],
             ["DI-F-003","Response time","UN-001","&lt; X seconds","Timing test"],
             ["DI-F-004","Alarm/alert performance","UN-002","Per IEC 60601-1-8","Functional test"]]
            +([["DI-E-001","Basic electrical safety","Regulatory","IEC 60601-1 Table 6","HiPot"],
               ["DI-E-002","EMC — emissions & immunity","Regulatory","IEC 60601-1-2","EMC lab"]] if intake.get("electromedical") else [])
            +([["DI-S-001","SW safety class determination","IEC 62304","Class A/B/C per FMEA","Design review"]] if intake.get("contains_software") else []),
            widths=[1.8*cm,4.5*cm,2.0*cm,3.5*cm,CONTENT_W-11.8*cm]),
        sp(4),src_line(["PubMed","Semantic Scholar","FDA"])]

    if intake.get("patient_contacting") and "biocompat" in imgs:
        story+=[sp(8),Paragraph("3.3 Biocompatibility Evaluation Flow",ST["h2"]),
            KeepTogether([svg_img(imgs["biocompat"],CONTENT_W,5.5*cm),
                Paragraph("Figure 3.1 — Biocompatibility evaluation pathway per ISO 10993-1.",ST["caption"])]),
            sp(4),src_line(["FDA"])]

    if intake.get("contains_software") and "sw_class" in imgs:
        story+=[sp(8),Paragraph("3.4 Software Safety Classification",ST["h2"]),
            KeepTogether([svg_img(imgs["sw_class"],CONTENT_W,5.5*cm),
                Paragraph("Figure 3.2 — IEC 62304 software safety classification decision tree.",ST["caption"])]),
            sp(4),src_line(["FDA"])]

    story.append(PageBreak())

def sec_design_outputs(story,intake):
    sec_hdr(story,4,"Design Outputs","sec4","21 CFR §820.30(d) · ISO 13485 §7.3.4")
    story+=[reg_ref("21 CFR §820.30(d)","ISO 13485:2016 §7.3.4"),sp(6),
        Paragraph("4.1 Device Master Record (DMR) Index",ST["h2"]),
        grid(["DMR-ID","Document Title","Type","Rev","Status"],
            [["DMR-DWG","Engineering Drawings & Assembly","Drawing Set","A","In Preparation"],
             ["DMR-BOM","Bill of Materials","BOM","A","In Preparation"],
             ["DMR-SPC","Material & Component Specifications","Spec","A","In Preparation"],
             ["DMR-MFG","Manufacturing & Assembly Procedures","SOP","A","In Preparation"],
             ["DMR-QCP","Quality Control Plans","QCP","A","In Preparation"],
             ["DMR-LBL","Labelling & Instructions for Use","Document","A","In Preparation"],
             ["DMR-PKG","Packaging Specification","Spec","A","In Preparation"]]
            +([["DMR-SFW","Software Release Package","SW Package","A","In Preparation"]] if intake.get("contains_software") else []),
            widths=[2.0*cm,6.5*cm,2.8*cm,1.0*cm,CONTENT_W-12.3*cm]),
        sp(4),src_line(["FDA"]),PageBreak()]

def sec_verification(story,intake):
    sec_hdr(story,5,"Design Verification Protocols","sec5","21 CFR §820.30(f) · ISO 13485 §7.3.6")
    rows=[["DV-001","DI-F-001","Primary functional performance test","[Standard]","Per spec","n=10","Planned"],
          ["DV-002","DI-F-002","Accuracy & precision","[Standard]","±X%","n=30","Planned"],
          ["DV-003","DI-F-003","Response time measurement","[Standard]","&lt;X sec","n=10","Planned"],
          ["DV-004","DI-F-004","Alarm performance","IEC 60601-1-8","Pass","n=5","Planned"],
          ["DV-005","DI-F-001","Environmental conditioning","IEC 60068-2","Pass","n=5","Planned"]]
    if intake.get("electromedical"):
        rows+=[["DV-E01","DI-E-001","Electrical safety — dielectric","IEC 60601-1","Pass","n=5","Planned"],
               ["DV-E02","DI-E-002","EMC radiated emissions","IEC 60601-1-2","Pass","n=3","Planned"]]
    if intake.get("contains_software"):
        rows+=[["DV-S01","DI-S-001","Software unit & integration tests","IEC 62304","Pass","N/A","Planned"]]
    story+=[reg_ref("21 CFR §820.30(f)","ISO 13485:2016 §7.3.6"),sp(6),
        Paragraph("5.1 Verification Test Matrix",ST["h2"]),
        grid(["DV-ID","DI-Ref","Test Description","Standard","Criterion","n","Status"],rows,
            widths=[1.8*cm,1.8*cm,4.5*cm,3.0*cm,2.5*cm,1.0*cm,CONTENT_W-14.6*cm]),
        sp(4),src_line(["FDA","PubMed"]),PageBreak()]

def sec_risk(story,engine,imgs):
    sec_hdr(story,6,"Risk Management File","sec6","ISO 14971:2019 · FDA Recall Data")
    hazards=engine.extract_hazards()
    story+=[reg_ref("ISO 14971:2019","ISO/TR 24971:2020","21 CFR §820.30(g)"),sp(6),
        Paragraph("6.1 Risk Management Process (ISO 14971:2019)",ST["h2"]),
        KeepTogether([svg_img(imgs["iso14971"],CONTENT_W,5.5*cm),
            Paragraph("Figure 6.1 — ISO 14971:2019 Risk Management Process. Arrows show the process flow and post-market feedback loop.",ST["caption"])]),
        sp(6),
        Paragraph("6.2 Hazard Analysis (Derived from FDA Recall Data & Literature)",ST["h2"]),
        Paragraph("Hazards identified from live FDA recall records and published clinical literature retrieved in real time.",ST["body"]),sp(4),
        grid(["#","Hazard","Cause","Harm","S","P","Risk Level","Control","Source"],
            [[hz["label"],hz["hazard"],trunc(hz["cause"],35),hz["harm"],
              str(hz["sev"]),str(hz["prob_initial"]),hz["level"],trunc(hz["control"],35),hz.get("source","")] for hz in hazards],
            widths=[0.7*cm,2.5*cm,2.8*cm,2.5*cm,0.5*cm,0.5*cm,2.0*cm,2.8*cm,CONTENT_W-14.3*cm],small=True),
        sp(6),
        Paragraph("6.3 Risk Acceptability Matrix — Device Hazards Plotted",ST["h2"]),
        KeepTogether([svg_img(imgs["risk_matrix"],CONTENT_W,7.0*cm),
            Paragraph("Figure 6.2 — Red dots: initial risk. Green dots: residual risk after controls. Arrows show risk reduction. Positions derived from FDA recall class and literature severity data.",ST["caption"])]),
        sp(6),
        Paragraph("6.4 FMEA Risk Priority Numbers",ST["h2"]),
        KeepTogether([svg_img(imgs["fmea_chart"],CONTENT_W,4.5*cm),
            Paragraph("Figure 6.3 — FMEA RPN overview. Green = Acceptable, Amber = ALARP, Red = Unacceptable. SME confirmation required.",ST["caption"])]),
        sp(4),src_line(["FDA","PubMed","Europe PMC","Semantic Scholar"]),PageBreak()]

def sec_clinical(story,engine,imgs):
    sec_hdr(story,7,"Clinical Evidence Summary","sec7","PubMed · ClinicalTrials · Europe PMC")
    story+=[reg_ref("EU MDR Annex XIV","MEDDEV 2.7/1 rev.4","21 CFR §820.30(g)"),sp(6),
        Paragraph("7.1 Evidence Summary",ST["h2"]),
        Paragraph(engine.clinical_summary(),ST["body"]),
        sp(4),src_line(["PubMed","ClinicalTrials","Europe PMC","Semantic Scholar"]),sp(6),
        Paragraph("7.2 PubMed Articles",ST["h2"])]
    pm=engine.results.get("PubMed",[])
    if pm:
        story.append(grid(["Year","Title","Authors","Journal","PMID"],
            [[p["year"],trunc(p["title"],55),trunc(p["authors"],32),trunc(p["journal"],22),p["pmid"]] for p in pm[:6]],
            widths=[1.2*cm,7.0*cm,4.0*cm,2.8*cm,CONTENT_W-15.0*cm]))
    story+=[sp(6),Paragraph("7.3 Clinical Trials",ST["h2"])]
    ct=engine.results.get("ClinicalTrials",[])
    if ct:
        story.append(grid(["NCT-ID","Title","Status","Phase","n","Conditions"],
            [[t["nct_id"],trunc(t["title"],42),t["status"],t["phase"],t["enrollment"],trunc(t["conditions"],28)] for t in ct[:5]],
            widths=[2.2*cm,5.2*cm,2.5*cm,2.0*cm,1.0*cm,CONTENT_W-12.9*cm]))
    story+=[sp(6),Paragraph("7.4 Europe PMC High-Impact Papers",ST["h2"])]
    emc=engine.results.get("Europe PMC",[])
    if emc:
        story.append(grid(["Year","Title","Authors","Cited","DOI"],
            [[p["year"],trunc(p["title"],50),trunc(p["authors"],28),str(p["cited"]),trunc(p["doi"],25)] for p in emc[:5]],
            widths=[1.2*cm,6.2*cm,3.8*cm,1.5*cm,CONTENT_W-12.7*cm]))
    story+=[sp(4),src_line(["PubMed","ClinicalTrials","Europe PMC","Semantic Scholar","CORE"]),PageBreak()]

def sec_predicates(story,engine):
    sec_hdr(story,8,"Predicate Device Analysis","sec8","FDA 510(k) Database")
    story+=[reg_ref("21 CFR §807.92","FDA Guidance: 510(k) Program (2014)"),sp(6),
        Paragraph("8.1 FDA 510(k) Predicate Devices (Live Data)",ST["h2"])]
    preds=(engine.results.get("FDA") or {}).get("predicates",[])
    if preds:
        story.append(grid(["K-Number","Device Name","Applicant","Decision","Date","Code"],
            [[p["k_number"],trunc(p["device_name"],42),trunc(p["applicant"],28),p["decision"],p["date"],p["prod_code"]] for p in preds],
            widths=[2.0*cm,5.5*cm,3.8*cm,2.2*cm,2.0*cm,CONTENT_W-15.5*cm]))
    else:
        story.append(info_box("No FDA 510(k) predicates found. Search directly at https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm",accent=C_AMBER,bg=HexColor("#FFFBEB")))
    story+=[sp(6),Paragraph("8.2 FDA Recall Records",ST["h2"])]
    recalls=(engine.results.get("FDA") or {}).get("recalls",[])
    if recalls:
        story.append(grid(["Recall #","Class","Date","Reason"],
            [[r["number"],r["class"],r["date"],trunc(r["reason"],75)] for r in recalls],
            widths=[2.5*cm,1.8*cm,2.2*cm,CONTENT_W-6.5*cm]))
    else:
        story.append(Paragraph("No FDA recall records found for this device.",ST["body"]))
    story+=[sp(4),src_line(["FDA"]),PageBreak()]

def sec_patents(story,engine):
    sec_hdr(story,9,"Patent Landscape","sec9","Google Patents · WIPO PATENTSCOPE")
    story+=[reg_ref("Google Patents","WIPO PATENTSCOPE"),sp(6),
        Paragraph("9.1 Patent Landscape Summary",ST["h2"]),
        Paragraph(engine.patent_summary(),ST["body"]),
        sp(4),src_line(["Google Patents","WIPO"]),sp(6),
        Paragraph("9.2 Google Patents",ST["h2"])]
    gp=engine.results.get("Google Patents",[])
    if gp:
        story.append(grid(["Patent ID","Title","Assignee","Inventor","Date"],
            [[trunc(p.get("id",""),18),trunc(p.get("title",""),48),trunc(p.get("assignee",""),26),trunc(p.get("inventor",""),22),trunc(p.get("date",""),12)] for p in gp[:6]],
            widths=[2.5*cm,5.5*cm,3.5*cm,3.0*cm,CONTENT_W-14.5*cm]))
    else:
        story.append(Paragraph("No Google Patents results retrieved.",ST["body"]))
    story+=[sp(6),Paragraph("9.3 WIPO PATENTSCOPE",ST["h2"])]
    wp=engine.results.get("WIPO",[])
    if wp:
        story.append(grid(["Patent Number","Title","Inventor","Date"],
            [[p.get("number",""),trunc(p.get("title",""),55),trunc(p.get("inventor",""),25),p.get("date","")] for p in wp[:6]],
            widths=[2.5*cm,7.0*cm,3.5*cm,CONTENT_W-13.0*cm]))
    else:
        story.append(Paragraph("No WIPO results retrieved.",ST["body"]))
    story+=[sp(4),src_line(["Google Patents","WIPO"]),PageBreak()]

def sec_traceability(story,engine,imgs):
    sec_hdr(story,10,"Regulatory Traceability Matrix","sec10","21 CFR §820.30(j) · EU MDR Annex II")
    un=engine.extract_user_needs()
    story+=[reg_ref("21 CFR §820.30(j)","ISO 13485:2016 §7.3.10","EU MDR Annex II"),sp(6),
        KeepTogether([svg_img(imgs["traceability"],CONTENT_W,2.8*cm),
            Paragraph("Figure 10.1 — DHF Traceability Chain. All nodes must be fully populated before DHF closure.",ST["caption"])]),
        sp(6),Paragraph("10.1 Master Traceability Matrix",ST["h2"]),
        grid(["UN-ID","User Need","DI-ID","Design Input","DO-ID","Design Output","DV-ID","Verification","Risk-ID"],
            [[n["id"],trunc(n["need"],28),f"DI-F-{i+1:03d}","[Confirm]",f"DO-{i+1:03d}","[Confirm]",f"DV-{i+1:03d}","[Confirm]",f"R-{i+1:03d}"] for i,n in enumerate(un[:5])],
            widths=[1.2*cm,3.5*cm,1.4*cm,1.9*cm,1.4*cm,1.9*cm,1.4*cm,1.9*cm,1.2*cm]),
        sp(4),src_line(["PubMed","FDA","ClinicalTrials"]),PageBreak()]

def sec_standards(story,engine,intake,imgs):
    sec_hdr(story,"A","Applicable Standards","secA","ISO · IEC · FDA · EMA")
    stds=engine.extract_standards(intake)
    story+=[reg_ref("ISO","IEC","FDA","EMA"),sp(6),
        Paragraph("A.1 Standards Applicability Matrix (Device-Specific)",ST["h2"]),
        grid(["Standard","Scope","Applicable?"],
            [[s["standard"],s["scope"],s["applicable"]] for s in stds],
            widths=[5.5*cm,7.5*cm,CONTENT_W-13.0*cm]),
        sp(6),Paragraph("A.2 Regulatory Pathways",ST["h2"]),
        KeepTogether([svg_img(imgs["reg_map"],CONTENT_W,4.5*cm),
            Paragraph("Figure A.1 — Target market regulatory pathway overview.",ST["caption"])]),
        sp(6),Paragraph("A.3 EMA Guidelines Retrieved",ST["h2"])]
    ema=engine.results.get("EMA",[])
    if ema:
        story.append(grid(["#","EMA Guideline / Resource","Type"],
            [[str(i+1),trunc(g["title"],85),g.get("type","Guideline")] for i,g in enumerate(ema)],
            widths=[0.8*cm,CONTENT_W-3.8*cm,3.0*cm]))
    story+=[sp(6),info_box("All content is derived from real-time public database queries. Quantified acceptance criteria, sample sizes, and device-specific technical parameters must be confirmed by qualified SMEs before regulatory submission.",accent=C_AZURE,bg=C_SHADE2)]

# ══════════════════════════════════════════════════════════════════════════
# DIAGRAM GENERATION
# ══════════════════════════════════════════════════════════════════════════
def generate_diagrams(intake,hazards,db_counts,tmp):
    # Import the diagrams module (same directory as this script)
    import importlib.util
    script_dir = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("diagrams", os.path.join(script_dir,"diagrams.py"))
    D = importlib.util.module_from_spec(spec); spec.loader.exec_module(D)

    device=intake["device_name"]
    contact="Implant" if intake.get("implantable") else ("Surface/External" if intake.get("patient_contacting") else "None")
    duration="Long-term (>30d)" if intake.get("implantable") else "Limited (≤24h) / Prolonged (24h–30d)"

    imgs={}
    imgs["vmodel"]       = D.gen_vmodel(device, os.path.join(tmp,"vmodel.svg"))
    imgs["iso14971"]     = D.gen_iso14971(os.path.join(tmp,"iso14971.svg"))
    imgs["risk_matrix"]  = D.gen_risk_matrix(hazards, os.path.join(tmp,"risk_matrix.svg"))
    imgs["traceability"] = D.gen_traceability_chain(os.path.join(tmp,"traceability.svg"))
    imgs["fmea_chart"]   = D.gen_fmea_chart(hazards, os.path.join(tmp,"fmea_chart.svg"))
    imgs["reg_map"]      = D.gen_regulatory_map(intake.get("target_markets",[]), os.path.join(tmp,"reg_map.svg"))
    imgs["evidence"]     = D.gen_evidence_chart(db_counts, os.path.join(tmp,"evidence.svg"))
    if intake.get("patient_contacting"):
        imgs["biocompat"] = D.gen_biocompat_flow(contact, duration, os.path.join(tmp,"biocompat.svg"))
    if intake.get("contains_software"):
        imgs["sw_class"]  = D.gen_sw_classification(os.path.join(tmp,"sw_class.svg"))
    return imgs

# ══════════════════════════════════════════════════════════════════════════
# MAIN PDF BUILDER
# ══════════════════════════════════════════════════════════════════════════
def build_pdf(intake,engine,output_path):
    with tempfile.TemporaryDirectory() as tmp:
        print("  Generating SVG diagrams …")
        hazards=engine.extract_hazards()
        db_counts=engine.db_counts()
        imgs=generate_diagrams(intake,hazards,db_counts,tmp)

        print("  Assembling PDF …")
        doc=SimpleDocTemplate(output_path,pagesize=A4,
            leftMargin=MARGIN,rightMargin=MARGIN,topMargin=1.8*cm,bottomMargin=1.8*cm,
            title=f"DHF — {intake['device_name']}",author="dhf_free.py — Live Database Driven",subject="Design History File")
        story=[]
        cover_page(story,intake,engine)
        toc_page(story)
        sec_research(story,engine,imgs)
        sec_device_profile(story,intake,engine,imgs)
        sec_design_inputs(story,intake,engine,imgs)
        sec_design_outputs(story,intake)
        sec_verification(story,intake)
        sec_risk(story,engine,imgs)
        sec_clinical(story,engine,imgs)
        sec_predicates(story,engine)
        sec_patents(story,engine)
        sec_traceability(story,engine,imgs)
        sec_standards(story,engine,intake,imgs)
        doc.build(story,onFirstPage=PageDec(intake),onLaterPages=PageDec(intake))
    print(f"  PDF written → {output_path}")

# ══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════
def main():
    parser=argparse.ArgumentParser(description="Dynamic DHF Builder — 10 Free Databases, No API Key",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python3 dhf_free.py --intake intake.json --out DHF.pdf
          python3 dhf_free.py --intake intake.json --cache data.json --out DHF.pdf
          python3 dhf_free.py --intake intake.json --cache data.json --cached --out DHF.pdf
        """))
    parser.add_argument("--intake",  required=True)
    parser.add_argument("--out",     default="DHF_Report.pdf")
    parser.add_argument("--cache",   default=None, help="Save/load scraped JSON")
    parser.add_argument("--cached",  action="store_true", help="Use existing cache")
    args=parser.parse_args()

    intake=json.loads(Path(args.intake).read_text())
    engine=ResearchEngine(intake["device_name"],intake.get("intended_use",""),intake.get("fda_class","II"))

    bar="█"*62
    print(f"\n{bar}\n  DHF FREE BUILDER  →  {intake['device_name']}\n  No API key · 10 free sources · Professional SVG diagrams\n{bar}")

    if args.cached and args.cache and Path(args.cache).exists():
        print(f"\n  Loading cached data from {args.cache} …")
        engine.results=json.loads(Path(args.cache).read_text())
        print(f"  {engine._count()} records loaded.")
    else:
        engine.run_all()
        if args.cache:
            Path(args.cache).write_text(json.dumps(engine.results,indent=2,default=str))
            print(f"  Cached → {args.cache}")

    print(f"\n  Building PDF …")
    build_pdf(intake,engine,args.out)
    print(f"\n{bar}\n  DONE  →  {args.out}\n{bar}\n")

if __name__=="__main__":
    main()

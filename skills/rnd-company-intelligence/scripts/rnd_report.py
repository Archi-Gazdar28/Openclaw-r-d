#!/usr/bin/env python3
"""
rnd_report.py  —  OpenClaw R&D Company Intelligence
Version: 2.2.0

Provider chain (tried in order for every section):
  1. Serper.dev  (SERPER_API_KEY)   — paid, structured results
  2. web_research.py fallback layer — free multi-engine (DDG, arXiv, CrossRef, Semantic Scholar, GitHub …)

Every command tries Serper first.  If Serper returns an error, empty data, or a
quota/auth failure the command silently falls through to the web_research layer
and tags the section with  "provider": "web_research_fallback"  so the caller
knows which path was taken.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERPER_BASE = "https://google.serper.dev"
VERSION     = "2.2.0"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": f"OpenClaw-rnd-report/{VERSION}"})


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _env(name: str = "SERPER_API_KEY") -> str | None:
    """Return env var value or None (never hard-exits — callers decide)."""
    return os.environ.get(name) or None


def _die(msg: str, code: int = 1) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(code)


def _today() -> str:
    return date.today().isoformat()


def _out(data: Any, output_path: str | None) -> None:
    payload = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(payload, encoding="utf-8")
        print(f"[rnd_report] Written → {p}", file=sys.stderr)
    else:
        print(payload)


# ---------------------------------------------------------------------------
# web_research.py bridge
# ---------------------------------------------------------------------------

def _load_web_research():
    """
    Dynamically import web_research.py from the same directory as this script
    (or from the current working directory as a fallback).
    Returns the module or None if it cannot be found.
    """
    candidates = [
        Path(__file__).parent / "web_research.py",
        Path.cwd() / "web_research.py",
    ]
    for path in candidates:
        if path.exists():
            spec   = importlib.util.spec_from_file_location("web_research", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


_WR = _load_web_research()   # loaded once at import time


def _wr_search(query: str, limit: int = 10, engine: str = "all") -> list[dict]:
    """
    Call web_research.py's search engine pipeline.
    Returns a list of  {engine, title, url, snippet}  dicts (may be empty).
    """
    if _WR is None:
        print("[fallback] web_research.py not found — skipping free-engine fallback.", file=sys.stderr)
        return []

    try:
        args = argparse.Namespace(query=query, limit=limit, engine=engine)
        result = _WR.cmd_web_search(args)
        return result.get("results", [])
    except Exception as exc:
        print(f"[fallback] web_research error: {exc}", file=sys.stderr)
        return []


def _wr_academic(query: str, limit: int = 10) -> list[dict]:
    """Run academic engines only (arXiv + CrossRef + Semantic Scholar)."""
    results: list[dict] = []
    if _WR is None:
        return results
    for engine_fn, name in [
        (_WR._search_arxiv,            "arxiv"),
        (_WR._search_crossref,         "crossref"),
        (_WR._search_semantic_scholar, "semantic-scholar"),
    ]:
        try:
            results.extend(engine_fn(query, limit))
        except Exception as exc:
            print(f"[fallback] {name} error: {exc}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Serper POST — non-fatal version
# ---------------------------------------------------------------------------

class SerperError(Exception):
    """Raised when Serper cannot return usable data."""


def _serper_post(endpoint: str, payload: dict, label: str) -> dict:
    """
    POST to Serper.  Raises SerperError on any failure so callers can
    fall through to the web_research layer without exiting the process.
    """
    key = _env("SERPER_API_KEY")
    if not key:
        raise SerperError("SERPER_API_KEY not set")

    url     = f"{SERPER_BASE}/{endpoint}"
    headers = {"X-API-KEY": key, "Content-Type": "application/json"}

    try:
        r = _SESSION.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        raise SerperError(f"Network error on {label}: {exc}") from exc

    if r.status_code in (401, 403):
        raise SerperError(f"Auth failure ({r.status_code}) on {label} — check SERPER_API_KEY or plan tier")
    if r.status_code == 429:
        raise SerperError(f"Rate-limited by Serper on {label}")
    if r.status_code >= 400:
        raise SerperError(f"HTTP {r.status_code} from Serper on {label}: {r.text[:200]}")

    try:
        return r.json()
    except ValueError as exc:
        raise SerperError(f"Non-JSON response from Serper on {label}: {r.text[:200]}") from exc


# ---------------------------------------------------------------------------
# Shared value-extraction utilities
# ---------------------------------------------------------------------------

_CRORE_RE  = re.compile(r"(?:INR|Rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr)", re.I)
_MILLION_RE = re.compile(r"(?:USD|US\$|\$)?\s*([\d,]+(?:\.\d+)?)\s*(?:million|mn|M)\b", re.I)
_BILLION_RE = re.compile(r"(?:USD|US\$|\$)?\s*([\d,]+(?:\.\d+)?)\s*(?:billion|bn|B)\b", re.I)


def _extract_financials(text: str) -> dict:
    """
    Try to parse monetary figures from unstructured snippet text.
    Returns a dict with whichever fields were found.
    """
    out: dict[str, Any] = {}
    if m := _CRORE_RE.search(text):
        out["revenue_inr_crore"] = float(m.group(1).replace(",", ""))
    if m := _BILLION_RE.search(text):
        out["revenue_usd_approx"] = float(m.group(1).replace(",", "")) * 1_000_000_000
    elif m := _MILLION_RE.search(text):
        out["revenue_usd_approx"] = float(m.group(1).replace(",", "")) * 1_000_000
    return out


def _snippets_to_rows(items: list[dict], source_label: str) -> list[dict]:
    """Convert raw search result items into financial row dicts."""
    rows = []
    for idx, item in enumerate(items[:5]):
        snippet = item.get("snippet", "") or ""
        parsed  = _extract_financials(snippet)
        rows.append({
            "rank":                idx + 1,
            "fiscal_year":         None,
            "source":              item.get("url") or item.get("link"),
            "source_label":        source_label,
            "snippet":             snippet,
            **parsed,
        })
    return rows


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

# ── 1. company-details ──────────────────────────────────────────────────────

def cmd_company_details(args: argparse.Namespace) -> dict:
    company, product = args.company, args.product
    gaps: list[str] = []
    provider = "serper"

    # ── Serper attempt ──
    try:
        print(f"[company-details] Serper KG lookup: '{company} {product}'…", file=sys.stderr)
        data    = _serper_post("search", {"q": f"{company} {product} official overview profile"}, "Company Overview")
        kg      = data.get("knowledgeGraph", {})
        organic = data.get("organic", [])

        if not kg and not organic:
            raise SerperError("Serper returned empty knowledge graph and no organic results")

        snippet = organic[0].get("snippet", "") if organic else ""
        link    = organic[0].get("link", "")    if organic else ""

        profile = {
            "legal_name":         kg.get("title")       or company,
            "short_description":  kg.get("description") or snippet,
            "website_url":        kg.get("website")     or link,
            "country_code":       kg.get("type")        or "Unknown",
            "founded_on":         None,
            "num_employees_enum": None,
            "total_funding_usd":  None,
        }

    except SerperError as exc:
        print(f"[company-details] Serper failed ({exc}) — using web_research fallback", file=sys.stderr)
        gaps.append(f"Serper unavailable: {exc}")
        provider = "web_research_fallback"
        kg       = {}

        # ── web_research fallback ──
        items = _wr_search(f"{company} {product} company profile overview founded", limit=10)
        items2 = _wr_search(f"{company} official website about", limit=5)

        snippet = items[0].get("snippet", "")  if items  else ""
        link    = items[0].get("url", "")      if items  else ""
        website = next((i.get("url","") for i in items2 if company.lower().split()[0] in i.get("url","").lower()), link)

        profile = {
            "legal_name":         company,
            "short_description":  snippet,
            "website_url":        website,
            "country_code":       None,
            "founded_on":         None,
            "num_employees_enum": None,
            "total_funding_usd":  None,
        }
        organic = [{"title": i.get("title"), "link": i.get("url"), "snippet": i.get("snippet")} for i in items]

    # ── enrichment: funding news (always attempt) ──
    funding_items = _wr_search(f"{company} funding raised investment round", limit=8)
    funding_rows  = []
    for fi in funding_items:
        parsed = _extract_financials(fi.get("snippet",""))
        if parsed:
            funding_rows.append({
                "source":  fi.get("url"),
                "snippet": fi.get("snippet"),
                **parsed,
            })

    return {
        "command":       "company-details",
        "version":       VERSION,
        "as_of":         _today(),
        "company":       company,
        "product":       product,
        "provider":      provider,
        "profile":       profile,
        "knowledge_panel": kg,
        "funding_rounds":  funding_rows,
        "organic_top5":    organic[:5],
        "data_gaps":       gaps,
    }


# ── 2. turnover / financials ─────────────────────────────────────────────────

def cmd_turnover(args: argparse.Namespace) -> dict:
    company  = args.company
    ticker   = getattr(args, "ticker", None)
    is_pub   = getattr(args, "public", False) or bool(ticker)
    gaps:  list[str] = []
    rows:  list[dict] = []
    provider = "serper"

    # ── Serper attempt ──
    try:
        if is_pub:
            q = f"{ticker or company} annual revenue financial results site:macrotrends.net OR site:wsj.com OR site:moneycontrol.com"
        else:
            q = f'"{company}" revenue turnover annual report crore million'

        print(f"[turnover] Serper search: {q}", file=sys.stderr)
        data    = _serper_post("search", {"q": q}, "Financials")
        organic = data.get("organic", [])

        for item in organic[:5]:
            snippet = item.get("snippet", "")
            parsed  = _extract_financials(snippet)
            rows.append({
                "rank":    organic.index(item) + 1,
                "source":  item.get("link"),
                "snippet": snippet,
                **parsed,
            })

        # Treat "all rows lack any parsed numbers" as a soft failure
        if not any(r.get("revenue_inr_crore") or r.get("revenue_usd_approx") for r in rows):
            raise SerperError("Serper snippets contained no parseable financial figures")

    except SerperError as exc:
        print(f"[turnover] Serper failed ({exc}) — using web_research fallback", file=sys.stderr)
        gaps.append(f"Serper unavailable: {exc}")
        provider = "web_research_fallback"
        rows     = []

    # ── web_research fallback (also runs when Serper rows had no numbers) ──
    if provider == "web_research_fallback" or not rows:
        queries = [
            f"{company} annual revenue turnover crore FY2024",
            f"{company} financial results profit sales billion million",
            f"{company} {ticker or ''} earnings report revenue".strip(),
        ]
        fallback_items: list[dict] = []
        for q in queries:
            fallback_items.extend(_wr_search(q, limit=8))

        # Deduplicate by URL
        seen: set[str] = set()
        for item in fallback_items:
            url = item.get("url","")
            if url in seen:
                continue
            seen.add(url)
            snippet = item.get("snippet","")
            parsed  = _extract_financials(snippet)
            rows.append({
                "rank":    len(rows) + 1,
                "source":  url,
                "engine":  item.get("engine"),
                "snippet": snippet,
                **parsed,
            })
            if len(rows) >= 8:
                break

        provider = "web_research_fallback"

    parsed_rows = [r for r in rows if r.get("revenue_inr_crore") or r.get("revenue_usd_approx")]
    if not parsed_rows:
        gaps.append(
            "No structured financial figures found in snippets. "
            "Company may be private with no public disclosures. "
            "Manual review of source URLs recommended."
        )

    return {
        "command":       "turnover",
        "version":       VERSION,
        "as_of":         _today(),
        "company":       company,
        "ticker":        ticker,
        "is_public":     is_pub,
        "provider":      provider,
        "rows":          rows,
        "parsed_rows":   parsed_rows,
        "data_gaps":     gaps,
    }


# ── 3. patents ───────────────────────────────────────────────────────────────

def cmd_patents(args: argparse.Namespace) -> dict:
    company  = args.company
    product  = args.product
    keywords = getattr(args, "keywords", "") or ""
    gaps:    list[str] = []
    patents: list[dict] = []
    provider = "serper"

    # ── Serper /patents attempt ──
    try:
        q = f'assignee:"{company}" {product} {keywords}'.strip()
        print(f"[patents] Serper /patents: {q}", file=sys.stderr)
        data = _serper_post("patents", {"q": q}, "Patents")
        raw  = data.get("patents", [])

        if not raw:
            raise SerperError("Serper /patents returned 0 results (possible 403 or quota exhaustion)")

        for p in raw:
            pid = p.get("patentNumber") or p.get("id") or "Unknown"
            patents.append({
                "patent_id":        pid,
                "title":            p.get("title", "Untitled"),
                "assignee":         p.get("assignee"),
                "inventors":        [p.get("inventor")] if p.get("inventor") else [],
                "publication_date": p.get("publicationDate"),
                "abstract_snippet": p.get("snippet"),
                "link":             p.get("link") or f"https://patents.google.com/patent/{pid}/en",
                "source":           "serper/patents",
            })

    except SerperError as exc:
        print(f"[patents] Serper failed ({exc}) — using web_research fallback", file=sys.stderr)
        gaps.append(f"Serper /patents unavailable: {exc}")
        provider = "web_research_fallback"

    # ── web_research fallback ──
    if provider == "web_research_fallback":
        queries = [
            f"{company} {product} patent site:patents.google.com",
            f"{company} {product} patent site:worldwide.espacenet.com",
            f"{company} {product} {keywords} patent assignee filing".strip(),
            f'"{company}" patent {product} abstract claims',
        ]
        fallback_items: list[dict] = []
        for q in queries:
            fallback_items.extend(_wr_search(q, limit=10))

        seen: set[str] = set()
        for item in fallback_items:
            url = item.get("url","")
            if url in seen:
                continue
            seen.add(url)

            # Try to extract a patent number from the URL or title
            pid_match = re.search(r"(US|EP|WO|IN|CN|JP)\d{6,}", url + " " + item.get("title",""), re.I)
            pid = pid_match.group(0).upper() if pid_match else None

            patents.append({
                "patent_id":        pid,
                "title":            item.get("title"),
                "assignee":         company,
                "inventors":        [],
                "publication_date": None,
                "abstract_snippet": item.get("snippet"),
                "link":             url,
                "source":           f"web_research/{item.get('engine','unknown')}",
            })
            if len(patents) >= 20:
                break

    # ── tech-area classification ──
    tech_areas: dict[str, int] = {}
    for p in patents:
        t = (p.get("title") or "").lower()
        for kw in ["drug eluting", "stent", "scaffold", "sirolimus", "polymer", "coating",
                   "balloon", "catheter", "imaging", "sensor", "ai", "machine learning"]:
            if kw in t:
                tech_areas[kw] = tech_areas.get(kw, 0) + 1

    return {
        "command":    "patents",
        "version":    VERSION,
        "as_of":      _today(),
        "company":    company,
        "product":    product,
        "keywords":   keywords,
        "provider":   provider,
        "count":      len(patents),
        "patents":    patents,
        "tech_areas": tech_areas,
        "data_gaps":  gaps,
    }


# ── 4. trends ────────────────────────────────────────────────────────────────

def cmd_trends(args: argparse.Namespace) -> dict:
    product  = args.product
    company  = getattr(args, "company", "")
    gaps:     list[str] = []
    timeline: list[dict] = []
    related:  list[str] = []
    provider  = "serper"

    # ── Serper news for velocity signals ──
    try:
        q = f"{product} market growth trends 2024 2025"
        print(f"[trends] Serper /news: {q}", file=sys.stderr)
        data  = _serper_post("news", {"q": q}, "News Trends")
        items = data.get("news", [])

        if not items:
            raise SerperError("Serper /news returned 0 items")

        for item in items[:15]:
            timeline.append({
                "date":    item.get("date") or "Recent",
                "title":   item.get("title"),
                "source":  item.get("link"),
                "snippet": item.get("snippet"),
                # NOTE: no synthetic index values — only real dates/titles from API
            })

    except SerperError as exc:
        print(f"[trends] Serper failed ({exc}) — using web_research fallback", file=sys.stderr)
        gaps.append(f"Serper news unavailable: {exc}")
        provider = "web_research_fallback"

    # ── web_research fallback (always augments, even when Serper worked) ──
    wr_queries = [
        f"{product} market size growth forecast 2024 2025 2026",
        f"{product} industry trends report CAGR",
        f"{company} {product} market share competitor analysis".strip(),
    ]
    wr_items: list[dict] = []
    for q in wr_queries:
        wr_items.extend(_wr_search(q, limit=8))

    for item in wr_items:
        url = item.get("url","")
        if not any(t.get("source") == url for t in timeline):
            timeline.append({
                "date":    None,
                "title":   item.get("title"),
                "source":  url,
                "snippet": item.get("snippet"),
                "engine":  item.get("engine"),
            })

    # ── Related query extraction from snippets ──
    all_snippets = " ".join(t.get("snippet","") or "" for t in timeline)
    # simple keyword frequency as a stand-in for "related queries"
    kw_candidates = re.findall(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\b', all_snippets)
    freq: dict[str, int] = {}
    for kw in kw_candidates:
        if len(kw) > 4 and kw.lower() not in {"the","and","for","this","that","with","from"}:
            freq[kw] = freq.get(kw, 0) + 1
    related = sorted(freq, key=lambda k: -freq[k])[:15]

    if not timeline:
        gaps.append("No trend signals found from any engine. Try a broader product keyword.")

    gaps.append(
        "Timeline entries are news article dates, NOT Google Trends interest index values. "
        "For real interest-over-time data, use the Google Trends dashboard manually."
    )

    return {
        "command":         "trends",
        "version":         VERSION,
        "as_of":           _today(),
        "product":         product,
        "provider":        provider,
        "timeline":        timeline,
        "related_queries": related,
        "data_gaps":       gaps,
    }


# ── 5. competitors ───────────────────────────────────────────────────────────

def cmd_competitors(args: argparse.Namespace) -> dict:
    company  = args.company
    product  = args.product
    limit    = getattr(args, "limit", 15)
    gaps:    list[str] = []
    comps:   list[dict] = []
    provider = "serper"

    # ── Serper ──
    try:
        q = f"{product} alternatives competitors market leaders vs"
        print(f"[competitors] Serper search: {q}", file=sys.stderr)
        data    = _serper_post("search", {"q": q}, "Competitors")
        organic = data.get("organic", [])
        if not organic:
            raise SerperError("Serper returned 0 organic results for competitors")

        for item in organic:
            comps.append({
                "name":        item.get("title","")[:60],
                "description": item.get("snippet"),
                "website":     item.get("link"),
                "funding_usd": None,
                "founded":     None,
                "source":      "serper/search",
            })

    except SerperError as exc:
        print(f"[competitors] Serper failed ({exc}) — using web_research fallback", file=sys.stderr)
        gaps.append(f"Serper unavailable: {exc}")
        provider = "web_research_fallback"

    # ── web_research fallback + enrichment ──
    wr_queries = [
        f"{product} top competitors companies market",
        f"{product} alternatives vs {company}",
        f"best {product} manufacturers global leaders",
        f"{product} market share companies ranking 2024",
    ]
    wr_items: list[dict] = []
    for q in wr_queries:
        wr_items.extend(_wr_search(q, limit=10))

    seen_urls = {c.get("website") for c in comps}
    for item in wr_items:
        url = item.get("url","")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        comps.append({
            "name":        item.get("title","")[:60],
            "description": item.get("snippet"),
            "website":     url,
            "funding_usd": None,
            "founded":     None,
            "source":      f"web_research/{item.get('engine','unknown')}",
        })

    return {
        "command":     "competitors",
        "version":     VERSION,
        "as_of":       _today(),
        "company":     company,
        "product":     product,
        "provider":    provider,
        "count":       min(len(comps), limit),
        "competitors": comps[:limit],
        "data_gaps":   gaps,
    }


# ── 6. research-papers ───────────────────────────────────────────────────────

def cmd_research_papers(args: argparse.Namespace) -> dict:
    product  = args.product
    keywords = getattr(args, "keywords", "") or ""
    limit    = getattr(args, "limit", 20)
    gaps:    list[str] = []
    papers:  list[dict] = []
    provider = "serper"

    # ── Serper /scholar ──
    try:
        q = f"{product} {keywords}".strip()
        print(f"[research-papers] Serper /scholar: {q}", file=sys.stderr)
        data    = _serper_post("scholar", {"q": q}, "Scholar")
        organic = data.get("organic", [])
        if not organic:
            raise SerperError("Serper /scholar returned 0 results")

        for p in organic:
            papers.append({
                "title":    p.get("title"),
                "authors":  p.get("publicationInfo", {}).get("authors") or "Not disclosed",
                "year":     p.get("publicationInfo", {}).get("year"),
                "venue":    p.get("publicationInfo", {}).get("journal") or "Academic Source",
                "cited_by": p.get("citedBy"),
                "snippet":  p.get("snippet"),
                "link":     p.get("link"),
                "source":   "serper/scholar",
            })

    except SerperError as exc:
        print(f"[research-papers] Serper failed ({exc}) — using academic fallback engines", file=sys.stderr)
        gaps.append(f"Serper /scholar unavailable: {exc}")
        provider = "web_research_fallback"

    # ── Always augment with free academic engines ──
    q = f"{product} {keywords}".strip()
    academic_items = _wr_academic(q, limit=limit)

    seen_urls = {p.get("link") for p in papers}
    for item in academic_items:
        url = item.get("url","")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        papers.append({
            "title":    item.get("title"),
            "authors":  "See source",
            "year":     None,
            "venue":    item.get("engine","").upper(),
            "cited_by": None,
            "snippet":  item.get("snippet"),
            "link":     url,
            "source":   f"web_research/{item.get('engine','unknown')}",
        })

    # ── Web fallback for Google Scholar via DDG ──
    wr_items = _wr_search(f"{product} {keywords} research paper clinical trial study", limit=10)
    for item in wr_items:
        url = item.get("url","")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        papers.append({
            "title":    item.get("title"),
            "authors":  None,
            "year":     None,
            "venue":    None,
            "cited_by": None,
            "snippet":  item.get("snippet"),
            "link":     url,
            "source":   f"web_research/{item.get('engine','unknown')}",
        })

    return {
        "command":   "research-papers",
        "version":   VERSION,
        "as_of":     _today(),
        "product":   product,
        "keywords":  keywords,
        "provider":  provider,
        "count":     len(papers[:limit]),
        "papers":    papers[:limit],
        "data_gaps": gaps,
    }


# ── 7. tech-stack-detect ────────────────────────────────────────────────────

def cmd_tech_stack_detect(args: argparse.Namespace) -> dict:
    domain = args.domain
    gaps:  list[str] = []
    layers: list[dict] = []
    provider = "serper"

    # ── Serper ──
    try:
        q = f'"{domain}" technology stack framework built with'
        print(f"[tech-stack-detect] Serper search: {q}", file=sys.stderr)
        data    = _serper_post("search", {"q": q}, "Tech Stack")
        organic = data.get("organic", [])
        if not organic:
            raise SerperError("Serper returned no results for tech stack")

        for item in organic[:5]:
            layers.append({
                "name":        item.get("title","")[:60],
                "description": item.get("snippet"),
                "link":        item.get("link"),
                "source":      "serper/search",
            })

    except SerperError as exc:
        print(f"[tech-stack-detect] Serper failed ({exc}) — using web_research fallback", file=sys.stderr)
        gaps.append(f"Serper unavailable: {exc}")
        provider = "web_research_fallback"

    # ── web_research fallback ──
    wr_queries = [
        f"site:{domain} technology",
        f"{domain} built with powered by framework CMS",
        f"{domain} tech stack engineering blog",
    ]
    for q in wr_queries:
        items = _wr_search(q, limit=5)
        seen_urls = {l.get("link") for l in layers}
        for item in items:
            url = item.get("url","")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            layers.append({
                "name":        item.get("title","")[:60],
                "description": item.get("snippet"),
                "link":        url,
                "source":      f"web_research/{item.get('engine','unknown')}",
            })

    # ── GitHub search for open-source repos by domain owner ──
    org_guess = domain.split(".")[0]
    if _WR:
        try:
            gh_items = _WR._search_github(f"org:{org_guess}", limit=5)
            for item in gh_items:
                layers.append({
                    "name":        item.get("title","")[:60],
                    "description": item.get("snippet"),
                    "link":        item.get("url"),
                    "source":      "web_research/github",
                })
        except Exception:
            pass

    return {
        "command":   "tech-stack-detect",
        "version":   VERSION,
        "as_of":     _today(),
        "domain":    domain,
        "provider":  provider,
        "layers":    layers,
        "data_gaps": gaps,
    }


# ── 8. full-report ───────────────────────────────────────────────────────────

def cmd_full_report(args: argparse.Namespace) -> dict:
    company = args.company
    product = args.product
    output  = getattr(args, "output", None)

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "command":  "full-report",
        "version":  VERSION,
        "as_of":    _today(),
        "company":  company,
        "product":  product,
        "sections": {},
        "all_gaps": [],
        "providers_used": set(),
    }

    def _run(label: str, fn, sub_args: argparse.Namespace) -> None:
        try:
            data = fn(sub_args)
            results["sections"][label] = data
            results["all_gaps"].extend(data.get("data_gaps", []))
            results["providers_used"].add(data.get("provider", "unknown"))
        except Exception as exc:
            results["sections"][label] = {"error": str(exc), "data_gaps": [str(exc)]}
            results["all_gaps"].append(f"{label}: {exc}")

    def _ns(**kwargs) -> argparse.Namespace:
        base = argparse.Namespace(
            company  = company,
            product  = product,
            domain   = getattr(args, "domain",   None),
            ticker   = getattr(args, "ticker",   None),
            public   = getattr(args, "public",   False),
            private  = getattr(args, "private",  False),
            keywords = getattr(args, "keywords", ""),
            limit    = getattr(args, "limit",    50),
        )
        for k, v in kwargs.items():
            setattr(base, k, v)
        return base

    _run("company-details",   cmd_company_details,   _ns())
    _run("turnover",          cmd_turnover,           _ns())
    _run("patents",           cmd_patents,            _ns())
    _run("trends",            cmd_trends,             _ns())
    _run("competitors",       cmd_competitors,        _ns())
    _run("research-papers",   cmd_research_papers,    _ns())
    if getattr(args, "domain", None):
        _run("tech-stack-detect", cmd_tech_stack_detect, _ns())

    # Convert set → list for JSON serialisation
    results["providers_used"] = sorted(results["providers_used"])

    _out(results, output)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="rnd_report.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    root.add_argument("--version", action="version", version=VERSION)
    sub = root.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    def _common(p):
        p.add_argument("--output", "-o", default=None)

    p1 = sub.add_parser("company-details")
    p1.add_argument("--company", required=True)
    p1.add_argument("--product", required=True)
    p1.add_argument("--domain",  default=None)
    _common(p1)

    p2 = sub.add_parser("turnover")
    p2.add_argument("--company", required=True)
    p2.add_argument("--ticker",  default=None)
    g = p2.add_mutually_exclusive_group()
    g.add_argument("--public",  action="store_true")
    g.add_argument("--private", action="store_true")
    _common(p2)

    p3 = sub.add_parser("patents")
    p3.add_argument("--company",  required=True)
    p3.add_argument("--product",  required=True)
    p3.add_argument("--keywords", default="")
    p3.add_argument("--limit",    type=int, default=50)
    _common(p3)

    p4 = sub.add_parser("trends")
    p4.add_argument("--product", required=True)
    p4.add_argument("--company", default="")
    _common(p4)

    p5 = sub.add_parser("competitors")
    p5.add_argument("--company", required=True)
    p5.add_argument("--product", required=True)
    p5.add_argument("--limit",   type=int, default=15)
    _common(p5)

    p6 = sub.add_parser("research-papers")
    p6.add_argument("--product",  required=True)
    p6.add_argument("--keywords", default="")
    p6.add_argument("--limit",    type=int, default=20)
    _common(p6)

    p7 = sub.add_parser("tech-stack-detect")
    p7.add_argument("--domain", required=True)
    _common(p7)

    p8 = sub.add_parser("full-report")
    p8.add_argument("--company",  required=True)
    p8.add_argument("--product",  required=True)
    p8.add_argument("--domain",   default=None)
    p8.add_argument("--ticker",   default=None)
    p8.add_argument("--keywords", default="")
    g2 = p8.add_mutually_exclusive_group()
    g2.add_argument("--public",  action="store_true")
    g2.add_argument("--private", action="store_true")
    p8.add_argument("--limit",   type=int, default=50)
    p8.add_argument("--output",  "-o", required=True)

    return root


COMMAND_MAP = {
    "company-details":   cmd_company_details,
    "turnover":          cmd_turnover,
    "patents":           cmd_patents,
    "trends":            cmd_trends,
    "competitors":       cmd_competitors,
    "research-papers":   cmd_research_papers,
    "tech-stack-detect": cmd_tech_stack_detect,
    "full-report":       cmd_full_report,
}


def main() -> None:
    parser = build_arg_parser()
    args   = parser.parse_args()
    fn     = COMMAND_MAP.get(args.command)
    if not fn:
        _die(f"Unknown command: {args.command}")

    result = fn(args)
    if args.command != "full-report":
        _out(result, getattr(args, "output", None))


if __name__ == "__main__":
    main()

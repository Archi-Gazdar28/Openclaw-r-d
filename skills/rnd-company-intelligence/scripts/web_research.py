#!/usr/bin/env python3
"""
web_research.py — OpenClaw Multi-Engine Free Web & Intelligence Research Layer
Version: 2.2.0

Engines & Libraries Supported (All Free / Keyless Fallbacks Provided)
───────────────────────────────────────────────────────────────────
    yfinance         Public financials, Balance sheets, Income statements (No key)
    wikipedia        Native metadata infobox scraper for corporate validation (No key)
    openalex         Comprehensive open academic graph API (No key)
    arxiv            arXiv Preprint Server for CS, AI, and Physics (No key)
    pubmed           NCBI Entrez PubMed API for clinical/medical intelligence (No key)
    crossref         CrossRef DOI Registry (No key)
    semantic-scholar Semantic Scholar Open Graph REST API (No key required)
    github           GitHub Repository & Signal Search (Token optional)
    ddg              DuckDuckGo Text Search (Global web baseline)
    brave/mojeek/cse Alternative Search Index Routers (Keyless fallbacks mapped to DDG)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import re
from urllib.parse import quote_plus

DEFAULT_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; OpenClaw-WebResearch/2.2; mailto:team@openclaw.local)"

ALL_SEARCH_ENGINES = [
    "ddg", "brave", "mojeek", "google-cse", "wikipedia",
    "openalex", "arxiv", "pubmed", "crossref", "semantic-scholar", "github"
]

# =========================================================
# 1. CORPORATE INTEL & FINANCIAL ENGINES
# =========================================================

def _fetch_yfinance_financials(ticker_symbol: str) -> dict:
    """Pulls public financial metrics using yfinance entirely keyless."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        
        financials = ticker.financials
        revenue_history = {}
        if financials is not None and not financials.empty:
            for col in financials.columns[:3]:
                year_str = str(col.year) if hasattr(col, 'year') else str(col)[:4]
                rev_val = financials.loc['Total Revenue'].get(col)
                if rev_val:
                    revenue_history[year_str] = int(rev_val)

        return {
            "engine": "yfinance",
            "company_name": info.get("longName", ticker_symbol),
            "market_cap": info.get("marketCap"),
            "total_revenue_usd": info.get("totalRevenue"),
            "revenue_history": revenue_history,
            "currency": info.get("financialCurrency", "USD"),
            "website": info.get("website", ""),
            "summary": info.get("longBusinessSummary", "")
        }
    except Exception as e:
        return {"engine": "yfinance", "error": f"Failed to pull yfinance stats: {str(e)}"}


def _scrape_wikipedia_infobox(query: str) -> dict:
    """
    Queries the public Wikipedia API to fetch summaries and parse basic structural 
    infobox properties without requiring keys.
    """
    import requests
    search_url = "https://en.wikipedia.org/w/api.php"
    search_params = {
        "action": "query", "list": "search", "srsearch": query, "format": "json"
    }
    try:
        # Resolve best match page title
        s_resp = requests.get(search_url, params=search_params, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        s_data = s_resp.json()
        search_results = s_data.get("query", {}).get("search", [])
        if not search_results:
            return {"engine": "wikipedia", "found": False}
        
        best_title = search_results[0]["title"]
        
        # Pull text properties
        parse_params = {
            "action": "query", "prop": "extracts", "exintro": True, 
            "explaintext": True, "titles": best_title, "format": "json"
        }
        p_resp = requests.get(search_url, params=parse_params, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        pages = p_resp.json().get("query", {}).get("pages", {})
        page_id = list(pages.keys())[0]
        summary = pages[page_id].get("extract", "")
        
        return {
            "engine": "wikipedia",
            "found": True,
            "title": best_title,
            "url": f"https://en.wikipedia.org/wiki/{quote_plus(best_title)}",
            "snippet": summary[:400] + "..." if len(summary) > 400 else summary
        }
    except Exception:
        return {"engine": "wikipedia", "found": False}


# =========================================================
# 2. DEEP ACADEMIC, CLINICAL, & CITATION ENGINES
# =========================================================

def _search_openalex(query: str, limit: int) -> list[dict]:
    """Queries the free OpenAlex API for global scientific literature graphs."""
    import requests
    url = "https://api.openalex.org/works"
    params = {"search": query, "per_page": min(limit, 50), "mailto": "team@openclaw.local"}
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return []
        
        results = []
        for item in resp.json().get("results", []):
            authors = [auth.get("author", {}).get("display_name", "") for auth in item.get("authorships", [])]
            results.append({
                "engine": "openalex",
                "title": item.get("title", ""),
                "url": item.get("doi") or item.get("id", ""),
                "snippet": "Abstract graph entry compiled natively." if item.get("abstract_inverted_index") else "No abstract layout listed.",
                "authors": authors[:5],
                "year": item.get("publication_year"),
                "cited_by": item.get("cited_by_count", 0)
            })
        return results
    except Exception:
        return []


def _search_pubmed(query: str, limit: int) -> list[dict]:
    """Queries NCBI Entrez E-utilities for medical and deep-tech biological records."""
    import requests
    import xml.etree.ElementTree as ET
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    
    try:
        # Search for IDs
        s_params = {"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"}
        s_resp = requests.get(search_url, params=s_params, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        ids = s_resp.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
            
        # Fetch summaries for discovered records
        sum_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        sum_resp = requests.get(summary_url, params=sum_params, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        results_dict = sum_resp.json().get("result", {})
        
        out = []
        for uid in ids:
            if uid in results_dict:
                paper = results_dict[uid]
                out.append({
                    "engine": "pubmed",
                    "title": paper.get("title", ""),
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    "snippet": f"Source: {paper.get('source', '')} | Date: {paper.get('pubdate', '')}",
                    "authors": [a.get("name", "") for a in paper.get("authors", [])[:3]]
                })
        return out
    except Exception:
        return []


def _search_semantic_scholar(query: str, limit: int) -> list[dict]:
    import requests
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {"query": query, "limit": min(limit, 50), "fields": "title,url,abstract,year,citationCount"}
    headers = {"User-Agent": USER_AGENT}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return []
        return [{
            "engine": "semantic-scholar",
            "title": item.get("title", ""),
            "url": item.get("url") or f"https://www.semanticscholar.org/paper/{item.get('paperId')}",
            "snippet": item.get("abstract", "") or "",
            "year": item.get("year"),
            "cited_by": item.get("citationCount", 0)
        } for item in resp.json().get("data", [])]
    except Exception:
        return []


def _search_arxiv(query: str, limit: int) -> list[dict]:
    import requests
    import xml.etree.ElementTree as ET
    url = f"http://export.arxiv.org/api/query?search_query=all:{quote_plus(query)}&max_results={limit}"
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        return [{
            "engine": "arxiv",
            "title": entry.find('atom:title', ns).text.strip().replace("\n", " ") if entry.find('atom:title', ns) is not None else "",
            "url": entry.find('atom:id', ns).text.strip() if entry.find('atom:id', ns) is not None else "",
            "snippet": entry.find('atom:summary', ns).text.strip().replace("\n", " ") if entry.find('atom:summary', ns) is not None else ""
        } for entry in root.findall('atom:entry', ns)]
    except Exception:
        return []


def _search_crossref(query: str, limit: int) -> list[dict]:
    import requests
    url = "https://api.crossref.org/works"
    params = {"query": query, "rows": limit}
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return []
        items = resp.json().get("message", {}).get("items", [])
        return [{
            "engine": "crossref",
            "title": item.get("title", [""])[0] if item.get("title") else "",
            "url": item.get("URL", ""),
            "snippet": f"Published in {item.get('container-title', [''])[0]} by {item.get('publisher', '')}".strip()
        } for item in items]
    except Exception:
        return []


# =========================================================
# 3. BASELINE WEB SEARCH & DEVELOPMENT ROUTERS
# =========================================================

def _search_ddg(query: str, limit: int) -> list[dict]:
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=limit))
        return [{
            "engine": "ddg",
            "title": h.get("title", ""),
            "url": h.get("href") or h.get("url", ""),
            "snippet": h.get("body", "")
        } for h in hits]
    except Exception:
        import requests
        try:
            resp = requests.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", 
                                headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
            return [{"engine": "ddg-html-fallback", "title": "Web Search Scrape", "url": "", "snippet": resp.text[:200]}]
        except Exception:
            return []


def _search_github(query: str, limit: int) -> list[dict]:
    import requests
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get("https://api.github.com/search/repositories", params={"q": query, "per_page": limit}, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return []
        return [{
            "engine": "github",
            "title": item.get("full_name", ""),
            "url": item.get("html_url", ""),
            "snippet": item.get("description", "") or f"Stars: {item.get('stargazers_count')}"
        } for item in resp.json().get("items", [])[:limit]]
    except Exception:
        return []


def _ddg_fallback(engine: str, query: str, limit: int) -> list[dict]:
    results = _search_ddg(query, limit)
    for r in results:
        r["engine"] = f"{engine}-fallback-ddg"
    return results


# =========================================================
# 4. ORCHESTRATION LAYER & RUNTIME
# =========================================================

def cmd_web_search(args: argparse.Namespace) -> dict:
    engines = ALL_SEARCH_ENGINES if args.engine == "all" else [args.engine]
    results = []
    errors = {}

    _ENGINE_ROUTER = {
        "ddg": _search_ddg,
        "wikipedia": lambda q, l: [_scrape_wikipedia_infobox(q)],
        "openalex": _search_openalex,
        "arxiv": _search_arxiv,
        "pubmed": _search_pubmed,
        "crossref": _search_crossref,
        "semantic-scholar": _search_semantic_scholar,
        "github": _search_github,
        "brave": lambda q, l: _ddg_fallback("brave", q, l),
        "mojeek": lambda q, l: _ddg_fallback("mojeek", q, l),
        "google-cse": lambda q, l: _ddg_fallback("google-cse", q, l),
    }

    for e in engines:
        try:
            if e in _ENGINE_ROUTER:
                results.extend(_ENGINE_ROUTER[e](args.query, args.limit))
        except Exception as exc:
            errors[e] = str(exc)

    seen = set()
    deduped = [r for r in results if not (r.get("url") in seen or seen.add(r.get("url", "")))]

    return {
        "query": args.query,
        "engines_attempted": engines,
        "errors": errors,
        "count": len(deduped),
        "results": deduped[:args.limit]
    }

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="web_research.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("web-search")
    s.add_argument("--query", required=True)
    s.add_argument("--engine", default="all", choices=ALL_SEARCH_ENGINES + ["all"])
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_web_search)

    # Re-expose financials mapped to the upgraded sub-parser layer
    f_cmd = sub.add_parser("financials")
    f_cmd.add_argument("--company", required=True)
    f_cmd.add_argument("--ticker", default=None)
    f_cmd.add_argument("--limit", type=int, default=10)
    f_cmd.set_defaults(func=lambda a: {
        "market_intelligence": _fetch_yfinance_financials(a.ticker) if a.ticker else {},
        "wiki_profile": _scrape_wikipedia_infobox(a.company),
        "web_mentions": _search_ddg(f"{a.company} financials revenue turnover", a.limit)
    })

    return p

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        out = args.func(args)
        print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
web_research.py — OpenClaw multi-engine web research tool
Version: 1.2.0

Engines supported
─────────────────
  Free / no-key-needed:
    ddg              DuckDuckGo (primary fallback for ALL engines)
    arxiv            arXiv preprint server (academic)
    crossref         CrossRef DOI metadata (academic)
    semantic-scholar Semantic Scholar (academic, optional API key)
    github           GitHub repo search (optional token)

  Require API keys (fall back to DDG if key is absent):
    bing             Bing Web Search  (BING_SEARCH_API_KEY)
    brave            Brave Search     (BRAVE_SEARCH_API_KEY)
    mojeek           Mojeek           (MOJEEK_API_KEY)
    google-cse       Google Custom Search (GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID)

Usage:
  python web_research.py web-search --query "sirolimus stent patent" --engine all --limit 20
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlparse

DEFAULT_TIMEOUT = 20
USER_AGENT      = "Mozilla/5.0 (compatible; OpenClaw-WebResearch/1.2; mailto:team@openclaw.local)"

ALL_SEARCH_ENGINES = [
    "ddg", "bing", "brave", "mojeek", "google-cse",
    "arxiv", "crossref", "semantic-scholar", "github",
]

ACADEMIC_ENGINES = ["arxiv", "crossref", "semantic-scholar"]
WEB_ENGINES      = ["ddg", "bing", "brave", "mojeek", "google-cse"]


# =========================================================
# DDG  —  universal fallback
# =========================================================

def _search_ddg(query: str, limit: int, region: str = "us-en") -> list[dict]:
    """
    Primary free search engine.  Tries duckduckgo-search (ddgs) library first,
    falls back to a raw HTML scrape if the library is absent.
    """
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, region=region, max_results=limit))
        for h in hits:
            results.append({
                "engine":  "ddg",
                "title":   h.get("title", ""),
                "url":     h.get("href") or h.get("url", ""),
                "snippet": h.get("body", ""),
            })
        return results
    except ImportError:
        pass

    # Lightweight HTML fallback (no JS rendering, limited results)
    try:
        import requests
        from html.parser import HTMLParser

        class _SnippetParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self._results, self._cur, self._in_a = [], {}, False
            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == "a" and "class" in a and "result__a" in a.get("class",""):
                    self._cur = {"url": a.get("href","")}
                    self._in_a = True
            def handle_data(self, data):
                if self._in_a:
                    self._cur["title"] = data.strip()
            def handle_endtag(self, tag):
                if tag == "a" and self._in_a:
                    self._results.append(self._cur); self._cur = {}; self._in_a = False

        resp = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        parser = _SnippetParser()
        parser.feed(resp.text)
        out = []
        for r in parser._results[:limit]:
            out.append({"engine": "ddg-html", "title": r.get("title",""), "url": r.get("url",""), "snippet": ""})
        return out
    except Exception:
        return []


def _ddg_fallback(engine: str, query: str, limit: int) -> list[dict]:
    """Universal fallback: run DDG and re-tag results as coming from `engine`."""
    try:
        results = _search_ddg(query, limit)
        for r in results:
            r["engine"] = f"{engine}-via-ddg"
        return results
    except Exception:
        return []


# =========================================================
# ACADEMIC ENGINES
# =========================================================

def _search_arxiv(query: str, limit: int) -> list[dict]:
    """arXiv API — free, no key required."""
    import requests
    import xml.etree.ElementTree as ET

    url  = f"http://export.arxiv.org/api/query?search_query=all:{quote_plus(query)}&max_results={limit}&sortBy=relevance"
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    results = []
    for entry in root.findall("atom:entry", ns):
        title   = entry.find("atom:title",   ns)
        id_tag  = entry.find("atom:id",      ns)
        summary = entry.find("atom:summary", ns)
        authors = entry.findall("atom:author/atom:name", ns)

        results.append({
            "engine":  "arxiv",
            "title":   (title.text or "").strip().replace("\n", " ") if title   is not None else "",
            "url":     (id_tag.text or "").strip()                   if id_tag  is not None else "",
            "snippet": (summary.text or "").strip().replace("\n"," ") if summary is not None else "",
            "authors": [a.text for a in authors if a.text],
        })
    return results


def _search_crossref(query: str, limit: int) -> list[dict]:
    """CrossRef Works API — free, no key required."""
    import requests

    try:
        resp = requests.get(
            "https://api.crossref.org/works",
            params={"query": query, "rows": limit, "select": "title,URL,publisher,container-title,author,published"},
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    data  = resp.json()
    items = data.get("message", {}).get("items", [])
    results = []
    for item in items:
        title     = item.get("title", [""])[0] if item.get("title") else ""
        container = item.get("container-title", [""])[0] if item.get("container-title") else ""
        publisher = item.get("publisher", "")
        authors   = [
            f"{a.get('given','')} {a.get('family','')}".strip()
            for a in item.get("author", [])
        ]
        pub_parts = item.get("published", {}).get("date-parts", [[]])
        year      = pub_parts[0][0] if pub_parts and pub_parts[0] else None

        results.append({
            "engine":  "crossref",
            "title":   title,
            "url":     item.get("URL", ""),
            "snippet": f"Published in {container} by {publisher} ({year})" if container else publisher,
            "authors": authors,
            "year":    year,
        })
    return results


def _search_semantic_scholar(query: str, limit: int) -> list[dict]:
    """Semantic Scholar Graph API — free tier, optional API key for higher limits."""
    import requests

    headers   = {"User-Agent": USER_AGENT}
    api_key   = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    try:
        resp = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": query, "limit": limit, "fields": "title,url,abstract,authors,year,citationCount"},
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    data = resp.json()
    results = []
    for item in data.get("data", []):
        pid     = item.get("paperId", "")
        authors = [a.get("name","") for a in item.get("authors", [])]
        results.append({
            "engine":   "semantic-scholar",
            "title":    item.get("title", ""),
            "url":      item.get("url","") or f"https://www.semanticscholar.org/paper/{pid}",
            "snippet":  item.get("abstract", "") or "",
            "authors":  authors,
            "year":     item.get("year"),
            "cited_by": item.get("citationCount"),
        })
    return results


# =========================================================
# STANDARD WEB ENGINES
# =========================================================

def _search_bing(query: str, limit: int) -> list[dict]:
    key = os.environ.get("BING_SEARCH_API_KEY")
    if not key:
        return _ddg_fallback("bing", query, limit)
    import requests
    try:
        resp = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": key},
            params={"q": query, "count": min(limit, 50)},
            timeout=DEFAULT_TIMEOUT,
        )
        data = resp.json()
    except Exception:
        return _ddg_fallback("bing", query, limit)
    return [
        {"engine": "bing", "title": i.get("name",""), "url": i.get("url",""), "snippet": i.get("snippet","")}
        for i in data.get("webPages", {}).get("value", [])[:limit]
    ]


def _search_brave(query: str, limit: int) -> list[dict]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        return _ddg_fallback("brave", query, limit)
    import requests
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            params={"q": query, "count": min(limit, 20)},
            timeout=DEFAULT_TIMEOUT,
        )
        data = resp.json()
    except Exception:
        return _ddg_fallback("brave", query, limit)
    return [
        {"engine": "brave", "title": i.get("title",""), "url": i.get("url",""), "snippet": i.get("description","")}
        for i in data.get("web", {}).get("results", [])[:limit]
    ]


def _search_mojeek(query: str, limit: int) -> list[dict]:
    key = os.environ.get("MOJEEK_API_KEY")
    if not key:
        return _ddg_fallback("mojeek", query, limit)
    import requests
    try:
        resp = requests.get(
            "https://www.mojeek.com/api/search",
            params={"q": query, "api_key": key, "t": limit},
            timeout=DEFAULT_TIMEOUT,
        )
        data = resp.json()
    except Exception:
        return _ddg_fallback("mojeek", query, limit)
    return [
        {"engine": "mojeek", "title": i.get("title",""), "url": i.get("url",""), "snippet": i.get("desc","")}
        for i in data.get("response", {}).get("results", [])[:limit]
    ]


def _search_google_cse(query: str, limit: int) -> list[dict]:
    api_key = os.environ.get("GOOGLE_CSE_API_KEY")
    cse_id  = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cse_id:
        return _ddg_fallback("google-cse", query, limit)
    import requests
    out, start = [], 1
    while len(out) < limit:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": api_key, "cx": cse_id, "q": query, "num": min(10, limit - len(out)), "start": start},
                timeout=DEFAULT_TIMEOUT,
            )
            data  = resp.json()
            items = data.get("items", [])
        except Exception:
            break
        if not items:
            break
        for i in items:
            out.append({"engine": "google-cse", "title": i.get("title",""), "url": i.get("link",""), "snippet": i.get("snippet","")})
        start += 10
    return out


def _search_github(query: str, limit: int) -> list[dict]:
    import requests
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token   = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": query, "per_page": limit},
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return _ddg_fallback("github", query, limit)
        data = resp.json()
    except Exception:
        return _ddg_fallback("github", query, limit)
    return [
        {
            "engine":  "github",
            "title":   item.get("full_name",""),
            "url":     item.get("html_url",""),
            "snippet": item.get("description","") or f"Stars: {item.get('stargazers_count',0)}",
        }
        for item in data.get("items", [])[:limit]
    ]


# =========================================================
# DOMAIN-SPECIFIC RESEARCH HELPERS
# (called directly by rnd_report.py as named imports)
# =========================================================

def web_research_financials(company: str, ticker: str | None = None, limit: int = 10) -> list[dict]:
    """
    Multi-engine financial data scraper.
    Returns a list of search result dicts enriched with parsed monetary fields.
    Called by rnd_report.py when Serper turnover command fails.
    """
    queries = [
        f"{company} annual revenue turnover crore FY2024 FY2025",
        f"{company} financial results profit sales billion",
        f"{ticker or company} earnings revenue report",
        f'"{company}" revenue site:moneycontrol.com OR site:screener.in OR site:tofler.in',
        f"{company} annual report consolidated revenue",
    ]
    results: list[dict] = []
    seen:    set[str]   = set()

    for q in queries:
        items = _search_ddg(q, limit=8)
        for item in items:
            url = item.get("url","")
            if url in seen:
                continue
            seen.add(url)
            results.append(item)
        if len(results) >= limit * 2:
            break

    return results[:limit * 2]   # caller will parse monetary values from snippets


def web_research_patents(company: str, product: str, keywords: str = "", limit: int = 20) -> list[dict]:
    """
    Free-web patent search — Google Patents, Espacenet, Lens.org.
    Called by rnd_report.py when Serper /patents fails.
    """
    queries = [
        f"{company} {product} patent site:patents.google.com",
        f"{company} {product} patent site:worldwide.espacenet.com",
        f"{company} {product} {keywords} site:lens.org".strip(),
        f'assignee "{company}" {product} patent filing abstract',
        f"{company} {product} {keywords} patent number claims".strip(),
    ]
    results: list[dict] = []
    seen:    set[str]   = set()

    for q in queries:
        items = _search_ddg(q, limit=10)
        for item in items:
            url = item.get("url","")
            if url in seen:
                continue
            seen.add(url)
            results.append(item)
        if len(results) >= limit:
            break

    return results[:limit]


def web_research_trends(product: str, company: str = "", limit: int = 15) -> list[dict]:
    """
    Market trend signals from free web search.
    Called by rnd_report.py when Serper /news fails.
    """
    queries = [
        f"{product} market size growth forecast 2025 2026 CAGR",
        f"{product} industry trends report",
        f"{company} {product} market share analysis".strip(),
        f"{product} demand outlook investment",
    ]
    results: list[dict] = []
    seen:    set[str]   = set()

    for q in queries:
        items = _search_ddg(q, limit=8)
        for item in items:
            url = item.get("url","")
            if url in seen:
                continue
            seen.add(url)
            results.append(item)
        if len(results) >= limit:
            break

    return results[:limit]


def web_research_competitors(company: str, product: str, limit: int = 15) -> list[dict]:
    """
    Multi-query competitor discovery.
    Called by rnd_report.py as supplementary data.
    """
    queries = [
        f"{product} top competitors companies global",
        f"{product} alternatives vs {company}",
        f"best {product} manufacturers market leaders 2024",
        f"{product} market share companies ranking",
    ]
    results: list[dict] = []
    seen:    set[str]   = set()

    for q in queries:
        items = _search_ddg(q, limit=8)
        for item in items:
            url = item.get("url","")
            if url in seen:
                continue
            seen.add(url)
            results.append(item)
        if len(results) >= limit:
            break

    return results[:limit]


# =========================================================
# ENGINE ROUTER  (used by CLI and by rnd_report._wr_search)
# =========================================================

def cmd_web_search(args: argparse.Namespace) -> dict:
    """
    Route a query through one or all engines.
    De-duplicates results by URL across engines.
    """
    engines = ALL_SEARCH_ENGINES if args.engine == "all" else [args.engine]

    results: list[dict] = []
    errors:  dict[str, str] = {}

    _ENGINE_FN = {
        "ddg":              lambda q, n: _search_ddg(q, n),
        "bing":             lambda q, n: _search_bing(q, n),
        "brave":            lambda q, n: _search_brave(q, n),
        "mojeek":           lambda q, n: _search_mojeek(q, n),
        "google-cse":       lambda q, n: _search_google_cse(q, n),
        "arxiv":            lambda q, n: _search_arxiv(q, n),
        "crossref":         lambda q, n: _search_crossref(q, n),
        "semantic-scholar": lambda q, n: _search_semantic_scholar(q, n),
        "github":           lambda q, n: _search_github(q, n),
    }

    for e in engines:
        fn = _ENGINE_FN.get(e)
        if not fn:
            errors[e] = "Unknown engine"
            continue
        try:
            results.extend(fn(args.query, args.limit))
        except Exception as exc:
            errors[e] = str(exc)

    # Global de-dup by URL
    seen:   set[str]   = set()
    deduped: list[dict] = []
    for r in results:
        k = r.get("url","")
        if not k or k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    return {
        "query":             args.query,
        "engines_attempted": engines,
        "errors":            errors,
        "count":             len(deduped[:args.limit]),
        "results":           deduped[:args.limit],
    }


# =========================================================
# CLI
# =========================================================

def build_parser() -> argparse.ArgumentParser:
    p   = argparse.ArgumentParser(prog="web_research.py", description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("web-search", help="Search across one or all engines")
    s.add_argument("--query",  required=True,  help="Search query string")
    s.add_argument("--engine", default="all",  choices=ALL_SEARCH_ENGINES + ["all"],
                   help="Which engine to use (default: all)")
    s.add_argument("--limit",  type=int, default=10, help="Max results per engine")
    s.set_defaults(func=cmd_web_search)

    # Convenience sub-commands that expose the domain-specific helpers
    fp = sub.add_parser("financials", help="Financial data research for a company")
    fp.add_argument("--company", required=True)
    fp.add_argument("--ticker",  default=None)
    fp.add_argument("--limit",   type=int, default=10)
    fp.set_defaults(func=lambda a: {"results": web_research_financials(a.company, a.ticker, a.limit)})

    pp = sub.add_parser("patents", help="Patent search for a company/product")
    pp.add_argument("--company",  required=True)
    pp.add_argument("--product",  required=True)
    pp.add_argument("--keywords", default="")
    pp.add_argument("--limit",    type=int, default=20)
    pp.set_defaults(func=lambda a: {"results": web_research_patents(a.company, a.product, a.keywords, a.limit)})

    tp = sub.add_parser("trends", help="Market trend research for a product")
    tp.add_argument("--product", required=True)
    tp.add_argument("--company", default="")
    tp.add_argument("--limit",   type=int, default=15)
    tp.set_defaults(func=lambda a: {"results": web_research_trends(a.product, a.company, a.limit)})

    cp = sub.add_parser("competitors", help="Competitor discovery for a product")
    cp.add_argument("--company", required=True)
    cp.add_argument("--product", required=True)
    cp.add_argument("--limit",   type=int, default=15)
    cp.set_defaults(func=lambda a: {"results": web_research_competitors(a.company, a.product, a.limit)})

    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    try:
        out = args.func(args)
        print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
web_research.py — multi-engine web research tool with fallback and academic engine support.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, quote_plus

DEFAULT_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; rnd-research/1.0; mailto:team@research-tool.local)"

# Updated to include academic and code repository engines
ALL_SEARCH_ENGINES = [
    "ddg", "bing", "brave", "mojeek", "google-cse", 
    "arxiv", "crossref", "semantic-scholar", "github"
]


# =========================================================
# CORE FALLBACK ENGINE
# =========================================================

def _search_ddg(query: str, limit: int, region="us-en"):
    try:
        from ddgs import DDGS
    except ImportError:
        # Fallback if duckduckgo_search library isn't installed
        import requests
        resp = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT
        )
        # Basic parsing stub or return empty if library missing
        return []

    results = []
    with DDGS() as ddgs:
        hits = ddgs.text(query, region=region, max_results=limit)

    for h in hits:
        results.append({
            "engine": "ddg",
            "title": h.get("title", ""),
            "url": h.get("href") or h.get("url", ""),
            "snippet": h.get("body", "")
        })
    return results


def _ddg_fallback(engine: str, query: str, limit: int):
    """Universal fallback for ALL engines without API keys or when failure occurs"""
    try:
        results = _search_ddg(query, limit)
        for r in results:
            r["engine"] = f"{engine}-fallback-ddg"
        return results
    except Exception:
        return []


# =========================================================
# NEW ENGINES: ACADEMIC & CODE REPOSITORIES
# =========================================================

def _search_arxiv(query: str, limit: int):
    import requests
    import xml.etree.ElementTree as ET

    url = f"http://export.arxiv.org/api/query?search_query=all:{quote_plus(query)}&max_results={limit}"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        return []

    root = ET.fromstring(resp.text)
    # Handle Atom feed namespaces
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    results = []
    for entry in root.findall('atom:entry', ns):
        title = entry.find('atom:title', ns)
        id_url = entry.find('atom:id', ns)
        summary = entry.find('atom:summary', ns)
        
        results.append({
            "engine": "arxiv",
            "title": title.text.strip().replace("\n", " ") if title is not None else "",
            "url": id_url.text.strip() if id_url is not None else "",
            "snippet": summary.text.strip().replace("\n", " ") if summary is not None else ""
        })
    return results


def _search_crossref(query: str, limit: int):
    import requests
    url = "https://api.crossref.org/works"
    params = {"query": query, "rows": limit}
    
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        return []
    
    data = resp.json()
    items = data.get("message", {}).get("items", [])
    
    results = []
    for item in items:
        title = item.get("title", [""])[0] if item.get("title") else ""
        url = item.get("URL", "")
        
        # CrossRef structure abstracts poorly, piece together metadata as snippet
        publisher = item.get("publisher", "")
        container = item.get("container-title", [""])[0] if item.get("container-title") else ""
        snippet = f"Published in {container} by {publisher}" if container else publisher

        results.append({
            "engine": "crossref",
            "title": title,
            "url": url,
            "snippet": snippet
        })
    return results


def _search_semantic_scholar(query: str, limit: int):
    import requests
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {"query": query, "limit": limit, "fields": "title,url,abstract"}
    
    # Semantic Scholar allows public unauthenticated requests with lower rate-limits
    headers = {"User-Agent": USER_AGENT}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    resp = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        return []

    data = resp.json()
    return [
        {
            "engine": "semantic-scholar",
            "title": item.get("title", ""),
            "url": item.get("url", "") or f"https://www.semanticscholar.org/paper/{item.get('paperId')}",
            "snippet": item.get("abstract", "") or ""
        }
        for item in data.get("data", [])
    ]


def _search_github(query: str, limit: int):
    import requests
    # GitHub Search API requires specific header acceptability
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json"
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = "https://api.github.com/search/repositories"
    params = {"q": query, "per_page": limit}

    resp = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        # Fall back gracefully if rate-limited by unauthenticated API thresholds
        return _ddg_fallback("github", query, limit)

    data = resp.json()
    return [
        {
            "engine": "github",
            "title": item.get("full_name", ""),
            "url": item.get("html_url", ""),
            "snippet": item.get("description", "") or f"Stars: {item.get('stargazers_count')}"
        }
        for item in data.get("items", [])[:limit]
    ]


# =========================================================
# STANDARD WEB ENGINES
# =========================================================

def _search_bing(query: str, limit: int):
    key = os.environ.get("BING_SEARCH_API_KEY")
    if not key:
        return _ddg_fallback("bing", query, limit)

    import requests
    resp = requests.get(
        "https://api.bing.microsoft.com/v7.0/search",
        headers={"Ocp-Apim-Subscription-Key": key},
        params={"q": query, "count": min(limit, 50)},
        timeout=DEFAULT_TIMEOUT,
    )
    data = resp.json()
    return [
        {
            "engine": "bing",
            "title": i.get("name", ""),
            "url": i.get("url", ""),
            "snippet": i.get("snippet", ""),
        }
        for i in data.get("webPages", {}).get("value", [])[:limit]
    ]


def _search_brave(query: str, limit: int):
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        return _ddg_fallback("brave", query, limit)

    import requests
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": key},
        params={"q": query, "count": min(limit, 20)},
        timeout=DEFAULT_TIMEOUT,
    )
    data = resp.json()
    return [
        {
            "engine": "brave",
            "title": i.get("title", ""),
            "url": i.get("url", ""),
            "snippet": i.get("description", ""),
        }
        for i in data.get("web", {}).get("results", [])[:limit]
    ]


def _search_mojeek(query: str, limit: int):
    key = os.environ.get("MOJEEK_API_KEY")
    if not key:
        return _ddg_fallback("mojeek", query, limit)

    import requests
    resp = requests.get(
        "https://www.mojeek.com/api/search",
        params={"q": query, "api_key": key, "t": limit},
        timeout=DEFAULT_TIMEOUT,
    )
    data = resp.json()
    return [
        {
            "engine": "mojeek",
            "title": i.get("title", ""),
            "url": i.get("url", ""),
            "snippet": i.get("desc", ""),
        }
        for i in data.get("response", {}).get("results", [])[:limit]
    ]


def _search_google_cse(query: str, limit: int):
    api_key = os.environ.get("GOOGLE_CSE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")

    if not api_key or not cse_id:
        return _ddg_fallback("google-cse", query, limit)

    import requests
    out = []
    start = 1
    while len(out) < limit:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": cse_id,
                "q": query,
                "num": min(10, limit - len(out)),
                "start": start,
            },
            timeout=DEFAULT_TIMEOUT,
        )
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break

        for i in items:
            out.append({
                "engine": "google-cse",
                "title": i.get("title", ""),
                "url": i.get("link", ""),
                "snippet": i.get("snippet", ""),
            })
        start += 10
    return out


# =========================================================
# ENGINE ROUTER
# =========================================================

def cmd_web_search(args):
    # Setting default engine value to "all" routes queries sequentially through everything
    engines = ALL_SEARCH_ENGINES if args.engine == "all" else [args.engine]

    results = []
    errors = {}

    for e in engines:
        try:
            if e == "ddg":
                results.extend(_search_ddg(args.query, args.limit))
            elif e == "bing":
                results.extend(_search_bing(args.query, args.limit))
            elif e == "brave":
                results.extend(_search_brave(args.query, args.limit))
            elif e == "mojeek":
                results.extend(_search_mojeek(args.query, args.limit))
            elif e == "google-cse":
                results.extend(_search_google_cse(args.query, args.limit))
            elif e == "arxiv":
                results.extend(_search_arxiv(args.query, args.limit))
            elif e == "crossref":
                results.extend(_search_crossref(args.query, args.limit))
            elif e == "semantic-scholar":
                results.extend(_search_semantic_scholar(args.query, args.limit))
            elif e == "github":
                results.extend(_search_github(args.query, args.limit))
        except Exception as exc:
            errors[e] = str(exc)

    # Global cross-engine deduplication by URL
    seen = set()
    deduped = []
    for r in results:
        k = r.get("url", "")
        if not k or k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    return {
        "query": args.query,
        "engines_attempted": engines,
        "errors": errors,
        "count": len(deduped),
        "results": deduped[:args.limit],
    }


# =========================================================
# CLI CONFIGURATION
# =========================================================

def build_parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("web-search")
    s.add_argument("--query", required=True)
    s.add_argument("--engine", default="all", choices=ALL_SEARCH_ENGINES + ["all"])
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_web_search)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        out = args.func(args)
        print(json.dumps(out, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

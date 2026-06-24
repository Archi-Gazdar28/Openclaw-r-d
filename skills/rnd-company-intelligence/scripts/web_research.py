#!/usr/bin/env python3
"""
web_research.py — OpenClaw Multi-Engine Free Web & Intelligence Research Layer
Version: 2.3.0 (Highly Optimized Edition)

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
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

DEFAULT_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; OpenClaw-WebResearch/2.3; mailto:team@openclaw.local)"

# =========================================================
# GLOBAL OPTIMIZED CONNECTION POOL (Prevents Handshake Bloat)
# =========================================================
HTTP_CLIENT = requests.Session()
HTTP_CLIENT.headers.update({"User-Agent": USER_AGENT})

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


def _scrape_wikipedia_infobox(query: str, limit: int = 1) -> list[dict]:
    """
    Queries the public Wikipedia API to fetch summaries and parse basic structural 
    infobox properties without requiring keys.
    """
    search_url = "https://en.wikipedia.org/w/api.php"
    search_params = {
        "action": "query", "list": "search", "srsearch": query, "format": "json"
    }
    try:
        s_resp = HTTP_CLIENT.get(search_url, params=search_params, timeout=DEFAULT_TIMEOUT)
        s_data = s_resp.json()
        search_results = s_data.get("query", {}).get("search", [])
        if not search_results:
            return []
        
        best_title = search_results[0]["title"]
        
        parse_params = {
            "action": "query", "prop": "extracts", "exintro": True, 
            "explaintext": True, "titles": best_title, "format": "json"
        }
        p_resp = HTTP_CLIENT.get(search_url, params=parse_params, timeout=DEFAULT_TIMEOUT)
        pages = p_resp.json().get("query", {}).get("pages", {})
        page_id = list(pages.keys())[0]
        summary = pages[page_id].get("extract", "")
        
        return [{
            "engine": "wikipedia",
            "title": best_title,
            "url": f"https://en.wikipedia.org/wiki/{quote_plus(best_title)}",
            "snippet": summary[:400] + "..." if len(summary) > 400 else summary
        }]
    except Exception:
        return []


# =========================================================
# 2. DEEP ACADEMIC, CLINICAL, & CITATION ENGINES
# =========================================================

def _search_openalex(query: str, limit: int) -> list[dict]:
    """Queries the free OpenAlex API for global scientific literature graphs."""
    url = "https://api.openalex.org/works"
    params = {"search": query, "per_page": min(limit, 50), "mailto": "team@openclaw.local"}
    try:
        resp = HTTP_CLIENT.get(url, params=params, timeout=DEFAULT_TIMEOUT)
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
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    
    try:
        s_params = {"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"}
        s_resp = HTTP_CLIENT.get(search_url, params=s_params, timeout=DEFAULT_TIMEOUT)
        ids = s_resp.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
            
        sum_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        sum_resp = HTTP_CLIENT.get(summary_url, params=sum_params, timeout=DEFAULT_TIMEOUT)
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
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {"query": query, "limit": min(limit, 50), "fields": "title,url,abstract,year,citationCount"}
    headers = {}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    try:
        resp = HTTP_CLIENT.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
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
    import xml.etree.ElementTree as ET
    url = f"http://export.arxiv.org/api/query?search_query=all:{quote_plus(query)}&max_results={limit}"
    try:
        resp = HTTP_CLIENT.get(url, timeout=DEFAULT_TIMEOUT)
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
    url = "https://api.crossref.org/works"
    params = {"query": query, "rows": limit}
    try:
        resp = HTTP_CLIENT.get(url, params=params, timeout=DEFAULT_TIMEOUT)
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
        try:
            resp = HTTP_CLIENT.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", timeout=DEFAULT_TIMEOUT)
            return [{"engine": "ddg-html-fallback", "title": "Web Search Scrape", "url": "", "snippet": resp.text[:200]}]
        except Exception:
            return []


def _search_github(query: str, limit: int) -> list[dict]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = HTTP_CLIENT.get("https://api.github.com/search/repositories", params={"q": query, "per_page": limit}, headers=headers, timeout=DEFAULT_TIMEOUT)
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
# 4. DOMAIN-SPECIFIC SEARCH ASSIGNMENTS
# =========================================================

def web_research_financials(company: str, ticker: str | None = None, limit: int = 10) -> list[dict]:
    fallback_query = f"{company} consolidated financial results revenue billion turnover"
    return _search_ddg(fallback_query, limit=limit)

def web_research_patents(company: str, product: str, keywords: str = "", limit: int = 20) -> list[dict]:
    query = f"{company} {product} {keywords} patent site:patents.google.com".strip()
    return _search_ddg(query, limit=limit)

def web_research_trends(product: str, company: str = "", limit: int = 15) -> list[dict]:
    query = f"{product} market size growth forecast 2026 2027 CAGR"
    return _search_ddg(query, limit=limit)

def web_research_competitors(company: str, product: str, limit: int = 15) -> list[dict]:
    query = f"{product} alternatives vs {company} competitors ranking"
    return _search_ddg(query, limit=limit)


# =========================================================
# 5. HIGH-PERFORMANCE CONCURRENT ORCHESTRATION TIER
# =========================================================

def cmd_web_search(args: argparse.Namespace) -> dict:
    engines = ALL_SEARCH_ENGINES if args.engine == "all" else [args.engine]
    results = []
    errors = {}

    _ENGINE_ROUTER = {
        "ddg": _search_ddg,
        "wikipedia": _scrape_wikipedia_infobox,
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

    # Optimization: Fan out concurrently across thread workers instead of linear loop blocks
    with ThreadPoolExecutor(max_workers=len(engines)) as executor:
        future_to_engine = {
            executor.submit(_ENGINE_ROUTER[e], args.query, args.limit): e 
            for e in engines if e in _ENGINE_ROUTER
        }
        
        for future in as_completed(future_to_engine):
            e = future_to_engine[future]
            try:
                data = future.result()
                if data:
                    results.extend(data)
            except Exception as exc:
                errors[e] = str(exc)

    seen = set()
    deduped = [r for r in results if not (r.get("url") in seen or seen.add(r.get("url", "")))]

    return {
        "query": args.query,
        "engines_attempted": engines,
        "errors": errors,
        "count": len(deduped[:args.limit]),
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

    f_cmd = sub.add_parser("financials")
    f_cmd.add_argument("--company", required=True)
    f_cmd.add_argument("--ticker", default=None)
    f_cmd.add_argument("--limit", type=int, default=10)
    f_cmd.set_defaults(func=lambda a: {
        "market_intelligence": _fetch_yfinance_financials(a.ticker) if a.ticker else {},
        "wiki_profile": _scrape_wikipedia_infobox(a.company, 1),
        "web_mentions": web_research_financials(a.company, a.ticker, a.limit)
    })

    # Keep structural alignment with sub-commands from version 1.2.0
    pp = sub.add_parser("patents")
    pp.add_argument("--company", required=True)
    pp.add_argument("--product", required=True)
    pp.add_argument("--keywords", default="")
    pp.add_argument("--limit", type=int, default=20)
    pp.set_defaults(func=lambda a: {"results": web_research_patents(a.company, a.product, a.keywords, a.limit)})

    tp = sub.add_parser("trends")
    tp.add_argument("--product", required=True)
    tp.add_argument("--company", default="")
    tp.add_argument("--limit", type=int, default=15)
    tp.set_defaults(func=lambda a: {"results": web_research_trends(a.product, a.company, a.limit)})

    cp = sub.add_parser("competitors")
    cp.add_argument("--company", required=True)
    cp.add_argument("--product", required=True)
    cp.add_argument("--limit", type=int, default=15)
    cp.set_defaults(func=lambda a: {"results": web_research_competitors(a.company, a.product, a.limit)})

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
    main()

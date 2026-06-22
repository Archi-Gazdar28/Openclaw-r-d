#!/usr/bin/env python3
"""
rnd_report.py  —  OpenClaw R&D Company Intelligence
Version: 2.0.0

Wraps four paid APIs:
  • Crunchbase  (CRUNCHBASE_API_KEY)   — company profile, funding, similar companies
  • SerpApi     (SERPAPI_KEY)          — patents, trends, scholar, knowledge panel
  • Financial Modeling Prep (FMP_API_KEY) — public company revenue / income statement
  • BuiltWith   (BUILTWITH_API_KEY)    — tech stack detection (optional)

Commands
--------
  company-details    Company + product profile (Crunchbase + SerpApi knowledge panel)
  turnover           Financials: public → FMP income statement; private → Crunchbase funding
  patents            Google Patents via SerpApi, grouped by tech area
  trends             Google Trends via SerpApi (interest-over-time + by-region)
  competitors        Crunchbase similar companies + SerpApi web search, merged & deduped
  research-papers    Google Scholar via SerpApi
  tech-stack-detect  BuiltWith tech-stack lookup (falls back to web-search hint)
  full-report        Orchestrates all of the above, writes report.json to --output path

All results are written as structured JSON (stdout or --output file) for the agent
to consume when rendering the chat report and charts.  Nothing is printed as prose
here — the agent handles synthesis and rendering.

Anti-hallucination contract
---------------------------
Every field in the returned JSON is either:
  • "reported"  — directly from a paid-API response field
  • "sourced"   — from a web/search snippet (key suffixed "_source" carries the URL)
  • null / ""   — genuinely not returned; the agent must write "Not disclosed" in
                  the report, never fill the gap with an estimate

Usage
-----
  python3 rnd_report.py <command> [options]
  python3 rnd_report.py --help
  python3 rnd_report.py <command> --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, date
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

CRUNCHBASE_BASE = "https://api.crunchbase.com/api/v4"
SERPAPI_BASE    = "https://serpapi.com/search"
FMP_BASE        = "https://financialmodelingprep.com/api/v3"
BUILTWITH_BASE  = "https://api.builtwith.com/v21/api.json"

VERSION = "2.0.0"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": f"OpenClaw-rnd-report/{VERSION}"})


def _env(name: str, required: bool = True) -> str | None:
    val = os.environ.get(name)
    if required and not val:
        _die(
            f"Missing required environment variable: {name}\n"
            f"Set it with:  export {name}=<your-key>"
        )
    return val or None


def _die(msg: str, code: int = 1) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(code)


def _get(url: str, params: dict, label: str, timeout: int = 30) -> dict:
    """GET with consistent error handling; returns parsed JSON or raises."""
    try:
        r = _SESSION.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        _die(f"Network error calling {label}: {exc}")
    if r.status_code == 401:
        _die(f"401 Unauthorized from {label} — check your API key env var.")
    if r.status_code == 403:
        _die(f"403 Forbidden from {label} — key may be expired or plan limit hit.")
    if r.status_code == 429:
        retry = int(r.headers.get("Retry-After", 60))
        _die(
            f"429 Rate-limited by {label}. "
            f"Wait {retry}s then retry.  (Retry-After: {retry})"
        )
    if r.status_code >= 500:
        _die(f"{r.status_code} Server error from {label}. Try again shortly.")
    if r.status_code >= 400:
        _die(
            f"{r.status_code} Client error from {label}: "
            f"{r.text[:300]}"
        )
    try:
        return r.json()
    except ValueError:
        _die(f"Non-JSON response from {label}: {r.text[:300]}")


def _out(data: Any, output_path: str | None) -> None:
    """Serialise `data` to JSON, writing to --output path or stdout."""
    payload = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(payload, encoding="utf-8")
        print(f"[rnd_report] Written → {p}", file=sys.stderr)
    else:
        print(payload)


def _today() -> str:
    return date.today().isoformat()


def _slug(text: str) -> str:
    return text.lower().replace(" ", "-").replace("/", "-")


# ---------------------------------------------------------------------------
# Crunchbase helpers
# ---------------------------------------------------------------------------

def _cb_headers() -> dict:
    return {"X-cb-user-key": _env("CRUNCHBASE_API_KEY")}


def _cb_find_org(company: str, domain: str | None = None,
                 hq_country: str | None = None) -> dict | None:
    """
    Search Crunchbase for an organization matching `company`.
    Returns the best-matching entity dict or None.
    Disambiguation hints: domain, hq_country.
    """
    params: dict = {
        "field_ids": "short_description,legal_name,website,country_code,founded_on,"
                     "num_employees_enum,total_funding_usd,last_funding_type,"
                     "last_funding_at,rank_org",
        "query": json.dumps([{
            "type": "predicate",
            "field_id": "facet_ids",
            "operator_id": "includes",
            "values": ["company"],
        }]),
        "name": company,
        "limit": 5,
        "user_key": _env("CRUNCHBASE_API_KEY"),
    }
    data = _get(
        f"{CRUNCHBASE_BASE}/searches/organizations",
        params={},
        label="Crunchbase org-search",
    )
    # Crunchbase v4 uses POST for searches; retry as POST
    try:
        r = _SESSION.post(
            f"{CRUNCHBASE_BASE}/searches/organizations",
            params={"user_key": _env("CRUNCHBASE_API_KEY")},
            json={
                "field_ids": [
                    "short_description", "legal_name", "website_url",
                    "country_code", "founded_on", "num_employees_enum",
                    "total_funding_usd", "last_funding_type",
                    "last_funding_at", "rank_org", "uuid",
                ],
                "query": [
                    {
                        "type": "predicate",
                        "field_id": "facet_ids",
                        "operator_id": "includes",
                        "values": ["company"],
                    }
                ],
                "name": company,
                "limit": 5,
                "order": [{"field_id": "rank_org", "sort": "asc"}],
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        _die(f"Network error calling Crunchbase org-search: {exc}")

    if r.status_code == 401:
        _die("401 Unauthorized from Crunchbase — check CRUNCHBASE_API_KEY.")
    if r.status_code == 429:
        _die("429 Rate-limited by Crunchbase. Wait then retry.")
    if r.status_code >= 400:
        _die(f"{r.status_code} Crunchbase error: {r.text[:300]}")

    try:
        data = r.json()
    except ValueError:
        _die(f"Non-JSON from Crunchbase: {r.text[:200]}")

    entities = data.get("entities", [])
    if not entities:
        return None

    # Apply disambiguation hints
    for ent in entities:
        props = ent.get("properties", {})
        if domain and domain.lower() in (props.get("website_url") or "").lower():
            return props
        if hq_country and (props.get("country_code") or "").upper() == hq_country.upper():
            return props

    # Fall back to top-ranked result
    return entities[0].get("properties", {})


def _cb_entity(uuid: str, card_ids: list[str]) -> dict:
    """Fetch a specific Crunchbase entity by UUID with requested card_ids."""
    params = {
        "user_key": _env("CRUNCHBASE_API_KEY"),
        "card_ids": ",".join(card_ids),
    }
    return _get(
        f"{CRUNCHBASE_BASE}/entities/organizations/{uuid}",
        params=params,
        label="Crunchbase entity",
    )


def _cb_similar(uuid: str, limit: int = 10) -> list[dict]:
    """Return Crunchbase 'similar companies' for the given org UUID."""
    data = _cb_entity(uuid, ["similar_companies"])
    items = (
        data.get("cards", {})
            .get("similar_companies", [])
    )
    return items[:limit]


def _cb_funding_rounds(uuid: str) -> list[dict]:
    """Return all funding rounds for the org, newest first."""
    data = _cb_entity(uuid, ["funding_rounds"])
    rounds = data.get("cards", {}).get("funding_rounds", [])
    return sorted(rounds, key=lambda r: r.get("announced_on") or "", reverse=True)


def _cb_people(uuid: str) -> list[dict]:
    """Return board members / key people."""
    data = _cb_entity(uuid, ["founders", "current_team"])
    founders = data.get("cards", {}).get("founders", [])
    team     = data.get("cards", {}).get("current_team", [])
    return founders + team


# ---------------------------------------------------------------------------
# SerpApi helpers
# ---------------------------------------------------------------------------

def _serp(engine: str, extra: dict) -> dict:
    key = _env("SERPAPI_KEY")
    params = {"api_key": key, "engine": engine, **extra}
    return _get(SERPAPI_BASE, params=params, label=f"SerpApi/{engine}")


def _serp_knowledge_panel(query: str) -> dict:
    data = _serp("google", {"q": query, "gl": "us", "hl": "en"})
    return data.get("knowledge_graph", {})


def _serp_patents(assignee: str, keywords: str,
                  since: str | None, limit: int) -> list[dict]:
    query = f'assignee:"{assignee}" {keywords}'
    params: dict = {"q": query, "num": min(limit, 100)}
    if since:
        params["as_ylo"] = since
    data = _serp("google_patents", params)
    return data.get("organic_results", [])[:limit]


def _serp_trends(keyword: str, geo: str = "", since: str | None = None) -> dict:
    date_range = f"{since}-01-01 {_today()}" if since else "today 5-y"
    data = _serp("google_trends", {
        "q": keyword,
        "geo": geo,
        "data_type": "TIMESERIES",
        "date": date_range,
        "hl": "en",
    })
    timeline   = data.get("interest_over_time", {}).get("timeline_data", [])
    by_region  = data.get("interest_by_region", [])
    related_q  = data.get("related_queries", {})
    return {
        "timeline": timeline,
        "by_region": by_region,
        "related_queries": related_q,
        "source": "SerpApi/google_trends",
    }


def _serp_scholar(keywords: str, since: str | None, limit: int) -> list[dict]:
    params: dict = {"q": keywords, "num": min(limit, 20)}
    if since:
        params["as_ylo"] = since
    data = _serp("google_scholar", params)
    return data.get("organic_results", [])[:limit]


def _serp_web(query: str, limit: int = 10) -> list[dict]:
    data = _serp("google", {"q": query, "num": min(limit, 10), "gl": "us", "hl": "en"})
    return data.get("organic_results", [])[:limit]


# ---------------------------------------------------------------------------
# Financial Modeling Prep helpers
# ---------------------------------------------------------------------------

def _fmp_income(ticker: str, years: int = 5) -> list[dict]:
    """Pull annual income statement for a public ticker (last N years)."""
    key = _env("FMP_API_KEY", required=False)
    if not key:
        return []
    data = _get(
        f"{FMP_BASE}/income-statement/{ticker}",
        params={"apikey": key, "limit": years},
        label="FMP income-statement",
    )
    return data if isinstance(data, list) else []


def _fmp_profile(ticker: str) -> dict:
    key = _env("FMP_API_KEY", required=False)
    if not key:
        return {}
    data = _get(
        f"{FMP_BASE}/profile/{ticker}",
        params={"apikey": key},
        label="FMP profile",
    )
    return data[0] if isinstance(data, list) and data else {}


# ---------------------------------------------------------------------------
# BuiltWith helpers
# ---------------------------------------------------------------------------

def _builtwith(domain: str) -> dict:
    key = _env("BUILTWITH_API_KEY", required=False)
    if not key:
        return {"error": "BUILTWITH_API_KEY not set — fallback to web search required"}
    data = _get(
        BUILTWITH_BASE,
        params={"KEY": key, "LOOKUP": domain},
        label="BuiltWith",
    )
    return data


# ---------------------------------------------------------------------------
# Chart generation (matplotlib)
# ---------------------------------------------------------------------------

def _charts_dir(output_path: str | None, company: str, product: str) -> Path:
    if output_path:
        base = Path(output_path).parent
    else:
        base = Path.home() / ".openclaw" / "workspace" / "reports" / \
               f"{_slug(company)}_{_slug(product)}_{_today()}"
    charts = base / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    return charts


def _save_bar_chart(
    labels: list[str],
    values: list[float],
    title: str,
    xlabel: str,
    ylabel: str,
    filepath: Path,
    color: str = "#2c5f8a",
) -> str:
    """Generate a bar chart and save as PNG. Returns filepath str."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        bars = ax.bar(labels, values, color=color, edgecolor="#333333", linewidth=0.7)
        ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.tick_params(axis="x", labelrotation=30)

        # Value labels on top of bars
        for bar, val in zip(bars, values):
            if val:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() * 1.01,
                    f"{val:,.0f}",
                    ha="center", va="bottom", fontsize=8,
                )

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        plt.tight_layout()
        plt.savefig(str(filepath), bbox_inches="tight", dpi=150,
                    facecolor="white")
        plt.close(fig)
        return str(filepath)
    except Exception as exc:
        return f"CHART_SKIPPED: {exc}"


def _save_pie_chart(
    labels: list[str],
    values: list[float],
    title: str,
    filepath: Path,
) -> str:
    """Generate a pie chart (share-of-whole, ≤6 segments). Returns filepath str."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        PALETTE = ["#2c5f8a", "#4a9eca", "#8db8d8", "#c5ddef",
                   "#6b6b6b", "#b0b0b0"]

        # Collapse anything beyond 5 into "Other"
        if len(labels) > 6:
            other_val = sum(values[5:])
            labels = labels[:5] + ["Other"]
            values = values[:5] + [other_val]

        colors = PALETTE[:len(labels)]

        fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
        fig.patch.set_facecolor("white")

        wedges, texts, autotexts = ax.pie(
            values, labels=None, autopct="%1.1f%%",
            colors=colors, startangle=140,
            wedgeprops={"edgecolor": "white", "linewidth": 1.2},
        )
        for at in autotexts:
            at.set_fontsize(8)

        ax.legend(wedges, labels, loc="center left",
                  bbox_to_anchor=(1.0, 0.5), fontsize=8)
        ax.set_title(title, fontsize=12, fontweight="bold", pad=10)

        plt.tight_layout()
        plt.savefig(str(filepath), bbox_inches="tight", dpi=150,
                    facecolor="white")
        plt.close(fig)
        return str(filepath)
    except Exception as exc:
        return f"CHART_SKIPPED: {exc}"


def _save_line_chart(
    labels: list[str],
    values: list[float],
    title: str,
    xlabel: str,
    ylabel: str,
    filepath: Path,
) -> str:
    """Generate a line chart. Returns filepath str."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 4), dpi=150)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        ax.plot(labels, values, color="#2c5f8a", linewidth=2,
                marker="o", markersize=3)
        ax.fill_between(labels, values, alpha=0.12, color="#2c5f8a")
        ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)

        # Only show every Nth label to avoid clutter
        n = len(labels)
        step = max(1, n // 10)
        ax.set_xticks(range(0, n, step))
        ax.set_xticklabels(
            [labels[i] for i in range(0, n, step)],
            rotation=30, ha="right", fontsize=8,
        )

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        plt.tight_layout()
        plt.savefig(str(filepath), bbox_inches="tight", dpi=150,
                    facecolor="white")
        plt.close(fig)
        return str(filepath)
    except Exception as exc:
        return f"CHART_SKIPPED: {exc}"


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

# ── 1. company-details ──────────────────────────────────────────────────────

def cmd_company_details(args: argparse.Namespace) -> dict:
    """
    Pull Crunchbase org profile + SerpApi knowledge panel for the product.
    Returns a single dict with keys: profile, knowledge_panel, funding_rounds,
    people, data_gaps.
    """
    company = args.company
    product = args.product
    domain  = getattr(args, "domain", None)
    hq      = getattr(args, "hq_country", None)

    gaps: list[str] = []

    # --- Crunchbase ---
    print(f"[company-details] Searching Crunchbase for '{company}'…", file=sys.stderr)
    org = _cb_find_org(company, domain=domain, hq_country=hq)

    profile: dict = {}
    uuid: str | None = None
    funding_rounds: list[dict] = []
    people: list[dict] = []

    if not org:
        gaps.append(f"Crunchbase returned no match for '{company}'. "
                    f"Try --domain or --hq-country to disambiguate.")
    else:
        uuid = org.get("uuid") or org.get("identifier", {}).get("uuid")
        profile = {
            "legal_name":          org.get("legal_name"),
            "short_description":   org.get("short_description"),
            "website_url":         org.get("website_url"),
            "country_code":        org.get("country_code"),
            "founded_on":          org.get("founded_on"),
            "num_employees_enum":  org.get("num_employees_enum"),
            "total_funding_usd":   org.get("total_funding_usd"),
            "last_funding_type":   org.get("last_funding_type"),
            "last_funding_at":     org.get("last_funding_at"),
            "crunchbase_source":   "Crunchbase API v4",
        }
        if uuid:
            print(f"[company-details] Fetching funding rounds & people for UUID {uuid}…",
                  file=sys.stderr)
            try:
                funding_rounds = _cb_funding_rounds(uuid)
            except SystemExit:
                gaps.append("Could not fetch Crunchbase funding rounds.")

            try:
                people = _cb_people(uuid)
            except SystemExit:
                gaps.append("Could not fetch Crunchbase leadership/team.")

    # --- SerpApi knowledge panel for product ---
    print(f"[company-details] Fetching SerpApi knowledge panel for '{company} {product}'…",
          file=sys.stderr)
    kp: dict = {}
    try:
        kp = _serp_knowledge_panel(f"{company} {product}")
        if not kp:
            kp = _serp_knowledge_panel(product)
        if not kp:
            gaps.append(
                f"SerpApi returned no knowledge panel for '{company} {product}'. "
                "Product overview will rely on Crunchbase description only."
            )
    except SystemExit as exc:
        gaps.append(f"SerpApi knowledge panel failed: {exc}")

    return {
        "command":        "company-details",
        "as_of":          _today(),
        "company":        company,
        "product":        product,
        "profile":        profile,
        "knowledge_panel": kp,
        "funding_rounds": funding_rounds,
        "people":         people,
        "data_gaps":      gaps,
    }


# ── 2. turnover ──────────────────────────────────────────────────────────────

def cmd_turnover(args: argparse.Namespace) -> dict:
    """
    Public company → FMP income statement (last 5 years).
    Private company → Crunchbase funding history + valuation.
    Returns: turnover_data, chart_data, source_label, data_gaps.
    """
    company  = args.company
    ticker   = getattr(args, "ticker", None)
    is_pub   = getattr(args, "public",  False)
    is_priv  = getattr(args, "private", False)
    gaps: list[str] = []

    result: dict = {
        "command":      "turnover",
        "as_of":        _today(),
        "company":      company,
        "ticker":       ticker,
        "is_public":    is_pub,
        "rows":         [],
        "chart_data":   {},
        "source_label": "",
        "data_gaps":    gaps,
    }

    if ticker or is_pub:
        # ── Public path: FMP ──
        result["is_public"] = True
        if not ticker:
            # Try to guess ticker from profile name via SerpApi
            print(f"[turnover] No ticker supplied — searching for '{company}' ticker…",
                  file=sys.stderr)
            hits = _serp_web(f"{company} stock ticker symbol site:finance.yahoo.com OR"
                             f" site:marketwatch.com", limit=3)
            if hits:
                gaps.append(
                    f"Ticker not supplied; used web search to locate it. "
                    f"Result snippet: {hits[0].get('snippet','')[:120]}"
                )

        key = _env("FMP_API_KEY", required=False)
        if not key:
            gaps.append("FMP_API_KEY not set — cannot pull income statement.")
        elif ticker:
            print(f"[turnover] Pulling FMP income statement for {ticker}…",
                  file=sys.stderr)
            income_rows = _fmp_income(ticker, years=5)
            if not income_rows:
                gaps.append(
                    f"FMP returned no income statement rows for ticker '{ticker}'. "
                    "Verify the ticker is correct and the company is publicly traded."
                )
            else:
                result["rows"] = [
                    {
                        "fiscal_year":      r.get("calendarYear") or r.get("date", "")[:4],
                        "revenue_usd":      r.get("revenue"),
                        "gross_profit_usd": r.get("grossProfit"),
                        "net_income_usd":   r.get("netIncome"),
                        "ebitda_usd":       r.get("ebitda"),
                        "eps":              r.get("eps"),
                        "source":           "Financial Modeling Prep",
                    }
                    for r in income_rows
                ]
                years  = [row["fiscal_year"] for row in result["rows"]]
                revs   = [row["revenue_usd"] or 0 for row in result["rows"]]
                result["chart_data"] = {
                    "bar_revenue_by_year": {
                        "labels": years[::-1],
                        "values": revs[::-1],
                        "title":  f"{company} — Annual Revenue (USD)",
                        "xlabel": "Fiscal Year",
                        "ylabel": "Revenue (USD)",
                    }
                }
                result["source_label"] = "Financial Modeling Prep (reported)"
    else:
        # ── Private path: Crunchbase funding rounds ──
        result["is_public"] = False
        print(f"[turnover] Private company — pulling Crunchbase funding data…",
              file=sys.stderr)
        org = _cb_find_org(company)
        if not org:
            gaps.append(f"Crunchbase: no match for '{company}'. "
                        "Funding data unavailable.")
        else:
            uuid = org.get("uuid") or org.get("identifier", {}).get("uuid")
            rounds: list[dict] = []
            if uuid:
                try:
                    rounds = _cb_funding_rounds(uuid)
                except SystemExit:
                    gaps.append("Crunchbase funding rounds call failed.")

            result["total_funding_usd"] = org.get("total_funding_usd")
            result["last_funding_type"] = org.get("last_funding_type")
            result["last_funding_at"]   = org.get("last_funding_at")
            result["rows"] = [
                {
                    "announced_on":      r.get("announced_on"),
                    "round_type":        r.get("investment_type"),
                    "raised_usd":        r.get("raised_amount_usd"),
                    "lead_investors":    [
                        i.get("investor", {}).get("value")
                        for i in r.get("lead_investors", [])
                    ],
                    "source": "Crunchbase API v4",
                }
                for r in rounds
            ]
            # Round-type breakdown for pie chart
            type_totals: dict[str, float] = {}
            for r in rounds:
                rtype = r.get("investment_type") or "Unknown"
                amt   = r.get("raised_amount_usd") or 0
                type_totals[rtype] = type_totals.get(rtype, 0) + amt

            sorted_types = sorted(type_totals.items(), key=lambda x: -x[1])
            result["chart_data"] = {
                "bar_funding_by_round": {
                    "labels": [r.get("announced_on", "?") for r in rounds][::-1]
                              or [],
                    "values": [r.get("raised_amount_usd") or 0 for r in rounds][::-1]
                              or [],
                    "title":  f"{company} — Funding Raised per Round (USD)",
                    "xlabel": "Round date",
                    "ylabel": "Amount raised (USD)",
                },
                "pie_funding_by_type": {
                    "labels": [t[0] for t in sorted_types],
                    "values": [t[1] for t in sorted_types],
                    "title":  f"{company} — Funding by Round Type",
                },
            }
            result["source_label"] = "Crunchbase (funding data, not revenue)"
            result["data_gaps"].append(
                "This company appears to be private. "
                "Revenue figures are not publicly disclosed; "
                "figures shown are funding raised, not revenue."
            )

    return result


# ── 3. patents ───────────────────────────────────────────────────────────────

def cmd_patents(args: argparse.Namespace) -> dict:
    """
    Pull patents from Google Patents (via SerpApi).
    Groups results by CPC/tech area and builds per-year filing counts.
    """
    company  = args.company
    product  = args.product
    keywords = getattr(args, "keywords", "") or ""
    since    = getattr(args, "since",    None)
    limit    = getattr(args, "limit",    50)
    gaps: list[str] = []

    query_kw = f"{product} {keywords}".strip()
    print(f"[patents] Querying Google Patents: assignee='{company}' kw='{query_kw}'…",
          file=sys.stderr)

    raw: list[dict] = []
    try:
        raw = _serp_patents(company, query_kw, since, limit)
    except SystemExit as exc:
        gaps.append(f"SerpApi/google_patents call failed: {exc}")

    if not raw:
        gaps.append(
            f"SerpApi returned no patent results for assignee='{company}' "
            f"keywords='{query_kw}'. "
            "Verify the assignee name matches exactly as it appears on patents."
        )

    # Normalise rows
    patents: list[dict] = []
    year_counts: dict[str, int] = {}

    for p in raw:
        pub_date = p.get("publication_date") or p.get("priority_date") or ""
        year = pub_date[:4] if pub_date else "Unknown"
        year_counts[year] = year_counts.get(year, 0) + 1

        cpc_groups: list[str] = []
        for cpc in p.get("cpc_classifications", []):
            group = (cpc.get("group") or cpc.get("code") or "")[:4]
            if group and group not in cpc_groups:
                cpc_groups.append(group)

        patents.append({
            "title":             p.get("title"),
            "patent_id":         p.get("patent_id"),
            "assignee":          p.get("assignee"),
            "inventors":         p.get("inventor") or p.get("inventors"),
            "publication_date":  pub_date,
            "filing_date":       p.get("filing_date"),
            "priority_date":     p.get("priority_date"),
            "cpc_codes":         cpc_groups,
            "abstract_snippet":  (p.get("snippet") or "")[:300],
            "link":              p.get("pdf") or p.get("link"),
            "source":            "SerpApi/google_patents",
        })

    # Tech-area grouping by CPC prefix
    tech_areas: dict[str, int] = {}
    for pat in patents:
        for code in pat["cpc_codes"]:
            tech_areas[code] = tech_areas.get(code, 0) + 1

    sorted_years = dict(sorted(year_counts.items()))

    return {
        "command":    "patents",
        "as_of":      _today(),
        "company":    company,
        "product":    product,
        "keywords":   keywords,
        "since":      since,
        "count":      len(patents),
        "patents":    patents,
        "tech_areas": tech_areas,
        "year_counts": sorted_years,
        "chart_data": {
            "bar_filings_per_year": {
                "labels": list(sorted_years.keys()),
                "values": list(sorted_years.values()),
                "title":  f"{company} / {product} — Patent Filings per Year",
                "xlabel": "Year",
                "ylabel": "Number of patents",
            }
        },
        "data_gaps":  gaps,
    }


# ── 4. trends ─────────────────────────────────────────────────────────────────

def cmd_trends(args: argparse.Namespace) -> dict:
    """
    Pull Google Trends data via SerpApi:
    interest-over-time, interest-by-region, related/rising queries.
    """
    product = args.product
    geo     = getattr(args, "geo",   "")
    since   = getattr(args, "since", None)
    gaps: list[str] = []

    print(f"[trends] Pulling Google Trends for '{product}' geo='{geo or 'worldwide'}'…",
          file=sys.stderr)

    trend_data: dict = {}
    try:
        trend_data = _serp_trends(product, geo=geo, since=since)
    except SystemExit as exc:
        gaps.append(f"SerpApi/google_trends call failed: {exc}")

    timeline   = trend_data.get("timeline", [])
    by_region  = trend_data.get("by_region", [])
    related_q  = trend_data.get("related_queries", {})

    # Prepare chart data
    tl_labels = [pt.get("date") or pt.get("timestamp", "") for pt in timeline]
    tl_values = []
    for pt in timeline:
        vals = pt.get("values", [{}])
        extracted = vals[0].get("extracted_value") if vals else None
        tl_values.append(float(extracted) if extracted is not None else 0.0)

    region_top = sorted(by_region, key=lambda x: x.get("value", 0), reverse=True)[:10]
    reg_labels = [r.get("location") or r.get("geo") or "?" for r in region_top]
    reg_values = [float(r.get("value") or 0) for r in region_top]

    if not tl_labels:
        gaps.append(
            f"Google Trends returned no timeline data for '{product}'. "
            "The keyword may be too niche or misspelled."
        )

    return {
        "command":        "trends",
        "as_of":          _today(),
        "product":        product,
        "geo":            geo or "worldwide",
        "since":          since,
        "timeline":       timeline,
        "by_region":      by_region,
        "related_queries": related_q,
        "chart_data": {
            "line_interest_over_time": {
                "labels": tl_labels,
                "values": tl_values,
                "title":  f"Search Interest Over Time — {product}",
                "xlabel": "Date",
                "ylabel": "Interest (0–100)",
            },
            "pie_interest_by_region": {
                "labels": reg_labels,
                "values": reg_values,
                "title":  f"Search Interest by Region — {product}",
            } if len(reg_labels) >= 2 else None,
        },
        "data_gaps": gaps,
    }


# ── 5. competitors ────────────────────────────────────────────────────────────

def cmd_competitors(args: argparse.Namespace) -> dict:
    """
    Merge Crunchbase similar-companies with SerpApi web search results.
    Dedupe by normalised name. Return a ranked list with profile snippets.
    """
    company  = args.company
    product  = args.product
    industry = getattr(args, "industry", None)
    known    = [k.strip() for k in (getattr(args, "known", "") or "").split(",") if k.strip()]
    limit    = getattr(args, "limit", 15)
    gaps: list[str] = []

    seen_names: set[str] = set()
    competitors: list[dict] = []

    def _add(name: str, source: str, description: str = "",
             website: str = "", funding_usd: float | None = None,
             founded: str = "") -> None:
        key = name.lower().strip()
        if key in seen_names or key == company.lower():
            return
        seen_names.add(key)
        competitors.append({
            "name":        name,
            "description": description,
            "website":     website,
            "funding_usd": funding_usd,
            "founded":     founded,
            "source":      source,
        })

    # Seed from known list
    for k in known:
        _add(k, source="user-provided")

    # --- Crunchbase similar companies ---
    print(f"[competitors] Searching Crunchbase similar companies for '{company}'…",
          file=sys.stderr)
    org = _cb_find_org(company)
    uuid: str | None = None
    if org:
        uuid = org.get("uuid") or org.get("identifier", {}).get("uuid")

    if uuid:
        try:
            similar = _cb_similar(uuid, limit=limit)
            for s in similar:
                props = s if "legal_name" in s else s.get("properties", s)
                _add(
                    name=props.get("legal_name") or props.get("name") or "",
                    source="Crunchbase similar_companies",
                    description=props.get("short_description", ""),
                    website=props.get("website_url", ""),
                    funding_usd=props.get("total_funding_usd"),
                    founded=props.get("founded_on", ""),
                )
        except SystemExit:
            gaps.append("Crunchbase similar-companies call failed.")
    else:
        gaps.append("Could not find company UUID in Crunchbase — similar-companies step skipped.")

    # --- SerpApi web search for alternatives ---
    industry_hint = f" {industry}" if industry else ""
    queries = [
        f"{product} alternatives competitors{industry_hint}",
        f"companies similar to {company} {product}{industry_hint}",
        f"best {product} competitors 2024",
    ]
    for q in queries:
        if len(competitors) >= limit:
            break
        print(f"[competitors] SerpApi web search: {q!r}…", file=sys.stderr)
        try:
            hits = _serp_web(q, limit=10)
        except SystemExit as exc:
            gaps.append(f"SerpApi web search failed for query '{q}': {exc}")
            continue
        for h in hits:
            snippet = h.get("snippet") or ""
            title   = h.get("title")   or ""
            link    = h.get("link")    or ""
            # Simple heuristic: if the title looks like a company/product name,
            # register it. We don't invent names from snippets.
            if title and len(title) < 80:
                _add(title, source="SerpApi web search (via snippet)",
                     description=snippet[:200], website=link)

    return {
        "command":     "competitors",
        "as_of":       _today(),
        "company":     company,
        "product":     product,
        "industry":    industry,
        "count":       len(competitors),
        "competitors": competitors[:limit],
        "chart_data": {
            "bar_competitors": {
                "labels": [c["name"] for c in competitors[:10]
                           if c.get("funding_usd")],
                "values": [c.get("funding_usd") or 0
                           for c in competitors[:10]
                           if c.get("funding_usd")],
                "title":  f"Total Funding — {company} vs Competitors (USD)",
                "xlabel": "Company",
                "ylabel": "Total Funding (USD)",
            },
        },
        "data_gaps": gaps,
    }


# ── 6. research-papers ────────────────────────────────────────────────────────

def cmd_research_papers(args: argparse.Namespace) -> dict:
    """
    Query Google Scholar (SerpApi).  Returns structured paper list.
    The agent should supplement this with arxiv-search / semantic-scholar
    via web_research.py.
    """
    product  = args.product
    keywords = getattr(args, "keywords", "") or ""
    since    = getattr(args, "since",    None)
    limit    = getattr(args, "limit",    20)
    gaps: list[str] = []

    query = f"{product} {keywords}".strip()
    print(f"[research-papers] Querying Google Scholar: {query!r} …", file=sys.stderr)

    raw: list[dict] = []
    try:
        raw = _serp_scholar(query, since=since, limit=limit)
    except SystemExit as exc:
        gaps.append(f"SerpApi/google_scholar failed: {exc}")

    if not raw:
        gaps.append(
            f"Google Scholar returned no results for '{query}'. "
            "Try broader keywords or fall back to arxiv-search / semantic-scholar-search."
        )

    papers: list[dict] = []
    for p in raw:
        pub = p.get("publication_info", {})
        papers.append({
            "title":          p.get("title"),
            "authors":        pub.get("authors") or pub.get("summary", "")[:120],
            "year":           pub.get("year") or pub.get("summary", "")[-4:],
            "venue":          pub.get("journal") or "",
            "cited_by":       p.get("inline_links", {}).get("cited_by", {})
                                .get("total"),
            "snippet":        (p.get("snippet") or "")[:400],
            "link":           p.get("link"),
            "source":         "SerpApi/google_scholar",
        })

    return {
        "command":   "research-papers",
        "as_of":     _today(),
        "product":   product,
        "keywords":  keywords,
        "since":     since,
        "count":     len(papers),
        "papers":    papers,
        "data_gaps": gaps,
    }


# ── 7. tech-stack-detect ──────────────────────────────────────────────────────

def cmd_tech_stack_detect(args: argparse.Namespace) -> dict:
    """
    Detect the live tech stack of `domain` via BuiltWith.
    Falls back gracefully when BUILTWITH_API_KEY is not set.
    """
    domain = args.domain
    gaps: list[str] = []

    key = _env("BUILTWITH_API_KEY", required=False)
    if not key:
        gaps.append(
            "BUILTWITH_API_KEY is not set. "
            "Tech-stack detection via BuiltWith is unavailable. "
            "The agent should fall back to web-search + github-search."
        )
        return {
            "command":    "tech-stack-detect",
            "as_of":      _today(),
            "domain":     domain,
            "layers":     [],
            "raw":        {},
            "data_gaps":  gaps,
        }

    print(f"[tech-stack-detect] BuiltWith lookup for {domain}…", file=sys.stderr)
    raw = _builtwith(domain)

    layers: list[dict] = []
    results = raw.get("Results", [{}])
    if not results:
        gaps.append(f"BuiltWith returned no results for domain '{domain}'.")
    else:
        paths = results[0].get("Result", {}).get("Paths", [])
        for path in paths:
            for tech in path.get("Technologies", []):
                layers.append({
                    "name":        tech.get("Name"),
                    "category":    tech.get("Categories", [""])[0] if tech.get("Categories") else "",
                    "description": tech.get("Description", "")[:200],
                    "link":        tech.get("Link"),
                    "first_seen":  tech.get("FirstDetected"),
                    "last_seen":   tech.get("LastDetected"),
                    "source":      "BuiltWith API",
                })

    return {
        "command":   "tech-stack-detect",
        "as_of":     _today(),
        "domain":    domain,
        "layers":    layers,
        "raw":       raw,
        "data_gaps": gaps,
    }


# ── 8. full-report ────────────────────────────────────────────────────────────

def cmd_full_report(args: argparse.Namespace) -> dict:
    """
    Orchestrate all commands in sequence; write consolidated report.json to
    args.output. Returns the consolidated dict (also printed to stdout if
    --output is not given).
    """
    company  = args.company
    product  = args.product
    output   = getattr(args, "output", None)

    # Build a workspace dir if output path given
    if output:
        workspace = Path(output).parent
        workspace.mkdir(parents=True, exist_ok=True)

    results: dict = {
        "command":    "full-report",
        "version":    VERSION,
        "as_of":      _today(),
        "company":    company,
        "product":    product,
        "sections":   {},
        "all_gaps":   [],
    }

    def _run(label: str, fn, sub_args: argparse.Namespace) -> None:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"[full-report] Running: {label}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        try:
            data = fn(sub_args)
            results["sections"][label] = data
            results["all_gaps"].extend(data.get("data_gaps", []))
        except SystemExit as exc:
            results["sections"][label] = {"error": str(exc), "data_gaps": [str(exc)]}
            results["all_gaps"].append(f"{label}: {exc}")

    # Build sub-namespace helper
    def _ns(**kwargs) -> argparse.Namespace:
        base = argparse.Namespace(
            company=company, product=product,
            domain=getattr(args, "domain", None),
            hq_country=getattr(args, "hq_country", None),
            ticker=getattr(args, "ticker", None),
            public=getattr(args, "public", False),
            private=getattr(args, "private", False),
            industry=getattr(args, "industry", None),
            keywords=getattr(args, "keywords", ""),
            known=getattr(args, "known", ""),
            since=getattr(args, "since", None),
            limit=getattr(args, "limit", 50),
            geo=getattr(args, "geo", ""),
        )
        for k, v in kwargs.items():
            setattr(base, k, v)
        return base

    _run("company-details",  cmd_company_details,  _ns())
    _run("turnover",         cmd_turnover,          _ns())
    _run("patents",          cmd_patents,           _ns())
    _run("trends",           cmd_trends,            _ns())
    _run("competitors",      cmd_competitors,       _ns())
    _run("research-papers",  cmd_research_papers,   _ns())

    # Generate all charts and record paths
    if output:
        charts = _charts_dir(output, company, product)
        _generate_all_charts(results, charts)
        results["charts_dir"] = str(charts)

    _out(results, output)
    return results


def _generate_all_charts(results: dict, charts: Path) -> None:
    """Walk the full-report result tree and generate every chart_data block."""
    for section_key, section in results.get("sections", {}).items():
        cd = section.get("chart_data", {})
        if not cd:
            continue
        for chart_key, spec in cd.items():
            if not spec:
                continue
            if "line_" in chart_key:
                out = charts / f"{chart_key}.png"
                path = _save_line_chart(
                    spec["labels"], spec["values"],
                    spec["title"], spec["xlabel"], spec["ylabel"], out,
                )
                section.setdefault("chart_paths", {})[chart_key] = path
            elif "pie_" in chart_key:
                out = charts / f"{chart_key}.png"
                path = _save_pie_chart(
                    spec["labels"], spec["values"], spec["title"], out
                )
                section.setdefault("chart_paths", {})[chart_key] = path
            elif "bar_" in chart_key:
                out = charts / f"{chart_key}.png"
                path = _save_bar_chart(
                    spec["labels"], spec["values"],
                    spec["title"], spec["xlabel"], spec["ylabel"], out,
                )
                section.setdefault("chart_paths", {})[chart_key] = path


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def _base_parser(prog: str, description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.add_argument("--output", "-o",
                   help="Write JSON result to this file path instead of stdout.")
    return p


def build_arg_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="rnd_report.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    root.add_argument("--version", action="version", version=VERSION)
    sub = root.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ── company-details ──
    p1 = sub.add_parser(
        "company-details",
        help="Crunchbase org profile + SerpApi knowledge panel for product",
    )
    p1.add_argument("--company",    required=True)
    p1.add_argument("--product",    required=True)
    p1.add_argument("--domain",     default=None,
                    help="Company website domain for Crunchbase disambiguation")
    p1.add_argument("--hq-country", default=None, dest="hq_country",
                    help="ISO-2 country code (e.g. US) for disambiguation")
    p1.add_argument("--output", "-o", default=None)

    # ── turnover ──
    p2 = sub.add_parser(
        "turnover",
        help="Revenue (public via FMP) or funding history (private via Crunchbase)",
    )
    p2.add_argument("--company",  required=True)
    p2.add_argument("--ticker",   default=None,
                    help="Stock ticker symbol for public company (e.g. AAPL)")
    g = p2.add_mutually_exclusive_group()
    g.add_argument("--public",  action="store_true",
                   help="Company is publicly traded")
    g.add_argument("--private", action="store_true",
                   help="Company is private")
    p2.add_argument("--output", "-o", default=None)

    # ── patents ──
    p3 = sub.add_parser(
        "patents",
        help="Google Patents via SerpApi, scoped to company assignee + product keywords",
    )
    p3.add_argument("--company",  required=True)
    p3.add_argument("--product",  required=True)
    p3.add_argument("--keywords", default="",
                    help="Additional patent search keywords (comma-separated)")
    p3.add_argument("--since",    default=None, metavar="YYYY",
                    help="Only patents filed/published from this year")
    p3.add_argument("--limit",    type=int, default=50,
                    help="Max patents to return (default 50)")
    p3.add_argument("--output", "-o", default=None)

    # ── trends ──
    p4 = sub.add_parser(
        "trends",
        help="Google Trends via SerpApi: interest-over-time + by-region",
    )
    p4.add_argument("--product",  required=True)
    p4.add_argument("--geo",      default="",
                    help="ISO-2 geo code (default: worldwide)")
    p4.add_argument("--since",    default=None, metavar="YYYY",
                    help="Start year for trend window (default: 5-year window)")
    p4.add_argument("--output", "-o", default=None)

    # ── competitors ──
    p5 = sub.add_parser(
        "competitors",
        help="Crunchbase similar companies + SerpApi web search, merged & deduped",
    )
    p5.add_argument("--company",  required=True)
    p5.add_argument("--product",  required=True)
    p5.add_argument("--industry", default=None,
                    help="Industry/sector hint (narrows competitor search)")
    p5.add_argument("--known",    default="",
                    help="Comma-separated list of known competitor names")
    p5.add_argument("--limit",    type=int, default=15,
                    help="Max competitors to return (default 15)")
    p5.add_argument("--output", "-o", default=None)

    # ── research-papers ──
    p6 = sub.add_parser(
        "research-papers",
        help="Google Scholar via SerpApi (supplement with web_research.py academic tools)",
    )
    p6.add_argument("--product",  required=True)
    p6.add_argument("--keywords", default="",
                    help="Additional search terms")
    p6.add_argument("--since",    default=None, metavar="YYYY")
    p6.add_argument("--limit",    type=int, default=20)
    p6.add_argument("--output", "-o", default=None)

    # ── tech-stack-detect ──
    p7 = sub.add_parser(
        "tech-stack-detect",
        help="BuiltWith tech-stack lookup for the product's domain",
    )
    p7.add_argument("--domain",   required=True,
                    help="Product website domain (e.g. notion.so)")
    p7.add_argument("--output", "-o", default=None)

    # ── full-report ──
    p8 = sub.add_parser(
        "full-report",
        help="Orchestrate all commands; write consolidated report.json",
    )
    p8.add_argument("--company",    required=True)
    p8.add_argument("--product",    required=True)
    p8.add_argument("--domain",     default=None)
    p8.add_argument("--hq-country", default=None, dest="hq_country")
    p8.add_argument("--ticker",     default=None)
    g2 = p8.add_mutually_exclusive_group()
    g2.add_argument("--public",  action="store_true")
    g2.add_argument("--private", action="store_true")
    p8.add_argument("--industry",  default=None)
    p8.add_argument("--keywords",  default="")
    p8.add_argument("--known",     default="")
    p8.add_argument("--since",     default=None, metavar="YYYY")
    p8.add_argument("--geo",       default="")
    p8.add_argument("--limit",     type=int, default=50)
    p8.add_argument("--web-research", action="store_true", dest="web_research",
                    help="Also run the free web-research layer "
                         "(passed as a flag to the agent — see web_research.py)")
    p8.add_argument("--output", "-o",
                    required=True,
                    help="Path for report.json inside the workspace reports dir "
                         "(e.g. ~/.openclaw/workspace/reports/acme_widget_2026-01-01/report.json)")

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

    # For individual commands (not full-report, which writes itself)
    if args.command != "full-report":
        _out(result, getattr(args, "output", None))


if __name__ == "__main__":
    main()

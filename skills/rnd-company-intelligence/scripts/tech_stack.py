#!/usr/bin/env python3
"""
tech_stack.py — Detected technology-stack lookup for the rnd-tech-stack skill.

Commands:
    detect          --domain example.com
                    Looks up the domain's current stack via the BuiltWith API.
                    Requires BUILTWITH_API_KEY. Exits with a clear error (not a
                    crash) if the key is missing so the calling agent can switch
                    to the fallback commands below.

    web-fallback    --query "..."  [--limit N] [--engine ddg|bing|brave|mojeek|google-cse|all]
                    Fans out across whichever free search engines are configured
                    and returns merged, deduped results for manual/LLM synthesis
                    (e.g. engineering-blog posts, "how it's built" writeups, job
                    postings that mention the stack). Always includes DuckDuckGo
                    (no key needed). Other engines are silently skipped if their
                    API key isn't set.

    github-fallback --query "..." [--type repositories|code|users] [--limit N]
                    Searches GitHub's public search API for repos/code/users
                    related to the query. Works without a token at a low rate
                    limit; set GITHUB_TOKEN to raise it.

Output: every command prints a single JSON object to stdout on success, and a
JSON object with an "error" key (plus enough detail to act on) on failure.
Network/API failures never raise uncaught — they're reported as structured
errors so the calling agent can decide whether to retry, fall back, or skip.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse

import requests

DEFAULT_TIMEOUT = 15
USER_AGENT = "rnd-tech-stack-skill/1.6.0 (+https://github.com/openclaw-user)"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def emit(payload: dict, exit_code: int = 0) -> None:
    """Print a single JSON object to stdout and exit."""
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    sys.exit(exit_code)


def emit_error(message: str, *, status: int = None, hint: str = None, exit_code: int = 1) -> None:
    payload = {"error": message}
    if status is not None:
        payload["status"] = status
    if hint is not None:
        payload["hint"] = hint
    emit(payload, exit_code=exit_code)


def normalize_domain(raw: str) -> str:
    """Strip scheme/path/www so BuiltWith and friends get a bare domain."""
    raw = raw.strip()
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urllib.parse.urlparse(raw)
    host = parsed.netloc or parsed.path
    host = host.split("/")[0]
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


def http_get(url: str, *, params: dict = None, headers: dict = None, timeout: int = DEFAULT_TIMEOUT):
    """Thin wrapper so every engine reports failures the same structured way."""
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    try:
        resp = requests.get(url, params=params, headers=req_headers, timeout=timeout)
        return resp, None
    except requests.exceptions.Timeout:
        return None, {"error": "request timed out", "url": url}
    except requests.exceptions.RequestException as exc:
        return None, {"error": str(exc), "url": url}


# --------------------------------------------------------------------------- #
# detect — BuiltWith
# --------------------------------------------------------------------------- #

def cmd_detect(args: argparse.Namespace) -> None:
    api_key = os.environ.get("BUILTWITH_API_KEY")
    if not api_key:
        emit_error(
            "BUILTWITH_API_KEY is not set.",
            hint="Run web-fallback and github-fallback instead, and label results "
                 "as inferred from public sources rather than BuiltWith.",
            exit_code=2,
        )

    domain = normalize_domain(args.domain)
    resp, transport_err = http_get(
        "https://api.builtwith.com/v21/api.json",
        params={"KEY": api_key, "LOOKUP": domain},
    )

    if transport_err:
        emit_error(f"Network error calling BuiltWith: {transport_err['error']}", exit_code=3)

    if resp.status_code in (401, 403):
        emit_error(
            "BuiltWith rejected the API key.",
            status=resp.status_code,
            hint="Tell the user BUILTWITH_API_KEY needs to be regenerated, then "
                 "fall back to web-fallback / github-fallback.",
            exit_code=4,
        )
    if resp.status_code == 404:
        emit_error(
            f"No BuiltWith data found for domain '{domain}'.",
            status=404,
            hint="Re-confirm the domain, or fall back to web-fallback / github-fallback.",
            exit_code=5,
        )
    if resp.status_code == 429:
        emit_error(
            "BuiltWith rate-limited this request.",
            status=429,
            hint="Wait for the reset window if one was reported, otherwise fall back.",
            exit_code=6,
        )
    if resp.status_code >= 500:
        emit_error(
            "BuiltWith is having an upstream outage.",
            status=resp.status_code,
            hint="Fall back to web-fallback / github-fallback rather than blocking.",
            exit_code=7,
        )
    if resp.status_code != 200:
        emit_error(
            f"Unexpected BuiltWith response ({resp.status_code}).",
            status=resp.status_code,
            exit_code=8,
        )

    try:
        data = resp.json()
    except ValueError:
        emit_error("BuiltWith returned a non-JSON response.", exit_code=9)

    results = data.get("Results", [])
    if not results:
        emit_error(
            f"BuiltWith returned no results for '{domain}'.",
            hint="Domain may be too new or too small for BuiltWith's index. Fall back.",
            exit_code=5,
        )

    paths = results[0].get("Result", {}).get("Paths", [])
    stack = {}
    for path in paths:
        for tech in path.get("Technologies", []):
            category = tech.get("Tag") or tech.get("Categories", [{}])[0].get("Name", "Other")
            stack.setdefault(category, [])
            entry = {
                "name": tech.get("Name"),
                "description": tech.get("Description"),
                "first_detected": tech.get("FirstDetected"),
                "last_detected": tech.get("LastDetected"),
            }
            if entry not in stack[category]:
                stack[category].append(entry)

    emit({
        "domain": domain,
        "source": "BuiltWith",
        "retrieved_at": int(time.time()),
        "stack_by_category": stack,
    })


# --------------------------------------------------------------------------- #
# web-fallback — free multi-engine search
# --------------------------------------------------------------------------- #

def search_ddg(query: str, limit: int) -> tuple:
    """DuckDuckGo via the ddgs library — always available, no key required."""
    try:
        from ddgs import DDGS
    except ImportError:
        return [], {"engine": "ddg", "error": "ddgs library not installed"}

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=limit))
        results = [
            {"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body"), "engine": "ddg"}
            for r in raw
        ]
        return results, None
    except Exception as exc:
        return [], {"engine": "ddg", "error": str(exc)}


def search_bing(query: str, limit: int) -> tuple:
    key = os.environ.get("BING_SEARCH_API_KEY")
    if not key:
        return [], None  # silently skipped, not an error
    resp, transport_err = http_get(
        "https://api.bing.microsoft.com/v7.0/search",
        params={"q": query, "count": limit},
        headers={"Ocp-Apim-Subscription-Key": key},
    )
    if transport_err:
        return [], {"engine": "bing", "error": transport_err["error"]}
    if resp.status_code != 200:
        return [], {"engine": "bing", "error": f"HTTP {resp.status_code}"}
    data = resp.json()
    items = data.get("webPages", {}).get("value", [])
    results = [
        {"title": i.get("name"), "url": i.get("url"), "snippet": i.get("snippet"), "engine": "bing"}
        for i in items
    ]
    return results, None


def search_brave(query: str, limit: int) -> tuple:
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        return [], None
    resp, transport_err = http_get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
    )
    if transport_err:
        return [], {"engine": "brave", "error": transport_err["error"]}
    if resp.status_code != 200:
        return [], {"engine": "brave", "error": f"HTTP {resp.status_code}"}
    data = resp.json()
    items = data.get("web", {}).get("results", [])
    results = [
        {"title": i.get("title"), "url": i.get("url"), "snippet": i.get("description"), "engine": "brave"}
        for i in items
    ]
    return results, None


def search_mojeek(query: str, limit: int) -> tuple:
    key = os.environ.get("MOJEEK_API_KEY")
    if not key:
        return [], None
    resp, transport_err = http_get(
        "https://www.mojeek.com/search",
        params={"q": query, "fmt": "json", "t": limit, "api_key": key},
    )
    if transport_err:
        return [], {"engine": "mojeek", "error": transport_err["error"]}
    if resp.status_code != 200:
        return [], {"engine": "mojeek", "error": f"HTTP {resp.status_code}"}
    data = resp.json()
    items = data.get("response", {}).get("results", [])
    results = [
        {"title": i.get("title"), "url": i.get("url"), "snippet": i.get("desc"), "engine": "mojeek"}
        for i in items
    ]
    return results, None


def search_google_cse(query: str, limit: int) -> tuple:
    key = os.environ.get("GOOGLE_CSE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")
    if not key or not cse_id:
        return [], None
    resp, transport_err = http_get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": key, "cx": cse_id, "q": query, "num": min(limit, 10)},
    )
    if transport_err:
        return [], {"engine": "google-cse", "error": transport_err["error"]}
    if resp.status_code != 200:
        return [], {"engine": "google-cse", "error": f"HTTP {resp.status_code}"}
    data = resp.json()
    items = data.get("items", [])
    results = [
        {"title": i.get("title"), "url": i.get("link"), "snippet": i.get("snippet"), "engine": "google-cse"}
        for i in items
    ]
    return results, None


ENGINES = {
    "ddg": search_ddg,
    "bing": search_bing,
    "brave": search_brave,
    "mojeek": search_mojeek,
    "google-cse": search_google_cse,
}


def cmd_web_fallback(args: argparse.Namespace) -> None:
    engine_choice = args.engine or "all"
    engines_to_run = list(ENGINES.keys()) if engine_choice == "all" else [engine_choice]

    if "ddg" not in engines_to_run:
        engines_to_run.append("ddg")  # baseline is always included for "all"-style robustness

    all_results = []
    seen_urls = set()
    skipped = []
    errors = []

    for name in engines_to_run:
        fn = ENGINES.get(name)
        if fn is None:
            continue
        results, err = fn(args.query, args.limit)
        if err:
            errors.append(err)
            continue
        if not results and name != "ddg":
            skipped.append(name)  # likely no key configured
            continue
        for r in results:
            url = r.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    if not all_results and not errors:
        emit_error(
            f"No results found for '{args.query}' across configured engines.",
            hint="Retry once with a reworded/broader query before giving up.",
            exit_code=10,
        )

    emit({
        "query": args.query,
        "engines_attempted": engines_to_run,
        "engines_skipped_no_key": skipped,
        "engine_errors": errors,
        "result_count": len(all_results),
        "results": all_results[: args.limit * len(engines_to_run) if engine_choice == "all" else args.limit],
    })


# --------------------------------------------------------------------------- #
# github-fallback
# --------------------------------------------------------------------------- #

def cmd_github_fallback(args: argparse.Namespace) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    search_type = args.type or "repositories"
    if search_type not in ("repositories", "code", "users"):
        emit_error(f"Invalid --type '{search_type}'. Must be repositories, code, or users.", exit_code=2)

    resp, transport_err = http_get(
        f"https://api.github.com/search/{search_type}",
        params={"q": args.query, "per_page": min(args.limit, 50)},
        headers=headers,
    )
    if transport_err:
        emit_error(f"Network error calling GitHub: {transport_err['error']}", exit_code=3)

    if resp.status_code == 403:
        emit_error(
            "GitHub rate-limited this request.",
            status=403,
            hint="Unauthenticated requests are limited to 10/min; set GITHUB_TOKEN to raise it. "
                 "Wait a minute and retry, or continue with other sources.",
            exit_code=6,
        )
    if resp.status_code != 200:
        emit_error(f"Unexpected GitHub response ({resp.status_code}).", status=resp.status_code, exit_code=8)

    data = resp.json()
    items = data.get("items", [])

    if search_type == "repositories":
        results = [
            {
                "name": i.get("full_name"),
                "url": i.get("html_url"),
                "description": i.get("description"),
                "stars": i.get("stargazers_count"),
                "forks": i.get("forks_count"),
                "language": i.get("language"),
                "last_pushed": i.get("pushed_at"),
            }
            for i in items
        ]
    elif search_type == "code":
        results = [
            {
                "repo": i.get("repository", {}).get("full_name"),
                "path": i.get("path"),
                "url": i.get("html_url"),
            }
            for i in items
        ]
    else:  # users
        results = [
            {"login": i.get("login"), "url": i.get("html_url"), "type": i.get("type")}
            for i in items
        ]

    emit({
        "query": args.query,
        "type": search_type,
        "authenticated": bool(token),
        "total_count": data.get("total_count", len(results)),
        "results": results[: args.limit],
    })


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tech_stack.py",
        description="Detected technology-stack lookup (BuiltWith + free fallbacks).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect", help="Look up a domain's current stack via BuiltWith.")
    p_detect.add_argument("--domain", required=True, help="e.g. example.com")
    p_detect.set_defaults(func=cmd_detect)

    p_web = sub.add_parser("web-fallback", help="Free multi-engine web search fallback.")
    p_web.add_argument("--query", required=True)
    p_web.add_argument("--limit", type=int, default=5)
    p_web.add_argument(
        "--engine",
        choices=["ddg", "bing", "brave", "mojeek", "google-cse", "all"],
        default="all",
    )
    p_web.set_defaults(func=cmd_web_fallback)

    p_gh = sub.add_parser("github-fallback", help="GitHub search fallback for open-source signal.")
    p_gh.add_argument("--query", required=True)
    p_gh.add_argument("--type", choices=["repositories", "code", "users"], default="repositories")
    p_gh.add_argument("--limit", type=int, default=5)
    p_gh.set_defaults(func=cmd_github_fallback)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # last-resort guard so failures are always structured JSON
        emit_error(f"Unhandled error: {exc}", exit_code=99)


if __name__ == "__main__":
    main()

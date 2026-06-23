---
name: rnd-company-research
description: Generate an R&D research report for a given Company + Product, covering company/product overview, turnover (financials), patents, trend analysis, competitor analysis, related research papers, and a synthesized SWOT. The full answer is always rendered directly in chat, including charts. A downloadable file (output.md or output.pdf, saved to the user's Downloads folder) is generated only when the user explicitly asks to download/save/export — never automatically. Research draws on paid APIs (Crunchbase, SerpApi, FMP) plus a free multi-engine layer (DuckDuckGo, Bing, Brave Search, Mojeek, Google Custom Search, Wikipedia+Wikidata, arXiv, Crossref, Semantic Scholar, GitHub Search) used as fallback and for qualitative/academic/open-source depth. Trigger this whenever the user gives a company name and a product name and asks for research, due diligence, market analysis, competitive analysis, patent search, SWOT, financial/turnover lookup, trend report, web research, or a "company + product report" — even if they only name the company and product without using the word "report". For technology-stack questions ("what stack does X use", "what should I use to build something like X"), use the companion rnd-tech-stack skill instead.
license: Apache-2.0
metadata:
  author: openclaw-user
  version: "1.6.0"
  openclaw:
    requires:
      env:
        - SERPAPI_KEY
        - CRUNCHBASE_API_KEY
      bins:
        - python3
      python:
        - requests>=2.31.0
        - matplotlib>=3.7.0
        - ddgs>=9.0.0
        - beautifulsoup4>=4.12.0
        - reportlab>=4.0.0
      skills:
        - pdf
      primaryEnv: SERPAPI_KEY
    optionalEnv:
      - BING_SEARCH_API_KEY
      - BRAVE_SEARCH_API_KEY
      - MOJEEK_API_KEY
      - GOOGLE_CSE_API_KEY
      - GOOGLE_CSE_ID
      - GITHUB_TOKEN
      - SEMANTIC_SCHOLAR_API_KEY
      - FMP_API_KEY
---

# R&D Company & Product Research

This skill turns the agent into an R&D / market-intelligence analyst. Given just a **company name** and a **product name**, it pulls structured data from a handful of paid APIs and a free multi-engine web/academic research layer, and synthesizes it into a report.

**Two simple rules govern output:**
1. **Always render the full answer in chat** — every section, table, chart, and the SWOT grid. This happens every time, with no opt-in needed.
2. **Only produce a downloadable file when the user explicitly asks** ("download this," "save it," "export as PDF") — and when they do, it's saved as `output.md` or `output.pdf` directly to the user's **Downloads folder**, not buried in a project or workspace directory.

This skill does **not** cover technology-stack detection or recommendation — that's a separate, companion skill (`rnd-tech-stack`). If the user asks a stack-related question after seeing a research report, point them to that skill (or hand off directly if both are available in your environment).

## Read the scripts first

This document describes intended behavior, but the actual flags, defaults, and output shape live in the scripts themselves, which can drift from what's written here. **Before running any command for the first time in a session — and any time a call fails in a way this document doesn't explain — view the full contents of:**

- `scripts/rnd_report.py` — wraps Crunchbase, SerpApi, FMP
- `scripts/web_research.py` — the free multi-engine search/scrape/academic layer
- `scripts/export_report.py` — writes `output.md` / `output.pdf` to the Downloads folder

Don't rely on `--help` output alone or on this document's examples once the underlying code has changed — read the actual source. If a command in this document doesn't match what a script actually accepts, trust the script.

## When to use this skill

Trigger this skill whenever the user:

- Gives a company name + product name and asks for research, a report, "intel", due diligence, or an overview
- Asks for any single piece that this skill produces on its own — turnover/revenue, patents, trend analysis, competitor analysis, related research papers, or a SWOT — for a named company/product
- Asks to download, save, or export a report this skill already produced

If the user asks about technology stack (detected or recommended), that's the companion `rnd-tech-stack` skill, not this one.

If the user only gives a company name with no product, or only a product with no company, ask for the missing piece before calling any API — every downstream command takes both.

## Inputs

### Required

| Input | Notes |
|---|---|
| Company name | Used to resolve a Crunchbase organization and to scope patent/competitor/financial lookups |
| Product name | Used to scope patents, trend analysis, and research-paper search; without it, results skew to the whole company instead of the specific product |

If either is missing or ambiguous (e.g., "Apple" could be the company or several unrelated entities), ask a single clarifying question rather than guessing.

### Optional — ask for these, or use them if the user already mentioned them

None of these block the report — the scripts will resolve the same things themselves via search — but each one removes a disambiguation step and sharpens a specific section. If the user's request already contains any of them, pass them straight through instead of re-deriving them. Don't interrogate the user for all of them up front; one good clarifying question covering the 2–3 most relevant to the request is enough, and it's fine to proceed with sensible defaults if the user just wants the report now.

| Input | Sharpens | Why it helps |
|---|---|---|
| Company website / domain | Crunchbase match | Skips name-collision guesswork |
| Stock ticker | Turnover | Goes straight to Financial Modeling Prep instead of guessing public vs. private |
| Public or private | Turnover routing | Tells you immediately whether to expect an income statement or a funding history |
| Industry / sector | Competitor analysis, SWOT | Narrows the "similar companies" search so it doesn't return unrelated firms that happen to share a category tag |
| HQ country / region | Crunchbase disambiguation, trend geo | Resolves same-name companies in different countries and sets a sensible default `--geo` for trends |
| Known competitors (a few names) | Competitor analysis | Seeds the merge/dedupe step so the section starts from something concrete instead of a cold search |
| Specific technology / keyword terms | Patents, research papers | The product name alone is sometimes too broad ("Cybertruck") or too narrow ("ChatGPT" vs. the underlying model); a keyword like "structural battery pack" or "transformer architecture" narrows precisely |
| Time window (e.g., last 3/5/10 years) | Patents, trends, research papers | Overrides the script's default lookback when the user cares about a specific period |
| Target customer segment (B2B / B2C / enterprise / consumer) | SWOT | Changes the scale and compliance assumptions baked into competitive framing |

If several of these are already implied by the conversation (e.g., the user is clearly talking about a public company, or already named two competitors), use them without asking again.

## Research sources

### Paid APIs (structured, repeatable — the primary sources)

| Capability | Service | Env var | Required? |
|---|---|---|---|
| Company profile, funding history, similar companies | Crunchbase API | `CRUNCHBASE_API_KEY` | yes |
| Web/news search, Google Patents, Google Trends, Google Scholar | SerpApi | `SERPAPI_KEY` | yes |
| Revenue / income statement for public companies | Financial Modeling Prep | `FMP_API_KEY` | yes, for the turnover section's public-company path |

### Free multi-engine web & academic layer (`scripts/web_research.py`)

No single free engine is reliable enough alone, so this layer fans out across several, all wrapped by one script. Most need no key at all; a few unlock higher quality or rate limits if configured, but none are required for the skill to function.

| Engine | Use for | Env var | Key required? |
|---|---|---|---|
| DuckDuckGo | General web search — the always-available baseline | none | no |
| Bing Web Search | General web search — extra coverage/fallback | `BING_SEARCH_API_KEY` | optional |
| Brave Search | General web search — extra coverage/fallback, independent index | `BRAVE_SEARCH_API_KEY` | optional |
| Mojeek | General web search — extra coverage/fallback, independent index | `MOJEEK_API_KEY` | optional |
| Google Custom Search | General web search via a configured CSE | `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_ID` | optional |
| Wikipedia + Wikidata | Encyclopedic company/product background, structured facts (founding date, HQ, industry, parent org) | none | no |
| arXiv | Preprint search — supplements Google Scholar, especially for CS/AI/physics-heavy products | none | no |
| Crossref | DOI/citation metadata for published academic work | none | no |
| Semantic Scholar | Academic paper search with citation-graph context | `SEMANTIC_SCHOLAR_API_KEY` | optional (raises rate limit only) |
| GitHub Search | Repos/code related to the company or product — open-source presence, stars, recent activity, contributor count | `GITHUB_TOKEN` | optional (raises rate limit only) |

**When to use which:**

1. **Fallback for a failed paid-API call.** Any time SerpApi or Crunchbase returns 401/403/429/5xx, or a 404/empty result with no close match, fall back to the general web-search engines (`web-search`, trying every configured engine plus DuckDuckGo, merged and deduped) and `scrape-page` on the best result. Label it "(via free web search, not SerpApi)" wherever it substitutes for a paid section.
2. **Company/product factual background.** Run `wiki-lookup` early (step 1) to cross-check or fill gaps in the Crunchbase profile — founding date, HQ, parent company, industry — especially useful when Crunchbase's entry is thin.
3. **Research-papers section.** Supplement `research-papers` (Google Scholar) with `arxiv-search`, `crossref-search`, and `semantic-scholar-search` — between them they cover preprints, DOI/citation metadata, and citation-graph context that Scholar alone misses, particularly for AI/ML/hardware products.
4. **Open-source / developer signal.** Run `github-search` when the product is developer-facing or when open-source presence is a relevant competitive signal (stars, forks, recent commit activity, contributor count) — feed it into Competitor Analysis or the qualitative section, whichever fits.
5. **Qualitative deepening.** Even when every paid API succeeds, a `web-search` pass across the general engines adds recent press, hands-on reviews, and community/forum sentiment that structured APIs can't surface. Use this to populate the optional "Additional Web Research" section — don't use it to second-guess numbers the paid APIs already returned with confidence.

Always finish a `web-search` pass with `scrape-page` on the 1–3 best results before writing a claim into the report — snippets are too short to synthesize from, and scraping lets you paraphrase the real content instead of leaning on a truncated snippet.

## Report Output (working files)

Intermediate/working files — `report.json`, chart PNGs, anything the scripts produce while building the chat answer — are never written to `/tmp`. They go in:

```
~/.openclaw/workspace/reports/{company}_{product}_{YYYY-MM-DD}/
├── report.json
└── charts/
    ├── turnover_bar.png
    ├── trend_line.png
    └── competitors_pie.png
```

Create the directory first if it doesn't exist (`mkdir -p`). This is **scratch space**, not the user-facing deliverable — `export_report.py` reads from here when the user asks to download, but the rendered chat answer is the actual report, and the workspace folder should never be what you point the user to when they ask "where's my file."

## How to use this skill

```bash
python3 {baseDir}/scripts/rnd_report.py <command> [args...]
python3 {baseDir}/scripts/web_research.py <command> [args...]
python3 {baseDir}/scripts/export_report.py <command> [args...]
```

Get each script's full command list with `--help`, but see "Read the scripts first" above — `--help` is a starting point, not a substitute for reading the source.

### Core workflow

1. **Read the three scripts** if you haven't already this session (see "Read the scripts first").
2. **Confirm inputs** — company name and product name, plus any optional enrichment inputs that are already implied or worth one quick clarifying question.
3. **Run the data-gathering commands** — all six `rnd_report.py` commands for a full report, or just the one/two that answer a narrower request. Run `wiki-lookup` early for background cross-checking.
4. **Run the free research layer where it's warranted** — automatic fallback on any failed/empty paid-API call; `arxiv-search`/`crossref-search`/`semantic-scholar-search` to round out the research-papers section; `github-search` when open-source signal is relevant; and ask the user once whether they also want the optional qualitative "Additional Web Research" section before running a `web-search` pass purely for that purpose.
5. **Synthesize the SWOT yourself** (full reports only) — your own analysis of the other sections, not a separate API call. Ground every bullet in something the report actually surfaced; free-layer findings (recurring complaints, a recent negative news cycle, thin GitHub activity) are fair game too, cited as web-sourced.
6. **Render the full answer directly in chat** — every section, every chart, the SWOT grid. This always happens; it's the primary deliverable, not a preview.
7. **Do not generate a file.** Stop here unless the user explicitly asks to download/save/export — see "Output & delivery" below.
8. **Offer the follow-up menu** (download / drill into a section / hand off to tech-stack skill / stop).

### Command reference — `rnd_report.py`

**Company & product detail**
- `company-details --company "..." --product "..." [--domain example.com] [--hq-country US]` — Crunchbase org profile (description, founding date, HQ, employee count, leadership) plus a SerpApi knowledge-panel pass for the specific product. `--domain` and `--hq-country` resolve name collisions instead of guessing from search results.

**Turnover (financials)**
- `turnover --company "..." [--ticker SYM] [--public | --private]` — if the company is public (or `--ticker` is given), pulls revenue/income statement from Financial Modeling Prep; otherwise falls back to Crunchbase total funding raised and latest valuation, clearly labeled as funding data, not revenue. Pass `--public`/`--private` if the user already told you.

**Patents**
- `patents --company "..." --product "..." [--keywords "term1,term2"] [--since YYYY] [--limit N]` — SerpApi's Google Patents engine, scoped to assignee = company and keyword = product.

**Trend analysis**
- `trends --product "..." [--geo US] [--since YYYY]` — SerpApi's Google Trends engine; interest-over-time and interest-by-region. Defaults to a 5-year window and worldwide geo.

**Competitor analysis**
- `competitors --company "..." --product "..." [--industry "..."] [--known "Name A,Name B"] [--limit N]` — Crunchbase "similar companies" plus a SerpApi web search for alternatives/competitors; dedupes and merges both lists.

**Research papers**
- `research-papers --product "..." [--keywords "term1,term2"] [--since YYYY] [--limit N]` — SerpApi's Google Scholar engine. Supplement with `web_research.py`'s `arxiv-search`/`crossref-search`/`semantic-scholar-search` per "When to use which" above.

**Orchestration**
- `full-report --company "..." --product "..." [--domain ...] [--ticker ...] [--industry ...] [--keywords ...] [--known ...] [--web-research] --output ~/.openclaw/workspace/reports/{company}_{product}_{date}/report.json` — runs company-details, turnover, patents, trends, competitors, and research-papers in sequence. Always point `--output` inside the workspace reports directory, never `/tmp`. Pass `--web-research` to also run the free-layer qualitative pass.

### Command reference — `web_research.py`

**General web search (engine fallback + qualitative pass)**
- `web-search --query "..." [--engine ddg|bing|brave|mojeek|google-cse|all] [--limit N] [--since YYYY] [--region us-en]` — defaults to `--engine ddg` (always available, no key). Use `--engine all` to fan out across every configured engine in parallel and merge/dedupe by URL — this is what "fallback" and "qualitative pass" both mean in practice; engines without a configured key are silently skipped, not treated as errors.
- `scrape-page --url "..." [--max-chars N]` — fetches and extracts readable page text; respects `robots.txt`.

**Reference / background**
- `wiki-lookup --query "..." [--lang en]` — Wikipedia summary + infobox facts, plus the matching Wikidata entity's structured claims (founding date, industry, HQ, parent organization, etc.).

**Academic / research**
- `arxiv-search --query "..." [--limit N] [--since YYYY]` — arXiv preprint search.
- `crossref-search --query "..." [--limit N]` — DOI/citation metadata lookup by title/keywords.
- `semantic-scholar-search --query "..." [--limit N] [--since YYYY]` — paper search with citation counts and influential-citation context.

**Open-source / developer signal**
- `github-search --query "..." [--type repositories|code|users] [--limit N]` — repo/code/user search; for repos, returns stars, forks, last-push date, and primary language. (Also usable here for competitor open-source signal; the companion `rnd-tech-stack` skill uses the same command for stack-detection fallback.)

### Command reference — `export_report.py`

- `export --format md|pdf|both --title "..." --markdown-file path/to/rendered.md [--charts-dir path/to/charts] [--out-dir ~/Downloads]` — writes `output.md` and/or `output.pdf` built from the exact markdown (and embedded chart images) you rendered in chat. Defaults `--out-dir` to the platform Downloads folder; only override it if the user asked for a specific location or Downloads isn't writable (see "Output & delivery" below).

## Output format

### Main report — always use this structure

```markdown
# R&D Research Report: {Product} by {Company}

## 1. Company & Product Overview
## 2. Turnover / Financials
## 3. Patents
## 4. Trend Analysis
## 5. Competitor Analysis
## 6. Related Research
## 7. SWOT Analysis
## 8. Additional Web Research (optional)
```

- Section 8 only appears if the free-layer engines were run for qualitative-research purposes (not just as a silent fallback for a failed paid-API call, which gets folded into its own numbered section with a "(via free web search)" label instead). Group bullets by theme (recent news, user sentiment, open-source activity, pricing/positioning), each ending in a markdown link to its source. Skip the section entirely if nothing material turned up.
- For a narrower request (e.g., just patents + trends), use only the matching numbered heading(s) — don't fabricate or pad the others.
- For sections 2–6, render results as compact markdown tables. Don't paste raw JSON.
- For the three market-analysis sections — Turnover (2), Trend Analysis (4), Competitor Analysis (5) — also render one or more charts (`matplotlib`) right after that section's table, per "Charts & visualizations" below.
- Section 7 (SWOT): a 2x2 markdown table — Strengths / Weaknesses on top, Opportunities / Threats on bottom, 2–4 bullets each.
- Cite a claim's source inline only when it materially matters; don't footnote every sentence.
- Paraphrase abstracts/summaries in your own words; never reproduce more than a short, attributed snippet.

#### Charts & visualizations

**Pie vs. bar — decision rule:**
- **Bar chart** for comparing magnitudes across categories, or anything that doesn't sum to a meaningful whole. Default when in doubt.
- **Pie chart** only for genuine share-of-a-whole data with **at most 6 segments** — group smaller categories into "Other," or fall back to a bar chart if that's not sensible.
- **Never** a pie chart for time series — those stay line/bar.

**Generation steps:**
1. Save each chart as a PNG into that run's `charts/` subfolder under `~/.openclaw/workspace/reports/{company}_{product}_{date}/` — never `/tmp`. Generate every chart before any download is requested, since `export_report.py` reads from this folder.
2. Embed each PNG under its section's table: `![Revenue by fiscal year](charts/turnover_bar.png)` plus a one-line italic caption.
3. **Quality, every chart:** `figsize=(6,4)`, `dpi=150`+, white `facecolor` (never transparent), title, labeled axes or percentage labels, legend when more than one series, `bbox_inches="tight"`, `plt.close()` after saving. Reuse one small color palette across the whole report.
4. **Text fallback:** if the runtime can't render images in chat, say so once and switch to a one-line trend summary for chat — but still generate the real chart PNG, since it's needed if/when the user asks to download.

| Section | Primary chart | Secondary chart (when data supports it) |
|---|---|---|
| 2. Turnover / Financials | Bar: revenue by year (public) or funding by round (private) | Pie: share of total funding by round type — 2+ rounds only |
| 4. Trend Analysis | Line: interest-over-time (always — never pie) | Pie: search interest by region, 2+ regions, top 5 + "Other" |
| 5. Competitor Analysis | Bar: company + competitors on one metric | Pie: each entity's share of that metric's total, only if it sums meaningfully |

Skip a chart (and say so in one line) if its underlying data is a single point or empty — don't fake one.

### Output & delivery — show in chat always, download only on request

1. **Chat rendering is unconditional.** Every section, table, chart, and SWOT grid goes into the chat response every time. The user never has to ask to see the report — it's already there.
2. **File generation is opt-in only.** Do not run `export_report.py` and do not mention downloading proactively until the user actually asks — phrases like "download this," "save it," "give me the file," "export as PDF/markdown," "can I get a copy." The follow-up menu (below) is the one place it's offered as a choice; outside that, don't bring it up unprompted.
3. **When asked, pick the format:**
   - No format specified ("download this," "save it") → **PDF** (`output.pdf`).
   - "Markdown," ".md," "raw text," "the text version" → **`output.md`**.
   - "Both" / "either" → generate both.
4. **Run `export_report.py`** (read it first) with the exact markdown and chart paths from the answer just rendered — the file should be a faithful copy of the chat output, not a trimmed summary.
5. **Save location is the Downloads folder, not the workspace:**
   - macOS / Linux: `~/Downloads/output.md` / `~/Downloads/output.pdf`
   - Windows: `%USERPROFILE%\Downloads\output.md` / `%USERPROFILE%\Downloads\output.pdf`
   - If Downloads doesn't exist or isn't writable in the current environment, say so plainly and fall back to `~/.openclaw/workspace/reports/{company}_{product}_{date}/`, telling the user exactly where the file landed instead.
6. **Don't silently overwrite.** If `output.md`/`output.pdf` already exists in Downloads from an earlier report this session, ask once whether to overwrite or save under a more specific name (e.g. `{company}_{product}_output.pdf`).
7. **Apply "Document styling" below** (plain black/white/gray) for the PDF — `export_report.py` defaults to this palette already, but override if you've customized the rendered markdown's styling.
8. **If export fails**, say so plainly and don't block the rest of the conversation on it — the chat answer the user already has stands on its own regardless.

### Document styling (PDF / docx) — keep it plain

Black text, white background, gray/black structural lines only — this is a research report, not a branded deck.

- **Table borders:** thin black or gray (`#000000` / `#808080`), never colored.
- **Table header row:** bold black text on plain white or very light gray (`#F2F2F2`) — no colored fills.
- **Headings:** normal heading styles, text stays black.
- **Rules/dividers:** plain thin gray line if needed; no colored callout boxes.
- **Charts** keep their small data-distinguishing palette from "Charts & visualizations" — everything outside the chart images stays black/white/gray.

If the user asks for a `.docx` instead of PDF, apply this same palette when handing off to the `docx` skill.

### After the report — present this menu

1. **Download** — markdown (`output.md`) or PDF (`output.pdf`), saved to your Downloads folder.
2. **Drill into a section** — re-run that section's command with a larger `--limit` or narrower scope and expand it inline; redraw its chart if it had one.
3. **Tech stack** — point the user to (or hand off to) the companion `rnd-tech-stack` skill for detected + recommended stack.
4. **Stop here** — nothing further needed.

## Error handling

| Status | Meaning | What to do |
|---|---|---|
| 401 / 403 | Bad or expired key on Crunchbase or SerpApi | Tell the user exactly which env var to regenerate |
| 404 | Company not found on Crunchbase | Re-confirm the company/product name; offer close matches if returned |
| 422 / 400 | Malformed query (e.g., empty product string to Google Trends) | Re-check both company and product were actually passed before retrying |
| 429 | Rate limited (SerpApi) | Wait for the reset window the script reports, then retry |
| 5xx | Upstream API outage | Tell the user which service is down, continue with sections that succeeded |
| Free-engine key missing (Bing/Brave/Mojeek/Google CSE/GitHub/Semantic Scholar) | Optional env var not configured | Skip that engine silently and continue with DuckDuckGo + whatever else is configured — never treat a missing optional key as an error |
| Free-engine block / CAPTCHA / empty results | Rate-limited or blocked, or query too narrow | Back off briefly and retry once with a reworded query; if it still fails, continue with whatever other engines/paid APIs succeeded |
| `scrape-page` non-200 / blocked by robots.txt | Site disallows scraping or needs JS rendering | Fall back to the search snippet, caveated as unverified |
| Downloads folder not writable | Environment restriction or path doesn't exist | Say so plainly, fall back to `~/.openclaw/workspace/reports/{company}_{product}_{date}/`, and tell the user the actual save path |
| `export_report.py` PDF generation fails | Missing `reportlab`/dependency issue | Say so plainly; offer `output.md` instead if PDF specifically failed; never hold back the chat answer over this |

## Examples

**User:** "Do an R&D report on Notion Labs for their Notion product."

Workflow:
1. Company = "Notion Labs", product = "Notion" (already given)
2. `full-report --company "Notion Labs" --product "Notion" --output ~/.openclaw/workspace/reports/notion-labs_notion_2026-06-19/report.json`
3. `wiki-lookup --query "Notion Labs"` to cross-check background facts
4. Render all seven sections directly in chat, including charts, with the SWOT written from the patterns in the other six
5. **Stop — no file generated.** Present the follow-up menu (download / drill in / tech stack / stop)

**User (continuing):** "Yeah go ahead and download that as a PDF."

Workflow:
1. `export_report.py export --format pdf --title "R&D Research Report: Notion by Notion Labs" --markdown-file <the rendered report> --charts-dir ~/.openclaw/workspace/reports/notion-labs_notion_2026-06-19/charts`
2. Saves to `~/Downloads/output.pdf`; confirm the exact path back to the user

**User:** "What patents does Tesla hold around the Cybertruck, plus check arXiv and GitHub for anything related to structural battery packs."

Workflow:
1. Company = "Tesla", product = "Cybertruck", keyword = "structural battery pack"
2. `patents --company "Tesla" --product "Cybertruck" --keywords "structural battery pack"`
3. `arxiv-search --query "structural battery pack"` and `github-search --query "structural battery pack" --type repositories`
4. Render just those sections in chat — no full report needed, no file generated unless asked

**User:** "SerpApi key's not working right now, but can you still pull together what you can on Figma's design tool, plus what people are actually saying about it online?"

Workflow:
1. Company = "Figma", product = "design tool"
2. Try `full-report`; patents/trends/research-papers fail on SerpApi auth — tell the user `SERPAPI_KEY` needs regenerating, then fall back to `web-search --engine all` + `scrape-page` for those three sections, labeled "(via free web search, not SerpApi)"
3. Run an additional qualitative `web-search --engine all` pass (reviews, forum threads, recent news) to populate section 8
4. Render everything in chat; no file generated unless the user separately asks to download

## Resources

- `scripts/rnd_report.py` — CLI wrapping Crunchbase, SerpApi, FMP.
- `scripts/web_research.py` — the free multi-engine layer: DuckDuckGo, Bing, Brave, Mojeek, Google Custom Search, Wikipedia+Wikidata, arXiv, Crossref, Semantic Scholar, GitHub Search, plus `scrape-page`.
- `scripts/export_report.py` — builds `output.md`/`output.pdf` from a rendered report and saves to the Downloads folder on request.
- `references/api-cheatsheet.md` — endpoint paths, auth headers, and payload shapes for the paid services and free-layer APIs, plus their individual rate limits.
- `references/report-template.md` — the full markdown template (including the optional section 8) with placeholder text, for copy/paste consistency across reports.

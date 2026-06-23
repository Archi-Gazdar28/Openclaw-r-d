---
name: rnd-tech-stack
description: Detect the current technology stack behind a company's product (frameworks, hosting, CMS, analytics, via BuiltWith) and/or recommend a technology stack for building something similar. Trigger this whenever the user asks "what tech stack does [company] use for [product]," "what is [product] built with," "what stack should I use to build something like [product]," or asks for a technology-stack breakdown or recommendation for a named company/product — even as a follow-up after an R&D research report. If the user wants financials, patents, trends, competitors, research papers, or a SWOT instead, that's the companion rnd-company-research skill, not this one.
license: Apache-2.0
metadata:
  author: openclaw-user
  version: "1.6.0"
  openclaw:
    requires:
      bins:
        - python3
      python:
        - requests>=2.31.0
        - ddgs>=9.0.0
        - beautifulsoup4>=4.12.0
    optionalEnv:
      - BUILTWITH_API_KEY
      - BING_SEARCH_API_KEY
      - BRAVE_SEARCH_API_KEY
      - MOJEEK_API_KEY
      - GOOGLE_CSE_API_KEY
      - GOOGLE_CSE_ID
      - GITHUB_TOKEN
---

# Technology Stack — Detection & Recommendation

This skill answers two related but distinct questions about a company's product:

1. **"What is it actually built with right now?"** — a *detected* stack, pulled from BuiltWith (or a best-effort web/GitHub fallback if BuiltWith isn't configured).
2. **"What would I use to build something like it?"** — a *recommended* stack, which is reasoning rather than an API call, grounded in the product's category, scale, and target users.

It can run either half alone or both together, and works as a standalone lookup or as a follow-up to a full R&D research report produced by the companion `rnd-company-research` skill.

## Read the script first

This document describes intended behavior, but the actual flags, defaults, and output shape live in the script itself, which can drift from what's written here. **Before running any command for the first time in a session — and any time a call fails in a way this document doesn't explain — view the full contents of:**

- `scripts/tech_stack.py` — wraps BuiltWith, plus the web/GitHub fallback path

Don't rely on `--help` output alone or on this document's examples once the underlying code has changed — read the actual source. If a command in this document doesn't match what the script actually accepts, trust the script.

## When to use this skill

Trigger this skill whenever the user:

- Asks what technology, framework, or stack a named product/company uses, or what a product is "built with" or "running on"
- Asks what stack they should use to build something similar to a named product
- Asks for either of the above as a follow-up after seeing an R&D research report (e.g., they just read a SWOT and now want the stack)

This skill always needs a **product** (and ideally the company that makes it) to scope the lookup. If the user names only a product category with no specific product ("what stack should I use for a SaaS app"), that's fine for the *recommended* half alone — skip the detected half, since there's nothing concrete to detect.

If the user wants financials, patents, trend data, competitor analysis, research papers, or a SWOT, redirect to (or hand off to) the companion `rnd-company-research` skill — this skill doesn't produce those sections.

## Inputs

### Required (for the detected-stack half)

| Input | Notes |
|---|---|
| Company website / domain | BuiltWith looks up by domain, not company name — if the user only gave a company/product name, resolve the domain first via a quick web search before calling BuiltWith |

### Helpful but optional

| Input | Sharpens | Why it helps |
|---|---|---|
| Product category (SaaS, hardware, mobile app, pharma, IoT, etc.) | Recommended stack | The recommended stack differs enormously by category — a mobile app and an IoT device share almost nothing at the infra layer |
| Target customer segment (B2B / B2C / enterprise / consumer) | Recommended stack | Changes the scale and compliance assumptions baked into the recommendation (e.g., SOC 2, HIPAA, multi-tenancy) |
| Known scale signals (user count, traffic, team size) | Recommended stack | Helps calibrate "boring and proven" vs. "lean and fast to ship" recommendations |
| Specific layer of interest (just frontend, just infra, etc.) | Both | Lets you skip generating layers the user doesn't care about |

If the user just wants the detected stack and gives a clear product/domain, proceed without asking anything. Only ask a clarifying question if the domain can't be resolved confidently (e.g., a generic product name with several unrelated companies behind it).

## Detected stack — `scripts/tech_stack.py`

```bash
python3 {baseDir}/scripts/tech_stack.py detect --domain example.com
```

- Calls the BuiltWith API for the given domain. Returns frontend/backend frameworks, hosting provider, CMS, analytics, CDN, and e-commerce platform where applicable.
- Requires `BUILTWITH_API_KEY`. If it's not configured, **don't fail** — fall back automatically:

```bash
python3 {baseDir}/scripts/tech_stack.py web-fallback --query "{product} tech stack" [--limit N]
python3 {baseDir}/scripts/tech_stack.py github-fallback --query "{company} {product}" [--type repositories] [--limit N]
```

  - `web-fallback` fans out across whatever free search engines are configured (DuckDuckGo always available; Bing/Brave/Mojeek/Google CSE if their keys are set) looking for engineering blog posts, "how it's built" writeups, job postings that mention the stack, or conference talks — then scrapes the 1–3 best results for specifics rather than guessing from a snippet.
  - `github-fallback` checks for a public repo (useful when the product is open-source or has public client libraries/SDKs that reveal backend conventions, e.g., a Python SDK implies a REST/gRPC API, a generated OpenAPI client implies a particular framework).
  - Label fallback-derived stack entries "(inferred from public sources, not BuiltWith)" so the user knows the confidence is lower than a direct BuiltWith hit.
- If even the fallback turns up nothing for a given layer, leave that row blank in the table rather than guessing — don't fabricate a detected entry.

## Recommended stack — reasoning, not an API call

This half is you reasoning through the problem, not a tool call. Base it on:

- **Product category** — e.g., a mobile app needs a different data/infra layer than a B2B SaaS dashboard or an IoT device with edge components.
- **Target customer segment** — enterprise/B2B implies SSO, audit logs, multi-tenancy, and stricter compliance defaults (SOC 2, HIPAA, GDPR as relevant); consumer/B2C implies different scaling and cost-sensitivity tradeoffs.
- **What you learned about scale, integrations, and competitors** — if this is a follow-up to a research report, use whatever competitor or company-detail context already surfaced (funding stage, employee count, customer segment) to calibrate "battle-tested and boring" vs. "lean and fast to ship."
- **The detected stack, if you have one** — it's fine for the recommendation to differ from what the actual company uses (codebases accrete legacy choices), but say so explicitly if your recommendation diverges meaningfully, and explain why (e.g., "they're on Rails, likely for historical reasons — for a greenfield build today I'd lean toward X because...").

Present as layers (frontend / backend / data / infra), each with a one-line rationale — not just a name with no justification.

## Output format

```markdown
## Technology Stack: {Product} by {Company}

### Detected (current)
| Layer | Technology | Source |
|---|---|---|

### Recommended (to build something similar)
| Layer | Suggested technology | Why |
|---|---|---|
```

- If only one half was requested, include only that section — don't pad the other with guesses.
- If the detected half came entirely from fallback (no BuiltWith key), add a one-line note above that table: *"BuiltWith isn't configured — this is inferred from public sources, so treat it as directional, not authoritative."*
- If a layer truly can't be determined either way, write "Unknown" rather than leaving the cell looking like an oversight, or omit the row if every column would be unknown.
- Keep this output in the plain black/white/gray styling described in the companion research skill if it's being merged into or exported alongside a fuller report — no colored fills, thin black/gray table borders only.

## Error handling

| Status | Meaning | What to do |
|---|---|---|
| `BUILTWITH_API_KEY` not set | Optional env var not configured | Don't error — run `web-fallback` and `github-fallback` automatically and label results as inferred |
| BuiltWith 401/403 | Bad or expired key | Tell the user the env var needs regenerating, then fall back the same way as a missing key |
| BuiltWith 404 / no domain match | Domain not found in BuiltWith's index | Try resolving the domain again (common with very new or very small products), then fall back |
| BuiltWith 429 / 5xx | Rate limited or upstream outage | Wait for the reported reset window if given, otherwise fall back immediately rather than blocking the answer |
| Free-engine key missing (Bing/Brave/Mojeek/Google CSE/GitHub) | Optional env var not configured | Skip that engine silently, continue with DuckDuckGo + whatever else is configured — never treat a missing optional key as an error |
| Free-engine block / CAPTCHA / empty results | Rate-limited, blocked, or query too narrow | Back off briefly and retry once with a reworded query; if it still fails, present whatever was found and note the gap |
| Domain can't be resolved from company/product name alone | Ambiguous or generic name | Ask one clarifying question (domain, or which of several similarly-named companies) before calling BuiltWith |

## Examples

**User:** "What tech stack does Figma use?"

Workflow:
1. Resolve domain → `figma.com`
2. `python3 scripts/tech_stack.py detect --domain figma.com`
3. If `BUILTWITH_API_KEY` isn't set: `web-fallback --query "Figma engineering blog tech stack"` and `github-fallback --query "Figma"` instead, labeled as inferred
4. Render the "Detected (current)" table only — user didn't ask for a recommendation, so skip that section

**User:** "I want to build something like Notion. What stack should I use?"

Workflow:
1. No detected-stack call needed unless the user also wants to know Notion's actual stack — ask only if it's not already obvious whether they want both halves, otherwise default to recommendation-only since that's what was explicitly asked
2. Reason through product category (collaborative SaaS doc editor), likely target segment (B2B + prosumer), and scale assumptions
3. Render the "Recommended (to build something similar)" table only, with a one-line rationale per layer

**User (continuing from an R&D research report on Notion Labs):** "Okay now show me the tech stack too."

Workflow:
1. Use context already gathered in the research report (funding stage, employee count, customer segment, competitors) to calibrate the recommendation
2. Resolve domain (likely already known from the report's company-details step) and run `detect`
3. Render both tables together under the combined heading

## Resources

- `scripts/tech_stack.py` — CLI wrapping BuiltWith, with a free web-search + GitHub fallback path when BuiltWith isn't configured or fails.
- `references/api-cheatsheet.md` — BuiltWith endpoint paths, auth headers, payload shape, and rate limits; also covers the free-layer engines used by the fallback path.

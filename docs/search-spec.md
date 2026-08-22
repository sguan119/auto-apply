# SPEC — Search Module

> Builds on [PRD.md](../PRD.md) §3 (what to build) → this document records **what the current MVP is**, **how to build it**, and **how to know it is done**.
> Each decision records **the conclusion + rationale + rejected alternatives**, so we don't circle back and re-litigate them later.
> **Read this file before implementing or changing search.** It is the prompt context for the module.

**Status:** spec locked for the search-only MVP. Implementation lives on the `search` branch. **In:** JobSpy fetch, in-run + delivered + seen dedupe, Gate A/B, threshold + cap, LLM rerank on the shortlist, `search pick` → `JobRef[]`, SQLite persist, `search run` / `search list` / `search pick`, local test UI. **Filter / match iteration (gates + LLM rerank):** [search-algorithm-tuning.md](./search-algorithm-tuning.md).

**Current MVP goal:** fetch jobs → cheap local filter → optional LLM shortlist → **show the user a list and let them pick**. Do **not** tailor résumés or auto-apply in this slice.

---

## Decision Summary

| Decision | Conclusion | Scope |
|---|---|---|
| Current MVP | **Search + human review only.** Resume tailoring and deliver are later, on picked jobs only. | search |
| Funnel | Fetch wide → Gate A (hard) → Gate B (cheap score) → **score threshold + per-run cap** → LLM on the shortlist only | search |
| Human gate | After the funnel, the user **sees candidates and checks** which jobs to pursue. Unchecked jobs go nowhere. | search |
| Fetch library | **[JobSpy](https://github.com/speedyapply/JobSpy)** (`python-jobspy` on PyPI), behind a thin adapter. Do not vendor JobSpy source unless we must fork. | search |
| Boards (MVP) | North America: **LinkedIn, Indeed, Glassdoor, ZipRecruiter**. Google Jobs optional. Bayt / Naukri / BDJobs out of scope. | search |
| Layering | Logic in `src/autoapply/core/search/`; CLI is a thin typer entry (`search` script). No TUI in this MVP. | whole system |
| Handoff to later modules | Picked jobs are a **`JobRef[]` JSON file** (plus in-memory pydantic). Not `DeliveryTask` until resume exists. | whole system |
| Dedup | Skip already-seen search keys **and** keys from `get_delivered_job_keys()`. Never read deliver SQLite directly. | search |
| LLM ranking | Cheap model, **shortlist only**. If LLM fails, keep Gate B order. Do **not** reuse `PageDecision` / form-fill prompts. | search |
| ApplyPilot | Reuse the **funnel idea**, not the ApplyPilot package, TUI, or `jobs` schema. | search |

---

## 1. Positioning (current MVP vs later)

AutoApply's long-term pipeline is `search → resume → deliver`. That is unchanged.

**This spec's MVP stops after search + review.** The user does not trust a fully automatic "search then rewrite then apply" loop yet. What to apply to is a human decision.

```text
NOW (this spec)
  bio preferences → fetch → Gate A/B → threshold + cap → [optional LLM]
    → candidate list (CLI table + JSON)
    → user picks
    → selected JobRef[] written to disk

LATER (not this spec)
  selected JobRef[] → resume module (PDF) → deliver module (forms)
  Optional: a config switch to skip the human gate and take the shortlist as-is.
```

**Rejected alternatives:**

- **Search writes `DeliveryTask` and calls `run_delivery()`:** couples modules before resume exists; skips the human gate we just locked.
- **Fixed Top 20 as the definition of a match** (ApplyPilot product rule): fine for a review UI budget, **wrong** as the only filter. A job at rank 21 can still be a match. Threshold decides "eligible"; cap decides "how many we score with the LLM / show this run."
- **Porting ApplyPilot Discovery** (TUI, `evidence_scorer`, `jobs` table columns): that product is browse-and-pick inside ApplyPilot. This repo is CLI-first, contracts-first, and does not have that stack. Copying it would drag in half of another codebase.

---

## 2. Tech Stack

Locked by [deliver-spec.md](./deliver-spec.md) unless noted.

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | Same runtime as deliver; `tomllib` is stdlib. |
| Package | `autoapply.core.search` | Pure Python, **zero UI assumptions**. |
| CLI | typer + rich | New console script `search` (do not pile search commands into `deliver`). |
| Fetch | **JobSpy** — PyPI package `python-jobspy`, import `jobspy.scrape_jobs` | Add to `pyproject.toml` dependencies when implementation starts. Adapter wraps it; core never depends on JobSpy DataFrame columns leaking past the adapter. |
| Models | pydantic v2 | New search models live in `contracts.py` (or a dedicated `core/search/models.py` re-exported from contracts if the file gets large). **Adding/removing fields must update this spec §5.** |
| Config | `config.toml` `[search]` | Non-secret knobs: sites, `results_wanted`, `hours_old`, `score_threshold`, `shortlist_cap`, `llm_rerank`. |
| Secrets | `.env` | Reuse `LLM_API_KEY`. No extra JobSpy key. Proxies, if ever used, are config — not required for MVP. |
| LLM | Existing pluggable LLM settings | Ranking uses a **different JSON schema** than deliver's `PageDecision`. Prefer a cheap model (`[search.llm]` or `[llm]` with a cheaper `model` override). Do not require Claude CLI for ranking. |
| Storage | SQLite `data/app.db` (new search tables) + JSON snapshots under `data/search/` | Sensitive; gitignored via existing `data/` rule. |
| Tests | pytest | Gate A/B and JSON parse must be unit-tested **without** hitting live job boards. Live JobSpy calls are optional, marked, off by default. |
| JobSpy extras | pandas (JobSpy's return type) | Allowed **inside the adapter only**. Normalize to pydantic before leaving fetch. |

**JobSpy usage constraints (MVP):**

- Default sites: `linkedin`, `indeed`, `glassdoor`, `zip_recruiter`.
- `country_indeed`: `USA` (Canada later via bio/config).
- `results_wanted`: default **100 per site per keyword** (cost/rate-limit cap, not a relevance filter). Layer 1 still uses **loose keywords**.
- `hours_old`: default 72.
- `linkedin_fetch_description`: **true** when LinkedIn is enabled, so Gate B / LLM have JD text. Accept the slower fetch.
- Do not enable JobSpy's unbounded / cap-bust splitting. ApplyPilot already showed 10k results/board drowns the funnel with junk.

**Rejected alternatives:**

- **Vendoring JobSpy into `src/`:** only if we must patch it; otherwise we inherit their bugs and license noise.
- **Playwright scraping of LinkedIn/Indeed:** out of scope; JobSpy is the locked fetch layer (PRD §3).
- **Embeddings / vector DB for ranking:** later. Too much infra for MVP.
- **LLM on the full fetch catalog:** unbounded cost; violates "cost must be controllable."

---

## 3. Architecture

Same seam as deliver-spec Decision 2:

```text
Entry:   src/autoapply/cli/search.py   (typer, thin: parse → call core → print)
              │
Core:    src/autoapply/core/search/    (orchestration, fetch, gates, rerank, persist)
              │
Shared:  bio store, contracts, config, repository.get_delivered_job_keys()
```

**Core must not import** CLI, typer, or rich. **Search must not import** `core.deliver.engine` / adapters / Playwright.

### 3.1 Target data flow

```text
search run
  1. Load Settings[search] + bio preference slice
  2. FetchJobs          JobSpy adapter, one query per (keyword × location) as configured
  3. Normalize          adapter rows → SearchJob (internal)
  4. Dedupe             (platform, job_id) within the run; drop keys already in
                        search-seen store OR get_delivered_job_keys()
  5. Gate A             hard drops only (see §6)
  6. Gate B             cheap local score in [0, 1]
  7. Shortlist          score >= score_threshold, then take at most shortlist_cap,
                        sorted by score DESC
  8. LLM rerank         optional; keep/drop/reorder the shortlist only
  9. Persist            run record + candidates (including dropped, with reason)
 10. Present            CLI table of shortlist (Keep-first if rerank ran)
 11. User pick          CLI select → selected JobRef[] JSON
```

Step 11 can be a second command (`search pick`) so a run can be reviewed later.

### 3.2 Suggested package layout (implementation standard)

```text
src/autoapply/core/search/
  __init__.py
  runner.py          # run_search() — the only orchestration entry (mirrors deliver.runner)
  fetch/
    base.py          # DiscoveryAdapter ABC: search(...) -> list[SearchJob]
    jobspy.py        # JobSpyAdapter
  normalize.py       # platform/job_id/url/title/company/description/yoe helpers
  dedupe.py
  gates.py           # Gate A + Gate B (pure functions; easy to test)
  rerank.py          # LLM shortlist; fallback to Gate B order
  store.py           # search tables + JSON snapshot helpers (does not query deliveries SQL)
src/autoapply/cli/search_app.py   # typer app → `search` script
```

Adding a second fetch source later = new adapter + one register line. **Gates and rerank stay source-agnostic.**

### 3.3 CLI commands (MVP)

| Command | Behavior |
|---|---|
| `search run` | Fetch → gates → optional LLM rerank. Prints a shortlist table. Writes `data/search/runs/<run_id>/`. `--no-llm` skips rerank. |
| `search list` | Reprint the latest run shortlist (LLM keep-first when rerank landed). |
| `search pick` | `--id` / `--ids` / `--kept` / `--shortlist`; writes `data/search/selected.json` as `JobRef[]`. Does not apply. |
| `search status` | Latest run id, counts (fetched / dropped / shortlisted / selected). |
| `search from-resume` | **Experimental** ([search-resume-query.md](./search-resume-query.md)): résumé text → query planner → optional `--run` into this same funnel. Does not replace `search run`. |

Default `search pick` is **explicit** — a run does not auto-mark everything as selected.

### 3.4 Experimental resume-query entry

A second **entry** (not a second funnel) lives on the `search-resume-query` branch: paste a plain-text résumé, plan 3–5 board queries, human-edit, then call existing `run_search`. Contract: [search-resume-query.md](./search-resume-query.md). Keyword `search run -k` stays the default path.


## 4. Preferences and configuration

### 4.1 Bio slice (search reads; does not lock the full bio schema)

Search reads `data/bio.yaml` via `BioStore.read_path`. If a path is missing, use `config.toml` `[search]` defaults rather than crashing.

Minimum paths for MVP (names can be bikeshedded but semantics are locked):

```yaml
preferences:
  target_role_keywords: ["product designer", "UX designer"]   # Layer 1 query terms + title_fit
  locations: ["Toronto, ON", "Vancouver, BC"]
  remote: true
  yoe_prefer_min: 0
  yoe_prefer_max: 3
```

**Keyword precedence (locked, from a real ApplyPilot bug):** if the CLI / this run passes explicit keywords, those **fully replace** profile `target_role_keywords` for title_fit and fetch. Profile keywords are the fallback only when the run has no explicit keywords. Never average the two sets.

**Empty search is invalid:** refuse to run a fetch with zero keywords (blank chips produced "ice cream delivery" junk in ApplyPilot).

### 4.2 `config.toml` `[search]` (behavioral)

```toml
[search]
sites = ["linkedin", "indeed", "glassdoor", "zip_recruiter"]
results_wanted = 100          # per site per keyword
hours_old = 72
score_threshold = 0.35        # Gate B; jobs below this never enter the shortlist
shortlist_cap = 20            # cost/UX cap AFTER threshold, not instead of it
llm_rerank = true
llm_timeout = 180             # one rerank call for the whole shortlist
# llm_transport = "http"      # optional override of [llm].transport
# llm_model = "deepseek-chat"  # optional cheaper override of [llm].model
country_indeed = "USA"
```

Score threshold is a **search** parameter (deliver-spec Decision 10). Deliver never re-filters it.

---

## 5. Data contracts

`JobRef` is already defined in [deliver-spec.md](./deliver-spec.md) §5. Search **must** be able to emit it. Unique key = `(platform, job_id)`.

Search needs a richer internal object for filtering and review. **`JobRef` is the subset later modules need; do not cram JD text into `JobRef`.**

```python
class SearchJob(BaseModel):
    """Normalized posting inside search. Adapter output / gate input."""
    platform: str                 # jobspy site name, e.g. "linkedin"
    job_id: str                   # board id; if missing, use a stable hash of the canonical url
    url: HttpUrl                  # prefer company/ATS apply URL when JobSpy provides it
    title: str
    company: str
    location: str | None = None
    description: str | None = None
    date_posted: datetime | None = None
    extracted_yoe: int | None = None
    yoe_is_preferred: bool = False  # "preferred" vs "required" when we can tell; else False

class SearchCandidate(SearchJob):
    """A job after gates (and optional LLM). Shown in review."""
    score: float                  # Gate B score in [0, 1]; JobRef.score uses this
    drop_reason: str | None = None
    llm_keep: bool | None = None
    llm_rank: int | None = None
    llm_reason: str | None = None
    selected: bool = False

class SearchRunSummary(BaseModel):
    run_id: str
    fetched: int
    after_dedupe: int
    dropped_gate_a: int
    shortlisted: int
    llm_kept: int | None = None
    selected: int
    failed_reason: str | None = None
```

**Handoff file** after `search pick` (path convention, still passed explicitly by callers):

`data/search/selected.json` — JSON array of `JobRef` (platform, job_id, url, title, company, score).

That file is what resume/deliver will consume later. Search does not invent `resume_pdf` paths.

**Job id rule:** if the board has an id, use it. If not, use a normalized URL (lowercase, strip tracking query params) as `job_id` so `(platform, job_id)` stays stable.

**URL rule:** prefer the company/ATS link over the job-board listing URL when both exist (deliver-prd: prefer company site). If only the board URL exists, keep it — do not fail the row.

---

## 6. Funnel implementation standards

### 6.1 Layer 1 — Fetch (maximize recall)

- Query each configured site with **loose** role keywords from bio / CLI.
- Multiple preference sets (PRD) = multiple query groups in one run, then merge + dedupe.
- One adapter failure (one site or one query) **must not** abort the run; log and continue.
- Persist raw normalized jobs even if later gates drop them (audit).

### 6.2 Dedupe

Drop a job if any of these hold:

1. Duplicate `(platform, job_id)` in this run (keep the richer description if they differ).
2. Same key already stored as seen in a previous search run (configurable lookback, default 7 days).
3. Key returned by `repository.get_delivered_job_keys()` — **interface only**.

Optional extra: `(lower(title), lower(company))` collapse within a run after Gate A, so the same role posted on two boards can still both appear unless they share a key — **do not** cross-board-collapse in v1 (easy to hide the better apply URL). Revisit later.

### 6.3 Gate A — hard filters (few, strict)

Eliminate only "almost certainly wrong":

| Rule | Behavior |
|---|---|
| Required YoE **>** `yoe_prefer_max` | **Drop** (`drop_reason="required_yoe"`) |
| Preferred-only YoE over max | **Do not** hard-drop; Gate B penalizes |
| No YoE extracted | **Do not** drop |
| Blank/whitespace title | **Drop** (`title_empty`) |
| Optional: Director/VP vs junior profile | **Out of v1** unless extraction is reliable |

**Do not** hard-drop on medium Gate B score — keyword false negatives kill recall (PRD: better wrong than missing).

YoE extraction v1: simple regex on title+description (e.g. `(\d+)\+?\s*years`). Porting ApplyPilot `seniority_classifier` is **not** required for v1.

### 6.4 Gate B — cheap score

Score in `[0, 1]`. v1 formula (locked as the starting point; weights tunable in config later):

```text
score =
    0.50 * title_fit
  + 0.30 * yoe_fit
  + 0.20 * signal        # 1.0 if description length >= 80 chars else 0.3
```

- **title_fit:** overlap of this run's keywords vs `job.title`. Empty title → 0.0 (not 0.5). No keywords → refuse the run (see §4.1).
- **yoe_fit:** in [min, max] → 1.0; missing → **0.60** (demote, still eligible); slightly over max if not Gate-A-dropped → 0.25.
- If keywords are set and `title_fit < 0.3`, exclude from shortlist (`title_mismatch`) even if the weighted score is high. This is the ApplyPilot junk fix.

Skill-coverage / evidence_score from ApplyPilot is **v1.1**, after bio has a stable skills list.

### 6.5 Threshold + cap (locked product rule)

```text
eligible = Gate A pass AND not title_mismatch AND score >= score_threshold
shortlist = first `shortlist_cap` of eligible, sorted by score DESC
```

- Threshold = "is this plausible?"
- Cap = "how many do we LLM-rank and show this run?" (default 20)
- Jobs that pass the threshold but lose the cap stay persisted with `prefilter_rank = null` so we can raise the cap later without re-fetching.

### 6.6 LLM rerank (shortlist only)

**When:** after shortlist; skip if `llm_rerank = false` or shortlist is empty.

**Input:** compact bio (role + YoE prefs + skills if present) + up to `shortlist_cap` jobs (title, company, location, score, truncated JD, max ~3500 chars each).

**Output (strict JSON):**

```json
{
  "ranked": [
    {"job_key": "linkedin:abc", "keep": true, "rank": 1, "reason": "..."},
    {"job_key": "indeed:xyz", "keep": false, "rank": null, "reason": "..."}
  ]
}
```

`job_key` = `"{platform}:{job_id}"`.

**Failure mode:** parse error, timeout, or rate limit → **fallback to Gate B order**, `llm_keep` left null, never wipe the run. (ApplyPilot 429 workaround.)

**Do not** use deliver's `CliLLMClient.decide` / `PageDecision`. Ranking is a separate prompt and schema. Transport is `[llm].transport`: `cli` (local command, default `claude -p`) or `http` (OpenAI-compatible Chat Completions). Search may override with `[search].llm_transport` / `[search].llm_model`. Prefer a cheap model; default deliver Opus is too expensive for batches of JDs.

### 6.7 Human review

- CLI table columns: rank, keep, score, title, company, location, platform, reason.
- Default view: LLM keep-first if rerank ran, else Gate B order.
- User marks selected jobs. Selection is stored on the run; `selected.json` is the export.
- Selecting does **not** start deliver.

---

## 7. Storage and logging

| Data | Where |
|---|---|
| Search runs + candidates | SQLite tables in `data/app.db` (new tables, search-owned functions in `core/search/store.py`) |
| JSON snapshot of a run (debug) | `data/search/runs/<run_id>/candidates.json` |
| Picked handoff | `data/search/selected.json` (`JobRef[]`) |
| Process log | `logs/search-<run_id>.jsonl` (append-only, same spirit as deliver run logs) |

Search **must not** `SELECT` from `deliveries` directly. Dedup against delivered jobs goes through `get_delivered_job_keys()`.

Clearing stale ranks: when a new run starts, commit "clear previous shortlist marks" **before** scoring the new batch, so a crash cannot resurrect the previous run's Top-N as if it were this search (ApplyPilot bug).

---

## 8. Implementation order

Do not start at LLM or deliver integration. Ship in this order; each step is demoable.

1. **JobSpy adapter + normalize + `search run` dumping raw `SearchJob` JSON** (no gates). Proves fetch.
2. **Dedupe + persist run** (including `get_delivered_job_keys()` with a fake/empty DB).
3. **Gate A + Gate B + threshold + cap**; unit tests with fixture postings (no network).
4. **CLI table** for the shortlist (`search list`).
5. **`search pick` + `selected.json` as `JobRef[]`.**
6. **LLM rerank** with mock client tests + live optional.
7. Stop. Resume/deliver wiring is a later spec.

---

## 9. Implementation standards (for later coding agents)

1. English for new code, comments, docs (repo rule). `from __future__ import annotations` + type hints, match existing files.
2. Put behavior in `core.search`; CLI only parses, calls, prints.
3. Gates are **pure functions** over `SearchJob` + prefs — no sqlite, no LLM, no typer. That is what pytest hits first.
4. Never call live JobSpy from unit tests. Adapter tests use a fake `scrape_jobs`.
5. One site/query failing does not fail the run.
6. Do not import ApplyPilot packages or copy `prefilter.py` / TUI / `evidence_scorer.py`. Re-implement the rules in this spec.
7. Do not add search commands to `src/autoapply/cli/main.py` (the deliver app). New script entry in `pyproject.toml`.
8. Config keys go in `config.example.toml`; secrets stay in `.env.example` only as names.
9. Changing `JobRef` / `SearchJob` fields = update this spec §5 **and** `docs/contracts/*.json` via the existing export helper.
10. No proxy pool / anti-detect project in MVP (same posture as deliver PRD). If JobSpy is blocked, fail that site and continue.

---

## 10. Acceptance criteria

Legend: these are the MVP done-when checks. Automation targets `tests/test_search_*.py`. Live board tests are optional and skipped by default.

| ID | Expected behavior | Status |
|---|---|---|
| S-1 | `search run` with valid bio/config keywords fetches from configured JobSpy sites via the adapter (or a fake adapter in tests) and returns normalized `SearchJob` rows with platform, job_id, url, title, company | ⬜ |
| S-2 | A run with **zero keywords** is refused; no fetch | ⬜ |
| S-3 | Duplicate `(platform, job_id)` in one run is collapsed | ⬜ |
| S-4 | Keys in `get_delivered_job_keys()` never appear in the shortlist | ⬜ |
| S-5 | Required YoE > `yoe_prefer_max` is Gate-A dropped; missing YoE is **not** dropped | ⬜ |
| S-6 | Blank title is dropped; `title_fit` of a blank title is 0.0 | ⬜ |
| S-7 | Explicit run keywords override profile `target_role_keywords` (no averaging) | ⬜ |
| S-8 | `title_fit < 0.3` with keywords set → excluded from shortlist (`title_mismatch`) | ⬜ |
| S-9 | Shortlist = `score >= threshold`, then at most `shortlist_cap`, score DESC | ⬜ |
| S-10 | Threshold-pass / cap-fail jobs are persisted, not deleted | ⬜ |
| S-11 | One failed site/query does not abort the run | ⬜ |
| S-12 | LLM keep/drop/rank applied only to the shortlist; bad JSON/timeout → Gate B order, run kept | ✅ |
| S-13 | CLI shows the shortlist; `search pick` writes `JobRef[]` JSON with required fields only | ✅ |
| S-14 | Search does not call deliver / Playwright / resume PDF generation | ⬜ |
| S-15 | Gate A/B unit tests run without network and without JobSpy | ⬜ |
| S-16 | New search run does not leave the previous run's shortlist pinned as current | ⬜ |

**MVP is done** when S-1–S-16 are implemented and S-3–S-10, S-12, S-15, S-16 have automated tests. Live JobSpy (S-1 against the network) can stay a manual check.

---

## 11. Out of scope (this spec)

- Resume rewriting and PDF generation
- Calling `run_delivery` / auto-apply
- TUI (ApplyPilot Discovery tab)
- Embeddings / full-catalog LLM scoring
- Scheduled daemon (PRD allows it; CLI on-demand is enough for MVP)
- Chinese job boards
- Greenhouse/Lever HTML adapters (JobSpy only)
- Perfect scoring; skill taxonomy; Director/VP hard-drop
- Multi-worker search

---

## 12. Open (ask before building if blocked)

- Filter / match iteration (Gate A/B **and** LLM rerank prompt/parse) is **not** open architecture: follow [search-algorithm-tuning.md](./search-algorithm-tuning.md).

- Exact SQLite table names vs JSON-only persistence for v1 (JSON snapshots are required either way; SQLite is preferred for dedup keys).
- Canada as a first-class `country_indeed` / location set vs USA-only MVP.

---

*End of spec. Search MVP funnel (fetch → gates → LLM shortlist → human pick) is implemented on the `search` branch. Resume/deliver wiring is a later spec.*

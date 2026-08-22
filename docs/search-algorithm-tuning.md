# Search Filter Algorithm — Tuning Boundaries

> **Audience:** the agent (or human) iterating the **ranking/filter formula**, not rebuilding search.
> **Parent spec:** [search-spec.md](./search-spec.md) — architecture, contracts, and funnel shape. Read that first.
> **Posture:** the pipeline already runs end-to-end (fetch → dedupe → Gate A/B → shortlist → **LLM rerank** → CLI/UI pick). **Tune the matcher on real dumps; do not redesign the product.**

This file is the **allowed-change contract**. If a change is not listed as in-bounds below, it is out of bounds unless Mark explicitly expands this document.

The matcher has **two stages**. Both are in scope for quality work; they have **different files and different failure modes**. Do not treat LLM rerank as a separate product — it is the last filter before the human.

| Stage | Cheap local | LLM (shortlist only) |
|---|---|---|
| Role | High recall, drop obvious junk, cap cost | Semantic keep/drop + order among the cap |
| Primary file | `gates.py` | `rerank.py` |
| Runs on | Every fetched job after dedupe | At most `shortlist_cap` jobs |
| Failure | Deterministic; tests without network | Parse/timeout → **fallback to Gate B order**, run kept |

---

## 1. Goal of a tuning pass

Improve **shortlist quality** (and, after rerank, **keep/drop quality**) for the user's real searches (fewer junk titles in Keep, fewer good roles dropped), while:

- keeping **high recall** at Layer 1 (fetch stays loose);
- keeping **cost bounded** (threshold + `shortlist_cap`; **no LLM on the full catalog**);
- leaving **human review** as the decision of what to apply to.

Success is judged on **saved runs**, not on a prettier formula or a longer prompt.

---

## 2. Locked product shape (do not change)

These are production requirements from the search spec. Algorithm work **must not** alter them.

| Locked | Meaning |
|---|---|
| Funnel order | Fetch → in-run / seen / delivered dedupe → Gate A → Gate B → `score >= threshold` → take `shortlist_cap` → **optional LLM on that shortlist** → human pick |
| Threshold vs cap | Threshold = “plausible?” Cap = “how many we show / LLM this run.” Cap is **not** the definition of a match. |
| LLM placement | Rerank **after** the cap. Never score the full catalog with an LLM. Never call the LLM on Gate-A drops, `title_mismatch`, `below_threshold`, `already_seen`, `already_delivered`, or cap overflow (`prefilter_rank` is null). |
| LLM schema | Output is `{"ranked":[{"job_key","keep","rank","reason"}, ...]}`. `job_key` = `"{platform}:{job_id}"`. **Not** a `PageDecision`. |
| LLM transport | `[llm].transport` is `cli` (local command) or `http` (OpenAI-compatible API + `LLM_API_KEY`). Search may override with `[search].llm_transport`. Must **not** use `CliLLMClient.decide()` or the form-fill system prompt. Prefer a cheap `search.llm_model`; default deliver Opus is too expensive. |
| LLM failure | Parse error, timeout, non-zero CLI, rate limit → Gate B order, `llm_keep` left **null**, **never wipe the run**. Distinguishes fallback (`llm_kept` is `None`) from “model kept zero” (`llm_kept == 0`). |
| Human gate | Search does not auto-apply and does not call deliver / résumé rewrite. Pick writes `JobRef[]` only. |
| Handoff | Later modules consume `JobRef` (`platform`, `job_id`, `url`, `title`, `company`, `score`). `score` stays the **Gate B** score. Do not put JD text or `llm_reason` on `JobRef`. |
| Keyword precedence | Explicit run keywords **replace** bio `target_role_keywords`; never average the two |
| Empty search | Zero keywords → refuse the run |
| Missing YoE | Soft demote, **never** Gate-A drop |
| Preferred YoE over max | Soft penalty, **never** Gate-A drop |
| No embeddings / full-catalog LLM | Out of scope for this tuning track |
| ApplyPilot code | Do not import or copy `prefilter.py` / `evidence_scorer.py` / TUI |

**Do not** insert a new stage (e.g. embeddings, skill taxonomy, LLM-on-all-jobs) without updating [search-spec.md](./search-spec.md) and this file.

---

## 3. In-bounds files

Stay inside this list unless Mark says otherwise.

### 3.1 Gate A/B (local scorer)

| Path | What you may change |
|---|---|
| `src/autoapply/core/search/gates.py` | **Primary for local filter.** YoE regex, `title_fit`, `yoe_fit`, `signal_score`, weights, Gate A extra **precise** hard rules, `TITLE_FIT_MIN_FOR_TOP` |
| `src/autoapply/core/config.py` `[search]` / `config.example.toml` | `score_threshold`, `shortlist_cap`, and any **new non-secret knobs** you promote from constants (weights, min title fit, min desc chars) |
| `tests/test_search_gates.py` | Required. Add fixtures from real false positives/negatives |
| `docs/search-spec.md` §6.3–6.5 | Only if a Gate A reason or the score formula **meaning** changes; keep in sync |

**Nice-to-have (in-bounds if it unblocks tuning):** a **replay** helper that loads `data/search/runs/<run_id>/jobs.json` (or `candidates.json`) and re-runs **only** `attach_yoe` + `evaluate_job` + `assign_shortlist` — no JobSpy, **no LLM**. Prefer this over hitting live boards every iteration.

### 3.2 LLM rerank (semantic filter)

| Path | What you may change |
|---|---|
| `src/autoapply/core/search/rerank.py` | **Primary for LLM match.** System prompt, compact bio excerpt paths, JD truncate (`MAX_JD_CHARS`), payload fields sent to the model, JSON parse (`parse_rerank_json`), `apply_rerank` / `review_order` (keep-first) |
| `src/autoapply/core/config.py` `[search]` / `config.example.toml` | `llm_rerank`, `llm_timeout`, `llm_model`, `llm_transport`. Do not add a second envelope parser here. |
| `tests/test_search_rerank.py` | Required for prompt/parse/apply changes. Use `CliSearchRerankClient(run_fn=...)` or a fake `rerank()` — **no live CLI** in unit tests |
| `tests/test_search_runner.py` (rerank cases) | Inject `rerank_client=`; assert shortlist-only, fallback on exception |
| `docs/search-spec.md` §6.6 | Only if the ranked JSON **meaning** changes (keep/rank/job_key); keep in sync |

You **may** read `runner.py` to see when rerank is skipped (`llm_rerank = false` or empty shortlist) and how exceptions fall back. Do not add a second LLM call, per-job LLM loop, or retries that multiply cost without Mark saying so.

**One concern per PR:** retune `title_fit` **or** the rerank prompt — not both in the same change. Local gates and LLM will otherwise hide each other's regressions.

---

## 4. Out-of-bounds files (do not touch)

| Path | Why |
|---|---|
| `src/autoapply/core/contracts.py` (`JobRef`, `SearchJob` field set) | Adding/removing contract fields is a spec change, not a scoring tweak |
| `src/autoapply/core/search/fetch/` | Fetch quality ≠ filter quality. Adapter bugs are a different task |
| `src/autoapply/core/search/dedupe.py` | Dedup keys are product rules |
| `src/autoapply/core/search/resume_query.py` | Experimental **query planner** (résumé → board keywords). Not the matcher. See [search-resume-query.md](./search-resume-query.md). |
| `src/autoapply/core/search/pick.py` | Pick is the human gate + `JobRef[]` export, not the matcher |
| `src/autoapply/core/deliver/**` | Separate module |
| `src/autoapply/core/llm/client.py` / `cli_client.py` (`decide`, `PageDecision`) | Form-fill brain. Search ranking must not share that prompt or schema. JSON fence helpers may stay shared; do not teach the deliver parser to accept `ranked` |
| `src/autoapply/core/llm/transport.py` | CLI vs HTTP plumbing, not a scoring tweak |
| `src/autoapply/cli/main.py` | Deliver CLI |
| Playwright / LLM form-fill client | Unrelated |
| `src/autoapply/web/search_app.py` / `search.html` | May **display** keep/reason/`drop_reason`; do not turn the test UI into a new product or call LLM on dropped rows |

You **may** read `runner.py` / `store.py` / the test UI to understand `drop_reason`, shortlist, and keep-first order, but do not rewire orchestration (no new pipeline stages, no calling deliver, no LLM before the cap).

---

## 5. Tunable knobs (current v1)

### 5.1 Local gates — `gates.py` + `[search]`

**Config today**

- `score_threshold` (default `0.35`)
- `shortlist_cap` (default `20`)

**Constants today — fair game to move into `[search]` if you tune them often**

```text
score = 0.50 * title_fit + 0.30 * yoe_fit + 0.20 * signal
title_fit < 0.3  → drop_reason = "title_mismatch"
signal = 1.0 if len(description) >= 80 else 0.3
missing YoE → yoe_fit = 0.60
```

**Stable `drop_reason` strings** (do not rename; the UI and tests key on them). You may **add** new reasons.

| Value | Meaning |
|---|---|
| `title_empty` | Gate A |
| `required_yoe` | Gate A: required years > `yoe_prefer_max` |
| `title_mismatch` | `title_fit` below min |
| `below_threshold` | score < `score_threshold` |
| `already_delivered` | runner/dedupe, not gates |
| `already_seen` | runner/dedupe, not gates |

Cap overflow: `drop_reason` stays `null`, `prefilter_rank` stays `null`. Do not invent a drop reason that hides “eligible but not in this run’s budget.” Those rows **must not** be sent to the LLM.

### 5.2 LLM rerank — `rerank.py` + `[search]`

**Config today**

- `llm_rerank` (default `true`; CLI `--no-llm` / UI checkbox can turn off)
- `llm_timeout` (default `180` — **one call** for the whole shortlist, not per job)
- `llm_model` (optional; empty = `[llm].model`)
- `llm_transport` (optional; empty = `[llm].transport`: `cli` or `http`)

**Constants / prompt contract — fair game inside `rerank.py`**

```text
MAX_JD_CHARS = 3500
job_key = "{platform}:{job_id}"
stdout = {"ranked": [ {job_key, keep, rank, reason}, ... ]}
```

**Stable LLM fields** (do not rename on `SearchCandidate`; UI/CLI/tests key on them):

| Field | Meaning |
|---|---|
| `llm_keep` | `true` / `false` from the model; **`null` = rerank did not land** (skipped or fallback) |
| `llm_rank` | 1 = best keep; null when keep is false or fallback |
| `llm_reason` | One short sentence for the reviewer |
| `prefilter_rank` | Gate B order; **never overwritten** by the LLM |

Display: keep-first (`review_order`) when any `llm_keep` is non-null; otherwise Gate B `prefilter_rank`.

**Stdout constraint:** raw `{"ranked":...}` (optional ` ```json ` fence). Same anti-envelope rule as deliver: do **not** use `claude -p --output-format json`. Do **not** accept a `PageDecision` (`decisions` / `next_action`) as a successful rerank.

Bio excerpt is **compact** (keywords, locations, YoE prefs, optional skills/summary). Do not dump the entire `bio.yaml` into the prompt.

---

## 6. How to iterate (required workflow)

1. **Freeze a corpus.** Copy 1–3 real runs: `data/search/runs/<run_id>/jobs.json` (and `candidates.json` for what the old formula / old prompt did). These files are gitignored; keep a local `docs/local/` or private folder if you need notes. Do **not** commit personal job dumps or LLM transcripts that contain the user's bio.
2. **Replay gates first** on that JSON (helper or a pytest fixture that loads the file). Do not `search run` against live JobSpy for every weight tweak. Do not call a live LLM to debug `title_fit`.
3. **Label by hand** on that corpus: keep / junk / unsure. Optimize gates for fewer junk in the **shortlist** without dropping labeled keeps (recall on labeled goods).
4. **Only then** look at LLM keep/drop on that same shortlist. Replay with a **fixture JSON** of `ranked` items or a `run_fn` that returns recorded stdout — live CLI is optional dogfood, not the inner loop.
5. **Change one concern per PR:** e.g. title_fit only, or YoE regex only, or rerank prompt only — not weights + regex + prompt together.
6. **Run** `pytest tests/test_search_gates.py tests/test_search_rerank.py tests/test_search_runner.py tests/test_search_dedupe.py tests/test_search_pick.py` plus any new fixture tests. Fetch/adapter tests should stay green without network. Rerank unit tests must stay green **without** invoking the real CLI.

If live fetch is still returning garbage **titles that never match the query**, that can be `title_fit` / `TITLE_FIT_MIN_FOR_TOP`. If the **wrong jobs are on the board because JobSpy/query is wide**, that is fetch/config (`results_wanted`, keywords), **out of bounds** for this agent unless Mark says to change fetch.

If the shortlist looks right but the model keeps junk / drops goods, that is **`rerank.py` prompt or excerpt**, not a reason to raise `shortlist_cap` or LLM the full catalog.

---

## 7. Known v1 weaknesses (starting backlog)

Observed while dogfooding; treat as hypotheses, confirm on the frozen corpus:

**Gates**

- Token `title_fit` (`all(word in title)`) can over-credit generic words like “designer”.
- YoE regex is naive (`N years` anywhere); can misread salary, company age, or “2 years preferred” vs required.
- Short JDs get a low `signal` and may fall under threshold even when the title is a perfect match.
- Blank-search junk is already blocked at run start; **cross-run** `already_seen` can hide a job you wanted to re-score after a formula change — use **replay on `jobs.json`**, not a second live run, when iterating.

**LLM**

- JDs longer than `MAX_JD_CHARS` are truncated; requirements at the bottom of a posting can disappear.
- Using the default deliver model (Opus / expensive) for 20 JDs will dominate cost; set `search.llm_model` to a cheap model before tuning prompt length upward.
- Fallback (`llm_keep` null) looks like “no opinion” in the UI — do not “fix” that by retrying the same failed call in a loop.
- `keep=false` jobs stay on the shortlist (keep-first, not keep-only) so the human can override. Do not auto-delete them from the run.
- Partial model output (some `job_key`s missing) leaves those rows `llm_keep` null; do not invent keeps for missing keys.

Skill-coverage / bio skills list = **v1.1**, only after bio has a stable skills field. Do not invent a taxonomy in `gates.py` or a huge skill dump in the rerank excerpt before that.

---

## 8. Done-when for a tuning PR

- [ ] Shortlist **or** LLM keep/drop on the frozen corpus is better on labeled keep/junk (state the before/after counts in the PR)
- [ ] No change to `JobRef` / fetch adapter / deliver / `PageDecision`
- [ ] Existing gate tests pass; rerank tests pass **without** a live LLM
- [ ] If you touched gates: at least one new test encodes a real miss you fixed; `drop_reason` old values still mean the same thing
- [ ] If you touched rerank: fallback still leaves the run intact; non-shortlist rows still have `llm_keep is None`; stdout is still `{ranked: [...]}` not a form-fill object
- [ ] Weights/thresholds/prompt constants live in `gates.py` / `rerank.py` or `config.example.toml`, not magic numbers copied into the UI

---

*End. Parent architecture stays in search-spec.md. This file is only the fence around the matcher (local gates + shortlist LLM).*

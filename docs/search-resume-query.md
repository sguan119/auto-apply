# SPEC — Resume-query entry (experimental)

> Parent: [search-spec.md](./search-spec.md). Matcher fence: [search-algorithm-tuning.md](./search-algorithm-tuning.md).
> This is a **second search entry**, not a second funnel. Keyword `search run` stays.

**Status:** experimental on `search-resume-query`. In: plain-text résumé → cheap LLM query planner → human edit → existing `run_search` → existing shortlist rerank (with a résumé excerpt) → existing pick. **Out:** PDF parse, writing `bio.yaml`, a second job-ranking LLM, embeddings, auto-apply.

---

## Decision Summary

| Decision | Conclusion |
|---|---|
| What this is | A **query planner**. It chooses Layer 1 board keywords. It does not replace Gate A/B or shortlist rerank. |
| Entry | New CLI `search from-resume` + a panel on the local test UI. `search run -k` is unchanged. |
| Input | Plain text (paste, `.txt`, `.md`). **PDF refused** with a clear error. |
| LLM #1 | Résumé → `{queries, clusters, yoe_guess, resume_summary, notes}`. Cheap model. Same transport as search (`cli` / `http`). |
| Queries | 3–5 **short, loose board terms** (e.g. `product designer`), not LinkedIn-style titles. Diversity across role clusters; skills are not queries. |
| Human gate on queries | Plan is shown and editable **before** fetch. `--run` skips that confirm for dogfood. |
| Fetch | `run_search(keywords=queries)` — existing adapter, dedupe, gates, cap. |
| LLM #2 | Existing shortlist rerank only. `resume_summary` is added to `compact_bio_excerpt`. No new ranking schema. |
| Bio | **Do not write** `bio.yaml`. Keywords and excerpt are ephemeral to this run. `yoe_guess` is display-only; Gate A/B still use bio / config YoE. |
| Handoff | Unchanged: `search pick` → `JobRef[]`. |

**Rejected alternatives:**

- **LLM picks 2–3 job titles, then a second LLM ranks the full catalog:** too few queries, synonym collapse, unbounded cost.
- **Skill names as JobSpy queries** (`Figma`, `Unreal`): high junk, low recall of roles.
- **Parse résumé into `preferences.target_role_keywords`:** starts the bio/resume schema on an experiment. Revisit after this entry is dogfooded.
- **PDF parsing in v1:** layout/columns are a separate problem; text/markdown is enough to test the planner.
- **Auto-apply after decode:** human pick stays.

---

## 1. Data flow

```text
search from-resume FILE
  1. Load plain text (refuse .pdf; empty text is invalid)
  2. Truncate to MAX_RESUME_CHARS
  3. LLM query planner  OR  use --query values (skip planner)
  4. Normalize queries (strip, lowercase, drop skills/dups/overlong, cap at 5)
  5. Persist data/search/resume_plan.json  (gitignored; no full résumé body)
  6. Print queries / clusters / notes  — stop here unless --run
  7. run_search(keywords=queries, resume_excerpt=resume_summary)
  8. Existing funnel: fetch → dedupe → Gate A/B → cap → optional rerank → pick
```

Step 6 is the human edit surface. On the test UI: Propose queries fills the Keywords field; Search is the existing button.

---

## 2. Planner JSON

```json
{
  "queries": ["product designer", "ux designer", "game designer", "level designer"],
  "clusters": ["product/ux design", "game/level design"],
  "yoe_guess": {"min": 1, "max": 3},
  "resume_summary": "One to three sentences: function, domain, YoE, notable skills.",
  "notes": "One short sentence for the reviewer."
}
```

`queries` is required and non-empty after normalize. Other fields are optional.

**Prompt constraints (locked for v1):**

- 3–5 queries when the résumé supports it; fewer is allowed if only one cluster exists. Hard-fail only on **zero** usable queries.
- Each query: 2–4 words, no seniority (`Senior` / `Staff` / `Lead`), no company, no location.
- Cover distinct clusters. Three UX synonyms as the whole set is a miss when another track is on the résumé.
- Do not emit tool/skill tokens as queries.
- Reply is this object only (optional ` ```json ` fence). **Not** `{"ranked":...}` and **not** a `PageDecision`.

**Failure:** parse error, timeout, or empty queries → do **not** fetch. Same transport as search; do not call `CliLLMClient.decide()`.

---

## 3. What existing search must accept

`run_search(..., resume_excerpt: str | None = None)` passes the excerpt into `compact_bio_excerpt` as `resume`. Keyword-only runs send no `resume` key.

Do **not** change `JobRef`, Gate A/B formulas, dedupe keys, or `search pick`.

Fetch cost: N queries × sites × `results_wanted`. The test UI Quick mode still lowers `results_wanted`. Do not silently divide the cap in v1.

---

## 4. Files

| Path | Role |
|---|---|
| `src/autoapply/core/search/resume_query.py` | Extract, normalize, planner client, parse |
| `src/autoapply/cli/search.py` | `from-resume` only; `run` unchanged |
| `src/autoapply/web/search_app.py` / `search.html` | `/api/resume-plan` + résumé panel; `/api/search` may take `resume_excerpt` |
| `src/autoapply/core/search/rerank.py` | Optional `resume` on the bio excerpt |
| `src/autoapply/core/search/runner.py` | Optional `resume_excerpt` into rerank |

**Do not touch for this experiment:** `gates.py`, `fetch/`, `dedupe.py`, `pick.py`, `core/deliver/**`, form-fill `decide()`.

---

## 5. Acceptance

| ID | Behavior |
|---|---|
| R-1 | `.txt` / `.md` / pasted text loads; `.pdf` is refused; empty text is refused |
| R-2 | Planner stdout `{queries:[...]}` is parsed; `PageDecision` / `{ranked:...}` is not a successful plan |
| R-3 | Normalized queries are lowercase, de-duplicated, skill-blocklisted, capped at 5; zero queries fail before fetch |
| R-4 | `--query` skips the LLM and still builds a `resume_summary` from the text |
| R-5 | Plan is written under `data/search/`; bio file is not modified |
| R-6 | `from-resume` without `--run` does not call `run_search` |
| R-7 | `--run` / UI Search after plan calls existing `run_search` with those keywords + excerpt |
| R-8 | Keyword `search run -k` still works with no résumé |
| R-9 | Unit tests inject `run_fn` / fake clients — no live LLM, no live JobSpy |

---

*End. Promote into search-spec.md only after dogfood. Until then this file is the contract for the experimental branch.*

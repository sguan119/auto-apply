# Devlog

## 2026-08-21 | Search MVP funnel [RESOLVED] #Search #Architecture
* **Context/Scope:** `docs/search-spec.md`, `src/autoapply/core/search/`, `src/autoapply/cli/search.py`, `src/autoapply/web/search_app.py`
* **Objective:** Ship a search-only loop (fetch → cheap filter → human pick) on the `search` branch without copying ApplyPilot or wiring deliver.
* **Roadblock(s):**
  1. [RESOLVED] ApplyPilot Discovery used Top-20 + TUI + its own job DB; AutoApply PRD is a high-recall feed into later modules, so transplanting `prefilter.py` / TUI would lock the wrong product.
  2. [RESOLVED] JobSpy looked like something to vendor into `src/`; forking it would freeze a scraper we do not own.
  3. [RESOLVED] Gate weights cannot be designed from a spec; dogfood showed junk titles, but rewriting the funnel to “fix” them would mix structure changes with scoring.
* **Solution/Pivots:**
  1. Locked the funnel as fetch → Gate A/B → **score threshold + `shortlist_cap`** → human review; cap is a cost/UX budget, not the definition of a match. Human pick is in-MVP; résumé/deliver stay later.
  2. Added `python-jobspy` (1.1.82) via `pyproject.toml` and wrapped `scrape_jobs` in `JobSpyAdapter` so our code owns normalize/dedupe/failure isolation.
  3. Shipped a thin E2E (`search run` / `search list` / local FastAPI UI) then wrote `docs/search-algorithm-tuning.md` so a later agent may touch `gates.py` only, replaying `jobs.json` instead of live boards (`already_seen` would hide the same keys).
* **Verification:** User dogfooded the local test UI and accepted the shortlist. Search unit tests (fake adapter, no live JobSpy) passed before LLM work landed.

## 2026-08-21 | Search LLM rerank + pick [RESOLVED] #Search #LLM #CLI
* **Context/Scope:** `src/autoapply/core/search/rerank.py`, `pick.py`, `runner.py`, `src/autoapply/cli/search.py`, `docs/search-algorithm-tuning.md`
* **Objective:** Rank only the Gate B shortlist with an LLM, then export checked jobs as `JobRef[]` without starting deliver.
* **Roadblock(s):**
  1. [RESOLVED] Deliver’s `CliLLMClient.decide()` expects `PageDecision`; using it for ranking would parse the wrong schema or silently reject good stdout.
  2. [RESOLVED] `[search].llm_rerank` defaults true, so existing `run_search` tests would spawn the real CLI (Opus-priced, flaky) on every pytest.
  3. [RESOLVED] A parse/timeout/429 must not delete the run (ApplyPilot 429 lesson); `llm_keep` null has to mean “fallback”, distinct from keep=false.
  4. [RESOLVED] Tuning doc originally fenced only `gates.py`; LLM keep/drop is also the matcher, so a later agent could “fix” junk by LLMing the full catalog.
* **Solution/Pivots:**
  1. Added `CliSearchRerankClient` with its own prompt and `{"ranked":[...]}` extractor (`job_key="{platform}:{job_id}"`); transport may reuse `[llm].command` but never `decide()` / `PageDecision`.
  2. Injected `rerank_client` in tests; existing runner tests force `llm_rerank=False`; UI checkbox defaults off so local dogfood stays cheap.
  3. Caught any rerank exception, kept Gate B `prefilter_rank`, left `llm_keep` null, set `llm_kept=None` vs `0` for “model kept none”. `search pick` writes `data/search/selected.json` as JobRef fields only (`--id` / `--kept` / `--shortlist`).
  4. Extended the tuning fence: in-bounds `rerank.py` prompt/parse/truncate; out-of-bounds full-catalog LLM, form-fill client, `JobRef` shape, pick/deliver.
* **Verification:** `pytest` on search modules: 76 passed (rerank parse/apply, shortlist-only, 429 fallback, pick JobRef field set, CLI/UI). No live LLM in unit tests.

## 2026-08-21 | LLM transport: CLI vs API key [RESOLVED] #LLM #Config
* **Context/Scope:** `src/autoapply/core/llm/transport.py`, `cli_client.py`, `src/autoapply/core/search/rerank.py`, `config.example.toml`, `.env.example`
* **Objective:** Let the user pick local Claude CLI or their own OpenAI-compatible API key (DeepSeek) without rewriting ranking or form-fill.
* **Roadblock(s):**
  1. [RESOLVED] Rerank spawned `claude -p`; putting a DeepSeek key in `LLM_API_KEY` changed nothing because that CLI uses Claude Code login, not our env key.
  2. [RESOLVED] `[llm].command` is shared with deliver, so swapping the command to DeepSeek would also hijack Workday form-fill.
  3. [RESOLVED] HTTP providers differ; a vendor-specific SDK would lock us to one company, and error strings must not echo the key.
* **Solution/Pivots:**
  1. Added `[llm].transport` = `cli` (default, local `claude -p`) or `http` (OpenAI-compatible Chat Completions via `complete_prompt()`). Both search and deliver call that one function, then parse their own JSON.
  2. Added `[search].llm_transport` / `llm_model` overrides so ranking can be DeepSeek HTTP while deliver stays Claude CLI. Key stays in `.env` as `LLM_API_KEY`; `base_url` is config, not a secret.
  3. Built HTTP against `/v1/chat/completions` only (DeepSeek / OpenAI / Groq). Tests assert the Bearer token never appears in raised errors.
* **Verification:** `pytest tests/test_llm_transport.py tests/test_cli_client.py tests/test_search_rerank.py tests/test_search_runner.py tests/test_search_pick.py` — 50 passed; HTTP path mocked, no live API.

## 2026-08-22 | Search UI Custom API dogfood [RESOLVED] #Search #UI #LLM
* **Context/Scope:** `src/autoapply/web/search.html`, `search_app.py`, `src/autoapply/core/search/runner.py`
* **Objective:** Make the local test page say how to call the model, and actually hit Custom API (DeepSeek) on a repeat search.
* **Roadblock(s):**
  1. [RESOLVED] The “LLM rerank” checkbox read as “use DeepSeek”; transport was only in `config.toml`, so the page could not choose Custom API vs Claude CLI.
  2. [RESOLVED] First live HTTP run (`f41c0fae`, 10:57) raised `HTTP LLM transport needs [llm].base_url` and fell back to Gate B with `llm_kept` null; the UI showed `—` and looked idle.
  3. [RESOLVED] Next live run (`0681aad1`, 11:27) fetched 24 / unique 17, dropped **17/17 `already_seen`**, shortlisted 0, so rerank never called; silent skip plus POST overriding `llm_rerank` from an unchecked box hid that.
* **Solution/Pivots:**
  1. Split intent: checkbox = rerank or not; after check, a Custom API (`http`) / Claude CLI (`cli`) toggle posts `llm_transport` (hint: `LLM_API_KEY` + `[llm].base_url`).
  2. Uncommented `[llm].base_url = "https://api.deepseek.com"` in local `config.toml` (key stays in `.env`). HTTP already required both; the example comment made `base_url` look optional.
  3. Defaulted **Include already-seen jobs** (`seen_lookback_hours = 0`) on the test page, returned `llm_error` on skip/fail, and painted it on the page instead of only `llm kept —`.
* **Verification:** Run dumps: 10:57 traceback matched missing `base_url`; 11:27 `candidates.json` was 17× `already_seen`. `pytest tests/test_search_ui.py tests/test_search_runner.py` — 16 passed (toggle, `include_seen`, empty-shortlist `llm_error`). Live DeepSeek keep/drop after restart not re-run in this session.


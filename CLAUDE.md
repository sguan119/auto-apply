# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AutoApply** — a fully automated job-application tool (open source). Overall flow: **search jobs → tailor résumé → auto-apply**. The three modules — **search / resume / deliver** — are highly independent and interact only through data contracts.

**This repository currently ships the CLI version of the deliver module** (Workday-only MVP). Search is specified in [`docs/search-spec.md`](docs/search-spec.md) and implemented on the `search` branch; resume is not yet built. Foundational deliver decisions are in [`docs/deliver-spec.md`](docs/deliver-spec.md). **Read the matching spec before changing search or deliver architecture**, to avoid circling back to choices that have already been debated.

## Common Commands

```bash
# Install (Python 3.11+; config parsing relies on stdlib tomllib)
python -m venv .venv
.venv\Scripts\activate            # Windows; on macOS/Linux use source .venv/bin/activate
pip install -e ".[dev]"           # installs the core and cli packages + pytest; tests import `from autoapply.core...`, so install first

# Tests
pytest                            # full suite
pytest tests/test_engine.py       # single file
pytest tests/test_runner.py::TestResumeCrossJob            # single class
pytest tests/test_engine.py::TestSelectorCache -k cache    # single test

# Run the search CLI (entry point defined in pyproject [project.scripts])
search run -k "product designer" -l "Toronto, ON"   # fetch → gates → optional LLM rerank
search run --no-llm                                 # skip LLM; Gate B order only
search list                                         # reprint current shortlist
search pick --id linkedin:abc --id indeed:xyz       # write data/search/selected.json (JobRef[])
search pick --kept                                  # pick every LLM keep=true job
search ui                                           # local test page (does not apply)
search from-resume resume.md                        # experimental: propose board queries from a résumé
search from-resume resume.md --run                  # plan then fetch with those queries

# Run the deliver CLI (entry point defined in pyproject [project.scripts])
deliver run --tasks tasks.example.json --manual   # run a delivery pass (manual is the default)
deliver run --tasks tasks.example.json --auto --headful   # auto mode + headed browser (for debugging)
deliver answer                    # interactively answer pending questions (writes back to bio, prioritized on the next run)
deliver retry workday R12345      # manually retry a single FAILED job (failures don't auto-retry by default)
deliver status                    # print delivery records + the list of pending questions
```

No lint/format toolchain is configured; code style follows the existing files (`from __future__ import annotations`, type annotations). All committed content — code, comments, docstrings, commit messages, and docs — is written in English. Existing Chinese comments and docstrings are grandfathered in; translate them opportunistically when the surrounding block is substantially rewritten, never in a sweeping mass-translation commit.

## Configuration and Secrets

- Non-secret behavioral parameters go in `config.toml`; secrets go in `.env` (both are gitignored — **never commit either**). The repo ships templates only: `cp config.example.toml config.toml`, `cp .env.example .env`.
- If `config.toml` hasn't been created yet, the loader falls back to `config.example.toml`, so the tool runs out of the box on first try.
- **Deliver / search LLM:** `[llm].transport` is `cli` (default: local `claude -p`) or `http` (OpenAI-compatible API; key in `.env` as `LLM_API_KEY`, plus `[llm].base_url` / `model`). Search may override with `[search].llm_transport` and `[search].llm_model` (e.g. DeepSeek for ranking, Claude CLI for form-fill). CLI stdout / HTTP message must be the raw business JSON — **do not** use `claude -p --output-format json`.

## Architecture Overview

Three layers, with the seam matching spec Decision 2, "separate core logic from the interface":

```
Entry layer   src/autoapply/cli/ (typer, thin)         Future Web backend (FastAPI, thin)
                       └──────────────┬──────────────┘
Core layer          src/autoapply/core/  (pure Python package, zero UI assumptions)
```

**Every command in `src/autoapply/cli/main.py` only does "parse args → call a core function → format and print"** — all real orchestration, storage, and browser logic lives in core. When adding a feature, put the logic in core; don't pile it into the CLI.

### The heart of the delivery engine: the DOM → LLM → Playwright per-page loop (spec Decision 4)

This is a bespoke execution architecture — no visual screenshots, no Agent-MCP. Data flow:

1. **`src/autoapply/core/deliver/dom.py`** `collect_page(page)` — simplifies the current page's DOM and numbers every interactive element, producing a `PageSnapshot` (including a `selector_map`: number → Playwright selector).
2. **`src/autoapply/core/llm/client.py` / `cli_client.py`** — `LLMClient.decide(PageContext)` has the LLM make a decision for the whole page ("which numbered element to fill, what value, and the value's source: BIO/LLM_GENERATED/USER_ANSWER"), returning a `PageDecision` (`actionable` + `uncertain`/needs_user + `next_action`).
3. **`src/autoapply/core/deliver/browser.py`** `apply_action()` — executes the decision with Playwright (searchable dropdowns are automatically routed to a "type + Enter" flow).
4. **`src/autoapply/core/deliver/engine.py`** `FillEngine.run_form()` — drives the three steps above in a per-page loop until `completed`/`suspended`/`failed`. **The engine only knows about injected abstract interfaces** (`LLMClient`/`BioStore`/`QuestionChannel`/`RunLogger`) — it doesn't import state_machine/repository, and only returns a structured `RunFormResult`.

**The selector cache (`src/autoapply/core/deliver/selector_cache.py`)** is a token-saving patch: the key is the page's **structural fingerprint** (excludes values). See `engine._is_cross_job_cacheable()` for the critical safety boundary — pages with an `LLM_GENERATED` fill value or an `upload` action are **never cached across jobs** (otherwise a cover letter/résumé from job A could get replayed onto job B — a real misdelivery bug; regression test at `test_runner.py::TestResumeCrossJob`).

### State Machine + Orchestration (spec Decisions 6/7/8)

- **`src/autoapply/core/deliver/state_machine.py`** — 8 states per job: `PENDING → OPENING → AUTHENTICATING → FILLING ⇄ WAITING_USER → READY_TO_SUBMIT → SUBMITTING → CONFIRMING → SUCCEEDED`; failure at any stage → `FAILED(reason)`; `WAITING_USER` timeout → `SUSPENDED` (non-terminal, recoverable).
- **`src/autoapply/core/deliver/runner.py`** `run_delivery()` — **the single orchestration entry point**, wiring up every component in exact order to drive each job's state machine, producing a `RunSummary`. The module's top-of-file docstring has the literal outcome→DeliveryStatus mapping — read it before touching orchestration.
- **Recovery = re-applying from scratch, not resuming the browser session.** A suspension can span days, so keeping a Playwright context alive isn't realistic; the form hasn't been submitted yet, actions are idempotent, and the answer has already been written back to bio, so in theory it won't get stuck on the same field again.
- **Persistence discipline**: `repository.record_delivery()` is called exactly once, only at a terminal state or SUSPENDED — never mid-state.

### Key Abstractions (replaceable seams)

- **Platform adapter layer `src/autoapply/core/deliver/adapters/`** — only the segment from "job URL to the form's first page / decide whether login is needed" (the OPENING state) varies by platform and can't be generalized, so it's cut into its own layer. `base.py`'s `PlatformAdapter` ABC is deliberately kept small; adding a platform means writing a subclass + `@register_adapter` + adding one import line in `adapters/__init__.py` — `select_adapter()` doesn't need to change. **FILLING itself stays generic** and doesn't go through the adapter layer.
- **Question channel `src/autoapply/core/questions/channel.py`** — the `QuestionChannel.ask(questions, timeout)` abstraction. The CLI implementation is terminal interaction (`src/autoapply/cli/terminal_channel.py`); auto mode uses `AutoAnswerChannel` (suspends immediately when it can't answer); a future Web implementation would use WebSocket/SSE. Questions are batched per page; on timeout, the job is suspended and the run continues with the next one.
- **LLM client `src/autoapply/core/llm/`** — the `LLMClient` abstraction, with `CliLLMClient` as the first implementation, running a headless CLI subprocess (see "Configuration and Secrets" above).

### Data Contracts and Storage (spec Decisions 5/9)

- **Contracts live in `src/autoapply/core/contracts.py`** (pydantic models): `JobRef` (unique key `(platform, job_id)`), `DeliveryTask` (deliver's input: job + resume_pdf/cover_letter_pdf paths), `DeliveryRecord` (output), `RunSummary`, `Question`/`Answer`/`BioWriteback`/`FilledField`. **Adding or removing fields must be reflected in spec Decision 5 at the same time.** Large files like PDFs are only passed as paths, never embedded in the object body. `src/autoapply/core/export_schemas.py` exports the contracts to `docs/contracts/*.json` for documentation reference.
- **Storage is split by data shape**: `data/app.db` (SQLite, `storage/repository.py`: delivery records/credentials/pending questions/run records — needs key-based lookups for deduplication) + `data/bio.yaml` (`bio/store.py`, the user's hand-maintained single source of truth, must be human-readable) + `logs/run-<run_id>.jsonl` (`storage/run_log.py`, an append-only process audit log per run) + `data/artifacts/<platform>/<job_id>/` (résumé artifacts).
- **Hard constraint on module decoupling**: cross-module access only goes through core interfaces (e.g., the search module uses `get_delivered_job_keys()` to query already-applied jobs for deduplication) — never read another module's storage directly.
- `data/`, `logs/`, `.env`, `config.toml`, résumés/cover letters are **all gitignored** (sensitive data must never enter the repo).

## Roadmap

CLI (current) → Website (FastAPI + frontend on top of core) → Docker release. Search MVP = fetch + filter + human pick ([`docs/search-spec.md`](docs/search-spec.md)); resume is not yet built. Follow-up topics listed as "open" in the deliver spec: non-Workday platform adapter abstraction, bio schema, DOM simplification/selector cache implementation details, multi-worker pause coordination.

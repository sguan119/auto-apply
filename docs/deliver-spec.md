# SPEC — Deliver Module Technical Specification

> Builds on [deliver-prd.md](./deliver-prd.md) (what to build) → this document records the technical decisions on *how* to build it.
> Each decision records **the conclusion + rationale + rejected alternatives**, so we don't circle back and re-litigate them later.
> This document grows as discussion progresses; the foundational technology choices and behavioral details/data contracts are settled — remaining small items are listed under "Open" at the end.

## Decision Summary

| Decision | Conclusion | Scope |
|---|---|---|
| Language / runtime | **Python** | whole system |
| CLI → Website layering | **pure-Python `core` package + thin entry layers** | whole system |
| Browser driver | **Playwright** | deliver |
| Execution architecture | **A: bespoke "DOM simplify+number → LLM decision → Playwright execution" loop** | deliver |
| Data contracts | **Pydantic models + in-memory calls**; large files like PDFs passed as paths | whole system |
| Delivery state machine | 8 states per job; **SUSPENDED is recoverable = re-apply, not resume the session** | deliver |
| Blocking questions | **QuestionChannel abstraction + per-page batching + timeout → suspend** | deliver |
| Deduplication / retry | delivery record's unique key feeds back to search; **failures don't auto-retry by default** | deliver |
| Storage | **SQLite (records/credentials) + bio.yaml + JSONL logs** | deliver (bio is whole-system) |
| Configuration and secrets | **config.toml (non-secret) + .env/environment variables (secrets)** | whole system |

---

## 1. Language / Runtime: Python (whole system)

**Conclusion**: all three modules (search / resume / deliver) use Python uniformly, a single runtime.

**Rationale**:
1. **The search module is anchored to JobSpy** — JobSpy is a Python library (locked in by the root PRD section 3), so at least one module can't avoid Python.
2. **A single runtime is cheapest overall**: for an open-source, solo-maintained project headed toward a Docker release, two runtimes would mean two sets of dependency management, two test setups, two Docker base images, and contributors having to set up two environments — a real cost.
3. Playwright-Python is a first-class citizen and can run Architecture A just fine; a pluggable LLM only needs a thin Python SDK abstraction.

**Rejected alternatives**:
- **Node/TS**: the only compelling reason would have been the ready-made Stagehand framework (TS-only), but once Architecture A was chosen we don't pull in Stagehand itself (only borrow its caching idea), so that reason disappears. Frontend JS doesn't count as a counterexample (see Decision 2).

## 2. CLI → Website Layering (whole system)

**Conclusion**: core logic is built as a **pure-Python package `core` (zero UI assumptions)**; the CLI and the future Web backend are both thin entry layers sharing the same core. This matches the "separate core logic from the interface" constraint in [CLAUDE.md](../CLAUDE.md).

```
Entry layer:   CLI (typer/click, thin)      Web backend (FastAPI, thin, future)
                        └──────────┬──────────┘
Core layer:          core (search / resume / deliver, pure Python)
                                   │
Presentation layer:        Web frontend (React/Vue/htmx, inherently JS in the browser)
```

**Key points**:
- **Frontend JS is independent of the backend language**: any web app's frontend has to be JS/HTML — every architecture has this layer, and it's isolated at the outermost edge, so it doesn't undercut the "single backend runtime" goal.
- **The seam where CLI and Web share core**: PRD section 7's **API mode** — each module is written as a callable service, with the CLI and Web backend each wrapping it in a thin layer.
- **The "ask only when blocked" channel is swappable**: the CLI asks in the terminal; the Web version pushes questions to the frontend via FastAPI's WebSocket/SSE — the underlying core is the same, only the question-channel implementation changes.
- deliver runs its **own headless Playwright, server-side** — it never touches the user's browser, so going Web-based involves no friction.

## 3. Browser Driver: Playwright (deliver)

**Conclusion**: use Playwright (Python) as the browser driver layer.

**Rationale** (mostly derived by working backward from PRD constraints):
1. **The PRD requires headless + API mode** (section 7) → needs to run headless/server-side.
2. **The PRD doesn't fight an anti-detection war** (section 5: no in-house anti-detection, no proxy pools/IP rotation) → anti-detection selling points count for nothing, so we can pick whichever has the cleanest API.
3. **Forms are dynamic and multi-step (Workday especially)** → Playwright's **auto-waiting** eliminates a lot of hand-written waits and flaky code.
4. **Login-state concerns** (LinkedIn/Workday require accounts) → **persistent context** reuses profile cookies; if needed, `connect_over_cdp` can attach to a real, already-logged-in Chrome.
5. **The door stays open**: browser-use / Skyvern, if adopted later, both sit on top of Playwright anyway.

**Rejected alternatives**:
- **Selenium**: clunkier and more flaky; since we're going LLM+DOM instead of hardcoded selectors, we don't benefit from its ecosystem.
- **Browser extension / content script** (the approach commercial plugins use): requires a headed desktop Chrome, which **conflicts with headless/API mode**.
- **undetected-chromedriver / nodriver and other anti-detection drivers**: their one selling point is cut off entirely by the PRD's "no anti-detection war" stance.

> Note: Playwright is the **driver layer**; browser-use / Skyvern / Stagehand sit on top of it as a "brain" layer, orthogonal to this decision.

## 4. Execution Architecture: A — Bespoke Imperative Loop (deliver)

**Conclusion**: a bespoke **"DOM simplify+number → LLM decides 'which numbered element, what value' → Playwright execution → repeat per page"** imperative loop (i.e., the technical approach in PRD section 3). Borrows **Stagehand's caching idea** (first LLM inference → cache the selector → only recompute when the page redesigns) as a **token-saving patch**, without pulling in Stagehand itself.

**Rejected alternatives**:
- **B: Agent + browser-MCP** (Claude/other models + Playwright-MCP etc., a standardized version of ApplyPilot's approach): faster to get started, but **every step goes through a big model, which is expensive**, locks in an Agent ecosystem, and gets costly at delivery volume; the caching patch here is essentially trying to save money for that approach.
- **Visual CUA / Computer Use** (OpenAI Operator, Anthropic Computer Use, Google Mariner): **consumes screenshots**, directly ruled out by the PRD's "no visual screenshots" (section 3).

---

## 5. Data Contracts: Pydantic Models + In-Memory Calls (whole system)

**Conclusion**: contracts between modules are defined with **pydantic models**, and passed between modules as **Python objects directly, in-process** (core is a single-process package, and both the CLI and Web backend call core in-process — see Decision 2). Large files like PDFs **never go into the object body — only paths are passed**. When persistence or cross-process transfer is needed, they're serialized to JSON; the contracts themselves can auto-export a JSON Schema via pydantic, for documentation and contributor reference. This also answers the "data contract format and passing mechanism" open item from [CLAUDE.md](../CLAUDE.md).

**Core deliver-side contracts** (the field list may be tweaked during implementation, but **adding/removing fields must come back and update this section**):

```python
class JobRef(BaseModel):
    """The subset of search-module output that deliver depends on. Unique key = (platform, job_id)."""
    platform: str          # source platform, e.g. "linkedin" / "indeed"
    job_id: str            # job ID within the platform; platforms without one use a normalized URL instead
    url: HttpUrl           # delivery entry point (prefer company site/ATS, see PRD 2)
    title: str
    company: str
    score: float           # search-module score, determines delivery order

class DeliveryTask(BaseModel):
    """deliver's input: one job to apply to plus the materials tailored for it."""
    job: JobRef
    resume_pdf: Path       # resume-module artifact, path convention under "9. Storage"
    cover_letter_pdf: Path | None

class DeliveryRecord(BaseModel):
    """deliver's output: the result record for one delivery (PRD 8)."""
    job: JobRef
    status: DeliveryStatus            # terminal states, see "6. Delivery State Machine"
    filled_fields: list[FilledField]  # per form field: the original question, the filled value, and the value's source (bio/LLM-generated/user answer)
    failure_reason: str | None        # e.g. "captcha_unsolved" / "login_failed"
    run_id: str
    started_at: datetime
    finished_at: datetime

class BioWriteback(BaseModel):
    """The carrier for writing a user's answer back to bio (PRD 4)."""
    field_path: str        # field path within bio, e.g. "preferences.visa_sponsorship_needed"
    question: str          # the original form question, kept for the record
    answer: str
```

- **The bio schema belongs to the bio module** and gets its own document; deliver only depends on "read by field path + write back" as two interfaces, not on bio's internal structure.
- **PDF path convention**: the resume module writes its artifacts to `data/artifacts/<platform>/<job_id>/resume.pdf` (and `cover_letter.pdf`); `DeliveryTask` still passes the path explicitly — the convention only exists for debuggability, and the contract never implicitly depends on directory structure.

**Rationale**:
1. Decision 2 already settled on core as a single-process pure-Python package, so in-memory calls are the shortest path; files/queues would be self-inflicted complexity at the MVP stage.
2. pydantic gives validation, serialization, and JSON Schema export as a package, so contracts don't drift from the code during open-source collaboration.
3. Passing PDFs as paths avoids copying large binaries around in objects, consistent with the "records go into SQLite, files go into a directory" storage split.

**Rejected alternatives**:
- **Exchanging JSON files**: process-level decoupling is a plus, but adds a layer of read/write and file lifecycle management, which is actually more roundabout in API mode. If we ever do split into separate processes, `model_dump_json()` on a pydantic object gives isomorphic JSON for free, so the migration cost is already accounted for.
- **dataclass + hand-written JSON Schema**: saves one dependency, at the cost of hand-writing validation/serialization/schema export — not worth it.

## 6. Delivery State Machine (deliver)

**Conclusion**: a single job's lifecycle is as follows; **recovery = re-apply from scratch, not resume the browser session**.

```
PENDING → OPENING → AUTHENTICATING → FILLING ⇄ WAITING_USER
                                        │
                          (manual mode pauses here)  READY_TO_SUBMIT
                                        │
                                   SUBMITTING → CONFIRMING → SUCCEEDED
Failure at any stage → FAILED(reason); WAITING_USER timeout → SUSPENDED (non-terminal, recoverable)
```

- **PENDING**: enters this run's delivery queue (sorted descending by score).
- **OPENING**: opens the job URL and follows any redirect to the company site/ATS landing page.
- **AUTHENTICATING**: logs in when an account is required; auto-registers if there's no account (PRD 6) — the registration form reuses the same LLM+DOM loop as FILLING, and email verification codes are retrieved automatically from the read-only mailbox. Credential read/write is covered under "9. Storage".
- **FILLING**: the per-page loop "DOM simplify+number → LLM decision → Playwright execution" (Decision 4). **Captchas are a sub-step within FILLING/AUTHENTICATING**, not their own state (detect type + sitekey → CapSolver solves it → inject); if solving fails → `FAILED("captcha_unsolved")`, skipped without retry (PRD 5).
- **WAITING_USER**: this page has an uncertain field, so a question is raised and awaits an answer (see "7"). Once the answer arrives → written back to bio → returns to FILLING; on timeout → SUSPENDED.
- **READY_TO_SUBMIT**: only manual-submit mode (PRD 7, the default) pauses here, requesting user confirmation via the question channel before moving to SUBMITTING; auto mode passes straight through.
- **CONFIRMING**: waits for and recognizes the **submission confirmation page**; seeing it means SUCCEEDED, otherwise FAILED (the success criterion from PRD 8).
- **Terminal states**: `SUCCEEDED` / `FAILED(reason)`. **SUSPENDED is a persisted, non-terminal state**: the job and its questions are stored, and once answers are supplied (at the end of this run or the start of the next) it's **re-applied from OPENING**.

**Rationale (why recovery means re-applying)**: a suspension can last anywhere from tens of minutes to multiple days, so keeping a live Playwright session (memory, session validity) isn't realistic; before re-applying the form hasn't been submitted yet, the actions are idempotent, and bio has already been written back, so in theory it won't get stuck on the same field again — the cost of re-applying is just a few extra page loads.

**Rejected alternatives**:
- **Freezing the browser context on suspend and resuming in place**: sessions expire, headless server memory pressure builds up, and it's unrecoverable after a crash — far more complexity than it's worth.
- **Making captchas an independent state**: captchas can appear on any page during login, registration, or the form itself, so modeling them as a sub-step within any state fits reality better.

## 7. Blocking Question Mechanism (deliver)

**Conclusion**: core defines a **`QuestionChannel` abstract interface**; questions are **batched per page**; on timeout, **the job is suspended and the run continues with the next one**.

- **Channel abstraction**: `QuestionChannel.ask(questions, timeout) -> answers | TIMEOUT`. The CLI implementation is terminal Q&A; a future Web implementation would use FastAPI WebSocket/SSE to push to the frontend (the seam is already reserved by Decision 2). Manual-submit mode's "confirm before submitting" also goes through the same channel — no separate mechanism.
- **Per-page batching**: the LLM already makes one decision for the whole page at a time, so every uncertain field on that page (missing from bio / low confidence, PRD 4) is combined into a single question batch. Multi-step forms require submitting the current page to see the next, so per-page *is* the natural batching limit — batching across pages isn't physically possible.
- **Timeout → suspend**: the wait duration is configurable (`question_timeout`, 30 minutes by default). If unanswered by the timeout, the job is set to SUSPENDED and the unanswered questions are persisted; the run continues with the next job. Once an answer arrives (via the next CLI interaction / an API answer-submission endpoint), it's written back to bio first, then re-applied per the rules in "6".
- **Unattended closed loop**: at the end of a run, all SUSPENDED jobs' unanswered questions are listed together in the summary (see "8"), so the user can answer them all at once, and the next run absorbs them automatically.

**Rejected alternatives**:
- **Blocking indefinitely**: strictly follows PRD 4's literal flow, but if the user steps away the whole run hangs forever, directly violating the "unattended" core principle.
- **Treating timeout as failure**: simplest to implement, but by the time the user comes back the job has already been missed and there's nowhere to submit an answer — wasted effort.
- **Asking field-by-field**: interrupting the user 3 times for 3 uncertain fields on the same page, with the pipeline idling between each Q&A — a pure downside.

## 8. Cross-Run Deduplication, Retries, and Run Summaries (deliver)

**Conclusion**:

- **Deduplication**: the delivery-records table uses `(platform, job_id)` as its unique key. **A SUCCEEDED job is never applied to again**; the search module queries the already-applied list via the core interface `get_delivered_job_keys()` for dedup feedback (root PRD 3, "already-applied jobs are auto-skipped") — going through an interface rather than reading the other module's storage directly preserves module decoupling.
- **Failures don't auto-retry**: PRD 5 already settled that captcha failures don't retry; other failures (login failure, confirmation page never appearing, etc.) likewise **don't auto-retry across runs by default** — a failure is most likely environmental (site redesign, bot detection), so blindly retrying burns tokens and risks a duplicate submission. A CLI command is provided to **manually retry a single job by its job key**.
- **SUSPENDED auto-recovers**: the exception — at the start of the next run, suspended jobs whose questions have already been answered are **prioritized ahead of new jobs** (score ordering is preserved within the suspended group).
- **Easy Apply daily-cap counting**: the rolling 24h count is persisted (PRD 2's ≈50 cap); once hit, falls back to the company site or queues for the next day.
- **Run summary**: each run writes one run record; at the end it produces a `RunSummary` (pydantic contract): totals / successes / failures grouped by reason / a list of suspended jobs + unanswered questions. The CLI prints it as a table; in API mode it's the return value.

**Rejected alternatives**:
- **Having the search module read the delivery database directly for dedup**: saves one interface, but creates implicit cross-module storage coupling, violating the CLAUDE.md constraint.
- **Auto-retrying failures N times**: ineffective against the main causes (page redesigns/bot detection), and auto-resubmission risks misdelivery — at odds with the industry-standard "safety valve" consensus (research 3.1).

## 9. Storage (deliver-focused, bio is whole-system)

**Conclusion**: **a single SQLite database + a single bio file + JSONL process logs**, split by data shape:

| Data | Medium | Notes |
|---|---|---|
| delivery records / credentials / pending questions / run records / Easy Apply counts | **a single SQLite database** `data/app.db` | needs key-based lookups (dedup) and transactional writes; will also hold up under future multi-worker concurrent writes |
| bio | **a single file** `data/bio.yaml` | the user's hand-maintained single source of truth, must be human-readable and editable; YAML is friendly to multi-line text (experience descriptions) |
| process logs | **JSONL** `logs/run-<run_id>.jsonl` | split per run, appended line by line (steps, LLM decisions, captcha solving, errors), for debugging and auditing (PRD 8) |
| résumé artifacts | file directory `data/artifacts/…` | see the path convention in "5" |

- **Storing credentials in plaintext** was already decided in PRD 6; this section just implements it: they go into the credentials table in `app.db`.
- **`.gitignore` must exclude** `data/`, `logs/`, `.env` (next section) — enforcing CLAUDE.md's "sensitive data never enters the repo" hard constraint.

**Rejected alternatives**:
- **All-JSON files**: zero dependencies, but once delivery records grow, dedup requires loading everything into memory, and concurrent appends can corrupt files; SQLite is part of the Python standard library, so the actual dependency cost is zero.
- **All-SQLite (including bio)**: uniform, but sacrifices bio's editability — the user couldn't edit their own information directly with a text editor, undermining the "single source of truth, user-maintainable" positioning.

## 10. Configuration and Secrets (whole system)

**Conclusion**: **non-secret configuration goes in `config.toml`; secrets go through environment variables (`.env` for local development, gitignored)**. The repo ships `config.example.toml` and `.env.example` as templates.

| Belongs to | Content |
|---|---|
| `config.toml` | delivery-mode switch (auto/manual, manual by default), score threshold, `question_timeout`, Easy Apply daily cap, LLM model name/`base_url`, password generation mode (random/template), mailbox IMAP address, and other **behavioral parameters** |
| environment variables / `.env` | `LLM_API_KEY`, `CAPSOLVER_API_KEY`, read-only mailbox authorization (IMAP app password or OAuth token file path), and other **secrets** |

- **Threshold source**: the score threshold is a search-module filtering parameter, set by the user in `config.toml` and consumed by the search module; deliver only receives the already-filtered list and doesn't re-evaluate it (keeping the contract boundary intact).
- **Pluggable LLM** (root PRD 4): configuration only needs `model` + `base_url` + a key; core uses a unified LLM client abstraction internally and isn't tied to a specific provider.

**Rationale**: separating config from secrets is standard practice for open-source projects to prevent accidental leaks; TOML has native stdlib `tomllib` parsing and shares a family with pyproject, with zero extra dependencies.

**Rejected alternatives**:
- **Writing secrets into the config file**: a single accidental commit becomes a leak incident, and even an example template is easy to copy into a real file and forget to gitignore.
- **YAML configuration**: equivalent capability, but requires pulling in pyyaml just to read it (bio uses YAML because it's **data** the user hand-edits frequently — a different tradeoff dimension).

---

## Open (future spec topics)

- **Platform adapter layer abstraction**: how platforms beyond Workday (Greenhouse / Lever / LinkedIn Easy Apply) plug into the generic LLM+DOM engine with a minimal interface — to be worked out once Workday is running end-to-end, based on the actual shape that emerges (matches the open item in CLAUDE.md).
- **bio schema**: field structure and read/write interfaces belong to the bio module and get their own document.
- **DOM simplification algorithm and selector cache implementation details** (Decision 4's implementation details): simplification rules, numbering stability, cache-invalidation logic — to be settled during implementation.
- **Multi-worker pause coordination** (the future feature from PRD 10): merging questions when multiple workers collide on the same field — not blocking the single-worker MVP.

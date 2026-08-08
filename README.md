# AutoApply

A fully automated job-application tool (open source). Overall flow: **search jobs → tailor résumé → auto-apply**.

The three modules interact through explicit data contracts and are highly independent: **search**, **resume**, and **deliver**. This repository currently focuses on landing the CLI version of the **deliver** module — see [`docs/deliver-spec.md`](docs/deliver-spec.md) for details.

## Requirements

- Python 3.11+ (config parsing uses the stdlib `tomllib`, which requires 3.11+).

## Installation

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## Configuration

Non-secret behavioral parameters go in `config.toml`; secrets go in `.env` (both are excluded by `.gitignore` and must never be committed). The repo only ships templates:

```bash
cp config.example.toml config.toml   # adjust delivery mode, timeouts, LLM command, etc. as needed
cp .env.example .env                  # fill in real secrets: LLM / CapSolver / IMAP, etc.
```

If `config.toml` hasn't been created yet, the loader automatically falls back to `config.example.toml`, so the tool runs out of the box on first try.

### LLM Command Requirements (important)

The CLI subprocess configured under `[llm].command` **must write the raw PageDecision JSON object to stdout** — that single `{"decisions": [...], "next_action": ...}` object (optionally wrapped in a ` ```json ` code fence, with explanatory text before/after being fine too — the parser extracts the object).

Key pitfall: **do not** use `claude -p --output-format json`. That `--output-format json` produces Claude Code's result envelope,
`{"type":"result","result":"…(decision JSON escaped into a string)…"}`,
where the real decision JSON is hidden inside the `result` string and there's no top-level `decisions`/`next_action`. The parser rejects it → every page produces `llm_decision_error`, and the whole pipeline breaks. That's why the default is `claude -p` without
`--output-format` (it writes the model's raw text reply straight to stdout, and the system prompt already instructs the
model to reply with nothing but a single PageDecision JSON object).

The same applies to any other CLI (Gemini CLI, a local-model wrapper script, etc.): it just needs to write the **raw decision JSON**
to stdout; if a given tool defaults to wrapping it in an envelope, write a thin wrapper script that unwraps the inner decision
JSON and point `command` at that script instead.

## Running

```bash
deliver --help                          # list command groups
deliver version                         # print the version

deliver run --tasks tasks.example.json --manual   # run a delivery pass (manual is the default, see config.toml)
deliver run --tasks tasks.example.json --auto --headful  # auto mode + headed browser (for debugging)
deliver answer                          # interactively answer pending questions (writes back to bio, prioritized on the next run)
deliver retry workday R12345            # manually retry a single FAILED job (Decision 8: failures don't auto-retry by default)
deliver status                          # print delivery records + the list of pending questions
```

### tasks.json Format

`deliver run --tasks` takes a JSON file containing a `DeliveryTask[]` array (the contract from Decision 5 in
`docs/deliver-spec.md`; normally produced by the search + resume modules, but here it's hand-written for local
verification), shaped like `tasks.example.json`:

```json
[
  {
    "job": {
      "platform": "workday",
      "job_id": "R12345",
      "url": "https://acme.wd1.myworkdayjobs.com/.../Software-Engineer_R12345",
      "title": "Software Engineer",
      "company": "Acme Corp",
      "score": 0.92
    },
    "resume_pdf": "data/artifacts/workday/R12345/resume.pdf",
    "cover_letter_pdf": "data/artifacts/workday/R12345/cover_letter.pdf"
  }
]
```

`cover_letter_pdf` can be omitted or set to `null`. `score` determines delivery order (descending); suspended jobs
are re-applied ahead of new tasks once their questions are answered, so they don't need to be included in this file
(`deliver run` checks for them automatically every time).

## Tests

```bash
pytest
```

## Directory Layout

```
src/autoapply/core/    pure Python core package (zero UI assumptions): contracts / config / storage / delivery engine
src/autoapply/cli/     thin command-line entry layer
docs/                  PRD and technical spec (deliver-spec.md has the settled foundational decisions)
data/                  runtime data (bio.yaml / app.db / résumé artifacts), gitignored
logs/                  per-run JSONL process logs, gitignored
```

## Conventions

- **Separate core logic from the interface**: the CLI and the future Web backend share `core`; the interface is just a thin entry point.
- **Module decoupling**: cross-module interaction only goes through data contracts — no implicit coupling.
- **Sensitive data never enters the repo**: secrets, cookies, personal résumés, and delivery records are all gitignored.

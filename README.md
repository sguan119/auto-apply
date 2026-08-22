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

### LLM (cli vs your own API key)

`[llm].transport` chooses how the model is called:

- **`cli`** (default) — run `[llm].command`, by default local Claude Code `claude -p`.
- **`http`** — OpenAI-compatible Chat Completions. Put the key in `.env` as `LLM_API_KEY`, set `[llm].base_url` and `[llm].model` (DeepSeek, OpenAI, Groq, …). Search can override with `[search].llm_transport` / `[search].llm_model` so ranking uses a cheap API while deliver still uses Claude CLI.

The model reply **must be the raw business JSON** (deliver: `PageDecision`; search: `{"ranked":[...]}`), optionally in a ` ```json ` fence. **Do not** use `claude -p --output-format json` — that wraps the payload in a Claude Code envelope and the parser rejects it.

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

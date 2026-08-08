# PRD — Deliver Module

> Detailed requirements for the deliver module, split out from [PRD.md](../PRD.md). See the root PRD for overall project background, how the three modules relate, and the bio module definition.
> This document only describes *what* to build, not *how* to build it (architecture is discussed once functionality is settled), though sections where the technical direction is already settled are called out explicitly.

## 1. Positioning

- The deliver module is the last stage of the pipeline: `search → resume → deliver`.
- **Input**:
  - The scored, above-threshold job list from the search module (sorted descending by score);
  - The cover letter + résumé PDF the resume module tailored for each job;
  - The bio module — the single source of truth.
- **Output**: delivery result records (which jobs were applied to, what was filled into each form); when a field is missing from bio, the user's supplied answer is written back to bio.
- **Core principle: unattended, ask only when blocked.** Runs fully automated by default and never interrupts the user; it only stops to ask when it hits a field it can't confidently fill.

## 2. Delivery Scope

- **Platform scope: North America only**, matching the search module (JobSpy). Domestic Chinese platforms (BOSS Zhipin, etc.) are out of scope — the domestic-platform approaches gathered during research are kept only as architectural reference, not part of the current scope.
- **First platform to ship: Workday** employer portals, prioritized. Reason: Workday is one of the most common ATSes among North American employers, and existing open-source projects like ApplyPilot have already validated that "LLM + DOM generic form filling" can cover a large share of Workday portals (without writing per-employer selectors), making it a good first stop for an end-to-end path.
- **Login requirements vary by platform**: Easy Apply requires a LinkedIn login; most company sites don't require login for a direct application; but **Workday usually requires an account** — each employer's Workday portal has an independent account system (an account registered with Employer A can't log into Employer B's portal), so applying to a Workday job will most likely require going through a "register/log in" flow (see "6. Account and Credential Management").
- **Prefer the company site for delivery**: even when LinkedIn Easy Apply is available, prefer applying through the company site/ATS instead (Easy Apply has a low hit rate and often doesn't lead to interviews).
- **In scope**: on-platform delivery (e.g. Easy Apply) + delivery via redirect to a company site/external ATS (Workday / Greenhouse / Lever, etc.).
- **Out of scope**: applications that require actively sending an email.
- **Easy Apply daily cap ≈ 50** (a LinkedIn limit, rolling 24h, not relaxed even for Premium; once hit, only the company-site path remains) → this cap needs handling (fall back to the company site / queue for the next day). Other company-site/ATS deliveries have no unified rate limit and don't need extra throttling.

## 3. Reading Pages and Filling Forms (technical approach settled)

- **No visual screenshots**: screenshots would blow up token consumption.
- **Approach: LLM + structured DOM understanding** (see research in [research/deliver-scheme-summary.md](research/deliver-scheme-summary.md), Approach 5):
  1. Collect the current page's DOM, simplify it, and number the interactive elements;
  2. Hand the numbered list + bio to the LLM, which decides what to fill into which numbered element;
  3. Repeat per page until the form is complete.

## 4. Field-Handling Rules

- **Open-ended text questions** (e.g. "Why do you want to join our company") **do not count as uncertain fields and are never blocking**: the LLM generates an answer on the spot using bio (work experience, skills, job preferences, etc.), with no need to wait on the user.
- **Handling uncertain fields (blocking)**: aside from the open-ended case above, a field is treated as "not confident" — and delivery stops to ask the user — if either of the following holds:
  1. The field has **no corresponding information in bio** (e.g. "do you require visa sponsorship");
  2. It was filled, but with **low confidence**.
- **Flow**: raise the question to the user → the user answers → the answer is **written back to bio** → **the current job's delivery continues using the updated info**, then moves on to the next job.

## 5. Captcha / Anti-Bot Handling (technical approach settled)

- **Approach: follow ApplyPilot's method** (see research in [research/autofill-tools/01-applypilot.md](research/autofill-tools/01-applypilot.md)):
  1. When a captcha is hit (hCaptcha / reCAPTCHA / Turnstile / FunCaptcha, etc.), first detect its type and sitekey;
  2. Call a third-party captcha-solving service API (e.g. CapSolver) to solve it and inject the result, then continue delivery.
- **When it genuinely can't be solved** (no solving service configured, or solving fails): mark that job's delivery as failed, skip it, and move on to the next one — without blocking the overall run or retrying.
- No in-house captcha-solving or anti-detection algorithms, no proxy pools/IP rotation — that kind of adversarial work is expensive and its payoff is uncertain, so it's out of scope for now.

## 6. Account and Credential Management

- **Auto-create accounts**: when the target platform/ATS (typically Workday) requires an account to deliver, the registration flow is completed automatically — reusing the same LLM+DOM approach from "3. Reading Pages and Filling Forms" to fill out the registration form, rather than building separate registration-specific logic.
- **Automatic email verification retrieval**: if registration/login requires an email verification code or link, the user's mailbox is read automatically (**read-only**) to retrieve the code or click the verification link — the user never needs to go check their inbox manually.
- **Password generation and storage**: a password is generated and recorded for each platform/employer portal, supporting either **random generation** or a **user-defined template**, at the user's choice; the next time a job on the same portal is applied to, the existing account is reused to log in rather than registering again.
- **Storage and security constraints**:
  - **Stored locally in plaintext, unencrypted** (e.g. JSON / SQLite). Reason: passwords are randomly generated per platform and independent of one another (never reusing the user's real personal password), so the actual damage from a single job site's account leaking is very low — not worth the friction of a master password/keystore unlock step, which would break the "unattended, fully automated" flow and headless/API modes.
  - The one hard constraint: matching the critical constraint in [CLAUDE.md](../CLAUDE.md) — this is an open-source project, so credential data **must never be committed to the repo** and must be excluded via `.gitignore` (enforced during the architecture phase).
  - Credentials and bio are two different kinds of data: bio is the job seeker's personal information (name/experience/skills, etc.), while credentials are "login state for a given platform" — they're stored separately, though both are read and written by the deliver module.

## 7. Run Modes

- **Invocation**: supports both **API mode** (invoked as a service) and **headless CLI mode** (run from the command line with no UI).
- **Delivery mode**: a global switch supporting **auto-submit** (submits the form as soon as it's filled) and **manual submit** (only fills the form, waiting for user confirmation before submitting). Only one mode can be selected at a time, and once chosen it applies to **every job in that run** — it can't be switched per job. **Manual submit is the default.**

## 8. Records and Logging

- **Delivery result records**: record which jobs were applied to, what was filled into each form, and whether delivery succeeded or failed (including failures caused by captchas).
- **Success criterion**: defined by reaching the platform's **submission confirmation page** — seeing the confirmation page counts as success, anything else counts as a failure.
- **Process logs**: record key steps and exceptions during the run (e.g. account registration/login, captcha detection and solving, field-fill decisions, error messages), for debugging and later auditing — not just the final result.
- **Storage**: local storage is sufficient (e.g. JSON / SQLite + log files); **no cross-device sync is needed**.

## 9. Concurrency

- **Delivery scope**: each run applies to **every above-threshold job in the list**, with no cap on the number of applications per run.
- **Current (MVP)**: single-worker only — applies **sequentially, one at a time**, in descending score order.
- **Future feature: parallel multi-worker delivery** — when a field is missing from bio, the same pause-and-ask logic applies, consistent with the single-worker behavior.

## 10. Open Items

- **Multi-worker pause-coordination details** (future feature, not blocking the current version): when multiple workers run in parallel and two of them hit the same missing field at the same time (e.g. both ask "do you require visa sponsorship"), does each worker pop up its own question, or do they get merged into a single question/single write-back that all workers share?

# PRD — AutoApply

> Open-source project. End-to-end automation of the job search: **search jobs → tailor résumé → auto-apply**.
> This document only describes *what* to build, not *how* to build it (architecture is discussed once functionality is settled).

## 1. Overall Shape

- Three functional modules plus one shared **bio module**.
- Modules are highly independent and interact only through data contracts.
- Priority: CLI first, to get one end-to-end path working.

```
        ┌─────────────────────────────┐
        │      bio module (bio)        │  ← single source of truth, shared by all three modules
        └─────────────────────────────┘
              ▲           ▲          ▲
              │           │          │(writes back uncertain fields)
        ┌─────┴───┐ ┌─────┴───┐ ┌────┴────┐
        │ search  │→│ resume  │→│ deliver │
        └─────────┘ └─────────┘ └─────────┘
```

## 2. Bio Module (bio)

- The central data shared by all three modules — the system's **single source of truth**.
- Holds all of the job seeker's information: basic info, education, experience, skills, job preferences, and more.
- **Can be written back to by the deliver module**: when delivery hits an uncertain or missing field, it asks the user, and the answer is written back into bio so it never has to ask again.

## 3. Search Module

- Uses the open-source library **[JobSpy](https://github.com/speedyapply/JobSpy)** to scrape job postings.
- **Platform scope: North America only** (LinkedIn / Indeed / ZipRecruiter / Glassdoor, etc., as supported by JobSpy).
- Search criteria come from **the job preferences in bio**; multiple preference sets can be configured.
- **Trigger**: run manually once, or run continuously on a schedule. **Users can configure the search interval (how often to search).**
- **Deduplication**: jobs that have already been searched or already applied to are automatically skipped.

### Two-Layer Design (core)

Job boards' own search is quite inaccurate and easily misses matching jobs. So this is split into two layers, aiming for **high recall** (better to over-include than to miss one):

1. **Layer 1 · Search (maximize recall)**: query each platform with **deliberately loose** criteria to pull in as many candidate jobs as possible, never missing a good job at this step.
2. **Layer 2 · Filter (our own algorithm)**: filter and score the pooled jobs with our own algorithm. Same principle — **better wrong than missing (high recall, tolerate low precision)**.
   - **Threshold filtering**: only jobs scoring above the threshold go on to resume tailoring + delivery, **applied to in descending score order**.
   - The threshold is user-configurable.
   - The exact scoring/filtering algorithm is **TBD** (LLM / rules / hybrid), but **cost must be controllable** (this runs on a schedule at volume, so it can't burn money).

- Output: a scored job list (flagging which ones are above the threshold).

## 4. Resume Module

- Input: a single job (JD) + the user's bio.
- **Rewrites the résumé for each JD** (not a template fill — a genuine per-job rewrite).
- **Pluggable LLM backend**: supports any LLM API, and also supports invocation through an LLM CLI. (The specific provider is undecided; the architecture must not lock in one.)
- Output: **a tailored cover letter + résumé PDF**.

## 5. Deliver Module

- **Unattended, ask only when blocked**: runs fully automated by default and never interrupts the user; it only stops to ask when it hits a field it can't confidently fill.
- Applies to jobs in the order given by the search module (descending score).
- Delivery actions: uploading résumé attachments + filling out forms. The résumé attachment is the PDF the resume module generated for that specific JD.
- **Detailed requirements have been split into their own document: [docs/deliver-prd.md](docs/deliver-prd.md)** (delivery scope, the technical approach to reading pages and filling forms, field-handling rules, run modes, records and concurrency, open items).

## 6. Not Doing Yet / TBD

- Platform adapters: get one platform working end-to-end first; add the rest later.
- The resume module's specific LLM choice and PDF-generation approach: TBD.
- Delivery tracking (read receipts/replies/interview invites): not doing yet.
- Website, Docker release: after the CLI is working end-to-end.

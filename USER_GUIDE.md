# CAPT Tax Prep — User Guide

**CAPT Taxation: Principles and Compliance — Exam Preparation System**
Offline-first study app for ICAP CAF-2 Taxation (Spring/Autumn 2027 attempts).
No accounts, no internet, no AI — everything runs on your own computer.

---

## 1. Install on Windows

1. Unzip the package to a folder you control (e.g. `Documents\CAPT-Tax`).
   The folder contains `run_windows.bat`, `app.py`, `core/`, `ui/`, `data/`,
   `requirements.txt`, and this guide.
2. **Double-click `run_windows.bat`.** That's it — no terminal needed day-to-day.
   - If Python is missing, the launcher installs it automatically via winget.
   - First run creates an isolated environment and installs dependencies
     (needs internet **once** for the install; the app itself is offline after that).
   - Your browser opens automatically at `http://127.0.0.1:8505` when the app is ready.
3. Keep the black launcher window open while you study; closing it stops the app.
   If the app is already running, double-clicking the launcher just opens the browser.

> The app is a Streamlit app on localhost, not a native `.exe`. This is a
> documented trade-off (see BUILD_NOTES.md): it gives the same offline SQLite
> workflow with a proven launcher pattern, and the data format transfers
> directly if a native build is wanted later.

## 2. First launch

- The app creates its local database at `data\app.db` and loads the bundled
  content pack (your teacher's textbook, Volume 1 — income tax, 287 pages).
- The **tax-year context banner** at the top tells you which tax year / syllabus
  the book targets. Textbook rules are **never presented as current law** —
  the Rule Library always shows each rule's verification status.
- If you ever see a **"DEMO"** badge, you're looking at synthetic sample data
  used for development, not the real textbook. The real content pack replaces it.

## 3. The study workflow (the 15 sidebar sections)

**Dashboard** — your daily home: continue studying, today's plan, due flashcards,
weak topics, recent results, syllabus coverage. Start here every session.

**Textbook Library** — the imported book(s), page counts, pages flagged for
manual review. Import another textbook here: upload a PDF/DOCX/TXT → the app
extracts text and suggests chapters → **you review and correct** chapter
boundaries, topics and failed pages → Confirm. Nothing is ever silently
discarded; failed pages stay flagged. Scanned pages need the optional
`rapidocr_onnxruntime` package; without it they're flagged, not guessed.

**Syllabus** — Subject → Chapter → Topic tree. Select a topic to edit its
learning objectives; rename/reorder/move/merge topics (every correction is
logged with old/new values); derive topics from chapter parts; optionally paste
the official ICAP syllabus text to keyword-map it against your chapters —
discrepancies are shown, never auto-resolved.

**Learn** — the per-topic workspace with five tabs:
- *Learn*: textbook wording (shown verbatim, quoted), your notes, bookmarks,
  "mark for revision", and **View source page** — the real rendered PDF page.
- *Understand*: concept cards (concept, simple explanation, why it matters,
  conditions, exceptions, example, self-check). Draft cards the app suggests are
  clearly labelled **DRAFT — needs your review**; gaps are flagged, never invented.
- *Memorise*: flashcard review for the topic.
- *Practise*: the topic's questions, attempted inline.
- *Revise*: an auto-built revision sheet — definitions, rules, exceptions,
  formulas, examiner pitfalls, questions you previously missed, source links. Grounded in imported
  content only.

**Chapter Maps** — 🗺 one mind map per chapter, built from the book's own
slide titles, topic labels, definitions and practice questions (every branch
shows its page number). Each chapter also gets:
- an **importance tier** — ★★★ Essential, ★★ High-yield, ★ Core, ○ Foundation —
  computed from the book's practice-question distribution and chapter sizes
  (formula shown in the app; these are study guidance, *not* ICAP's official
  weightage). You can override any tier manually.
- a **suggested study format** — 🧠 mind map, 🧮 computation flow, 🗂 checklist
  or 🃏 flashcards-first — whichever suits that chapter's nature, with the
  reason stated.
- **topics ranked by importance**, so you see which part of the chapter
  deserves the most time.
Use it to plan *what* to study; then jump straight into Flashcards, the
Question Bank or Learn from the buttons on the page.

**Flashcards** — SM-2 spaced repetition: Again / Hard / Good / Easy, due cards
first, difficult-only filter, generate cards from any chapter/topic (definitions
and formulas become cards automatically). **🗺 Map drill** reviews the
flashcards generated from chapter mind maps (definition, topic-recall and
question-pointer cards) — generate them from any chapter here or from the
"Create flashcards from this map" button in Chapter Maps.

**Question Bank** — filter by chapter, topic, type (MCQ, true/false, short,
theory, numerical, scenario, long-form), difficulty, unattempted, incorrect-only,
due-for-revision, source section. Objective questions are marked exactly;
numerical questions accept a tolerance and alternative valid answers; theory
questions use a rubric **self-assessment** (the app never invents a score).
Questions without a verified answer say so — you may add your own solution,
labelled as student origin. From any question, **🧭 Open answer approach**
jumps to that chapter's guided exam workflow.

**Answer Approaches** — 🧭 one guided exam workflow per chapter: a deterministic
step checklist for attempting questions (read the requirement → classify →
apply the chapter's own branches in order → present in the computation format).
Steps may link to that chapter's rules, definitions and questions already in
the app. Workflows are **suggested exam technique, not tax law** — verify
against the book. Start a *walkthrough session* to tick off steps as you
attempt a question (progress is saved); edit, add or delete steps freely —
every edit is logged.

**Calculation Practice** — worked examples in three modes: *Guided* (step-by-step
reveal), *Complete-it* (fill in hidden steps), *Solve independently* (reveal
after you submit). Numeric steps like `a × b = c` are re-verified by real
arithmetic; mismatches are flagged as "check this step". Assumptions are shown,
never silently changed.

**Mock Examinations** — build timed or untimed tests: topic-based, mixed, or a
custom blueprint (chapters, question types, difficulty, count, time limit,
previously-incorrect / unattempted pools). Answers autosave; timed exams
auto-submit on expiry. Results show totals, marks by chapter/topic, accuracy by
question type, time spent, misses (each linked back to its source page), weak
concepts, and concrete next steps. Mock scores are **not** predictions of your
real exam result.

**Pitfalls** — ⚠️ what the examiners say students keep getting wrong, quoted
verbatim from the examiner commentary printed in your textbook (pp. 7–12);
`[…]` marks a gap in the book's own extraction, never a smoothed-over claim.
Browse by chapter, add your own pitfalls, and turn any pitfall into a
flashcard with one click. Pitfalls also surface automatically in each
chapter's Learn → Revise sheet.

**Tax Rule Library** — rules as **IF / THEN / UNLESS** blocks with conditions,
exceptions, rates/thresholds, evidence required, and source references. Every
rule carries a verification badge: `textbook`, `verified`, `student`, or
`ocr_unverified`. The banner reminds you the tax year of the source; textbook
rules are not current law until verified.

**Revision Planner** — topics ordered weakest-first with the reason shown
(e.g. "recent accuracy 40% over 8 attempts"), due flashcards, missed questions,
and a deterministic revision queue you can override or dismiss.

**Progress Analytics** — the mastery formula is shown in full:
`score = 0.40×recent accuracy + 0.25×flashcard recall + 0.20×calculation
success + 0.15×application success`, with fewer than 3 attempts capping the
score at 40 ("insufficient evidence"). Bands: <45 weak, 45–74 developing,
≥75 strong — each with its reasons. Plus attempts over time, accuracy by
question type, and study time.

**Settings & Backup** — tax-year context text, auto-backup frequency, page-render
DPI, FTS index rebuild, database integrity check, manual backup, restore
(guarded — it refuses to overwrite your only copy), and CSV/Markdown exports of
notes and progress.

## 4. Daily study planner

In **Revision Planner → Planner** (the planner UI): set your exam date
(default **2027-02-06**), study hours per day, study days, and chapter
priorities. The app generates concrete daily sessions ("Review 12 due
flashcards", "Solve 3 calculation questions — Chapter 4", "Topic test — …"),
ordered weak-topics-first. Mark sessions complete/missed/reschedule. No streaks,
no gamification — it's a time-allocation tool.

## 5. Backup & restore

- Your data lives in `data\app.db` (one SQLite file). Automatic progress saving;
  WAL mode; integrity check on startup.
- **Backups** (Settings & Backup): timestamped zips of the database. Turn on
  auto-backup (e.g. every 3 days). Restore always safety-backs-up the current
  database first and refuses to proceed if the backup you're restoring is your
  only copy (unless you explicitly force it).
- Copy the backup zips somewhere safe (USB drive) before a Windows reinstall.

## 6. FAQ

- **Which exam is this for?** ICAP CAF-2 *Taxation: Principles and Compliance*.
  The bundled Volume 1 (Murtaza Quaid, FCA, Spring and Autumn 2027) covers
  income tax; it targets the Spring/Autumn 2027 attempts.
- **Do I need the internet?** Only once, to install dependencies on first run.
  Studying, exams, search, backups — all offline.
- **A question has no solution — is that a bug?** No. The book prints solutions
  for many practice questions but not all. Missing ones are labelled missing;
  you can add your own (marked student origin, never shown as the author's).
- **The app says a definition is "unverified" — what does that mean?** It was
  auto-detected from the text layer. Verify or correct it yourself; until then
  it's never presented as a confirmed fact.
- **Can I add my own questions/rules/cards?** Yes — they're labelled
  student origin and kept separate from imported content.
- **Something looks wrong in the book's text?** The app preserves the book's
  wording verbatim and flags inconsistencies for your review — it never
  silently "corrects" the textbook.

## 7. Limitations (honest list)

- No AI, no network in the core app; no cloud sync — one machine, one database.
- Key bold terms in the source PDF exist only as vector/raster content, so some
  words are OCR-filled, flagged `ocr`, and the rendered PDF page remains the
  source of truth. Page numbers are real and extracted, never invented.
- The real content pack (`data/content_pack.json`) arrives separately; until
  then the app runs on the labelled synthetic DEMO pack.
- Streamlit-on-localhost UI rather than a native desktop app (documented
  trade-off); needs a browser, runs only on your machine.
- Scanned/image PDFs need the optional `rapidocr_onnxruntime` package for OCR;
  without it, image-heavy pages are flagged for manual review.
- Theory marking is rubric self-assessment by design — the app does not pretend
  to grade written answers.
- Mock exam scores measure practice performance; they do not predict ICAP results.

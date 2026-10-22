# CAPT Taxation — Exam Preparation System · Build Notes

## Project
Offline-first desktop exam-prep app for **ICAP CAF-2 Taxation: Principles and
Compliance**, built for Bilal (CAF-2 exam: **Sat 6 Feb 2027**). Transforms his
teacher-compiled textbook — *Murtaza Quaid, FCA, "Taxation: Principles and
Compliance", Volume 1, Spring and Autumn 2027* (287-page slide-deck PDF) — into
a structured learning system.

## Architecture decision (stack trade-off)

**Chosen: Python + Streamlit + SQLite**, shipped as a ZIP with a
`run_windows.bat` launcher (the launcher installs Python via winget when
missing, creates a venv, installs requirements, and opens the app in the
browser — no terminal needed day-to-day).

**Why not the spec's recommended PySide6 + PyInstaller:**
1. This build environment is Linux — PyInstaller cannot produce a Windows
   `.exe` here, and a PySide6 GUI cannot be exercised/tested here at all.
2. Bilal already runs three apps built on the Streamlit+launcher pattern
   (CA Copilot, ICAP case engine, audit-risk library, tax engine); the pattern
   is proven on his machine and consistent across his tools.
3. Streamlit covers every functional requirement (offline, local SQLite, no AI,
   no accounts); the UI runs on localhost only.

The trade-off is documented here and in the user guide. If a native PySide6
build is wanted later, the SQLite schema and content-pack format transfer
directly.

**No AI, no network** in the core app. Optional OCR uses `rapidocr_onnxruntime`
(pip-installable, CPU) for the in-app importer; the shipped content pack is
pre-extracted so OCR is not needed for the bundled book.

## Textbook findings (Phase 1, verified by inspection)

- 287 pages, searchable text layer BUT key terms (bold words like "individual",
  "person", "directorship") exist only as vector/raster content — the text
  layer has gaps exactly where the most examinable words are.
- Hybrid extraction: text layer (primary) + RapidOCR gap-fill. OCR-filled
  content is flagged `ocr` and the rendered PDF page stays the source of truth.
- 14 chapters, printed page numbers == PDF page numbers (verified).
- 114 "Question No." markers across 7 `PRACTICE QUESTIONS - <SECTION>` blocks;
  many sections print the author's **solutions in the book** (captured verbatim).
  Where a solution is absent it is labelled missing — never invented.
- The book's preface also points to an online solution folder (unavailable
  offline) — recorded in the pack's `solutions_note`.
- This is **Volume 1** (income tax). A future Volume 2 can be imported through
  the in-app importer.

## Content-pack contract
`docs/CONTENT_PACK_SCHEMA.md` is binding. `data/sample_pack.json` is synthetic
demo data for development (labelled DEMO everywhere it surfaces).

## Status
- [x] Phase 1: environment + textbook inspection, extraction pipeline
- [x] Phase 2: foundation (DB, importer, nav, search, settings) — 2026-10-21
- [x] Phase 3: learning engine (workspace, flashcards/SM-2, question bank, worked examples) — 2026-10-21
- [x] Phase 4: exam prep (timed exams, marking, analytics, planner) — 2026-10-21
- [x] Phase 5: tests (122 pass), packaging, user guide — 2026-10-21
- [x] Phase 6: real content-pack integration (14 chapters, 131 questions, 14 definitions, 287 pages loaded) — 2026-10-21
- [x] Phase 7: Chapter Maps — per-chapter mind maps, importance tiers, topic ranking, per-chapter study-format suggestions (133 tests pass) — 2026-10-21
- [x] Phase 8: Map Cards + Answer Approaches + Pitfalls; port moved 8504 → 8505 (8504 belongs to the ICAP case-engine app) — 2026-10-21

## Completed vs limitations (updated 2026-10-21; Phase 8 feature pass + installer hotfix)
_Built by five parallel teams against a binding schema contract, integrated and
verified by the build coordinator; Phase 8 (map cards, answer approaches,
pitfalls, port move, first-run pack fix) verified by the feature team. Final
state: `pytest tests/` → **160 passed** (133 + 27 new); the real content pack (`data/content_pack.json`:
14 chapters, 287 pages, 131 questions, 14 definitions) loads via `load_pack`;
13 examiner pitfalls seed from the pack's own commentary (pp. 7–12) and 14
answer-approach workflows seed from the chapters' real topic structure.
Headless boot test → HTTP 200 on port **8505** (moved from 8504, which the ICAP
case-engine app uses), all 15 sections render with no exceptions. Windows ZIP
rebuilt at `~/workspace/capt-tax-windows.zip` (~27.9 MB, 68 files) containing
the real pack plus `run_windows.bat` (port 8505)._

**Installer hotfix (2026-10-21, after Bilal's first launch attempt failed):**
`requirements.txt` pinned `pymupdf==2.0`, whose metadata unconditionally
requires `onnxruntime` (+ networkx, pyyaml, …) — onnxruntime has no wheel for
Bilal's Windows Python, so `pip install` failed. The app only uses pymupdf for
text extraction and page rendering, so the pin was moved to **`pymupdf==1.28.2`**
(zero dependencies, Requires-Python >=3.10, abi3 wheel). Full suite re-run:
160/160 pass. `run_windows.bat` is now self-healing: if a previous dependency
install failed (no `install_ok.txt` marker), it wipes the broken `.venv` and
retries cleanly instead of leaving the user stuck.

### Completed
- **Phase 8 — Map Cards:** `core/mapcards.py` builds SM-2 flashcards from the
  chapter-map trees (definition leaves → term + breadcrumb → full definition;
  group nodes → "recall the key points" → leaf checklist; question leaves →
  pointer into the Question Bank, never a fabricated answer). Idempotent via
  the `map_cards` registry (chapter_id + node path); every card carries a real
  page ref. UI: Flashcards → "Map drill" mode (per-chapter SM-2 review);
  Chapter Maps → "Create flashcards from this map" button with created-count.
- **Phase 8 — Answer Approaches:** `core/approaches.py` seeds one guided exam
  workflow per chapter (14/14), derived from each chapter's real topic
  structure (e.g. Salary follows the book's Sec. 12 branch order; Ch 12 the
  capstone computation flow), each step optionally linked to that chapter's
  real rules/definitions/questions. Labelled "suggested workflow — verify
  against the book"; fully student-editable with every edit logged
  (`approach_edits`); interactive per-walkthrough checklists with persisted
  progress (`approach_sessions`/`approach_checks`). Question Bank →
  "🧭 Open answer approach" jumps to the question's chapter workflow.
- **Phase 8 — Pitfalls:** `pitfalls` table + `core/pitfalls.py`; 13 pitfalls
  seeded ONLY when the book's examiner commentary is detected in the DB
  (sentinel-gated, so another book never gets this book's pitfalls), each a
  verbatim quote from pp. 7–12 with `[…]` marking extraction gaps. UI section
  "Pitfalls": browse by chapter, add your own, one-click "make flashcard"
  (origin='pitfall'), pitfalls auto-surface in Learn → Revise sheets and are
  indexed in FTS search.
- **Foundation (Phase 2):** SQLite schema (WAL, migrations, FKs, integrity
  check), content-pack loader (v1, idempotent, DEMO-aware), 12-section sidebar
  app shell, shared UI helpers, FTS5 index, `requirements.txt` (pinned),
  `run_windows.bat` (winget Python bootstrap → venv → pip install → auto-open
  browser, port 8505).
- **Textbook import (§4):** pdf/docx/txt extraction, chapter-boundary
  suggestions with confidence labels, student review-and-correct UI, failed-page
  flagging (never silently discarded), every correction logged with history,
  optional rapidocr OCR (flagged `ocr`, never silently merged as verified).
- **Syllabus & knowledge map (§5):** Subject→Chapter→Topic tree, topic records
  (objectives, definitions, rules, examples, questions, mistakes,
  revision/mastery status), hierarchy correction (rename/reorder/move/merge,
  derive-from-parts), optional official-syllabus keyword mapping (discrepancies
  shown, never auto-resolved).
- **Learning workspace (§6):** per-topic Learn / Understand / Memorise /
  Practise / Revise tabs; verbatim source quotations distinguished from notes;
  concept cards (drafts labelled, gaps flagged); SM-2 flashcards (Again/Hard/
  Good/Easy, due/difficult filters, auto-generation from definitions/formulas);
  inline question practice; auto revision sheets grounded in imported content.
- **Rule library (§7):** IF/THEN/UNLESS records with verification badges
  (textbook/verified/student/ocr_unverified), tax-year banner, "not current
  law" discipline, student notes, student-added rules.
- **Worked examples (§8):** Guided / Complete-it / Solve-independently modes;
  numeric `a op b = c` steps re-verified by real arithmetic; assumptions shown.
- **Question bank (§9):** full filter set (chapter/topic/type/difficulty/
  unattempted/incorrect/due/source/origin); deterministic numeric variants from
  validated templates via a safe AST evaluator, labelled "generated practice";
  theory items never fabricated.
- **Marking (§10):** exact MCQ/TF, numerical with tolerance + rounding modes +
  alternative answers, theory via rubric self-assessment (no fake scores);
  marking rules visible and editable.
- **Exam mode (§11):** timed/untimed, topic/mixed/blueprint mocks, autosave,
  auto-submit on expiry, review-before-submit, results by chapter/topic/type
  with source-page links, weak concepts, deterministic next steps; mock scores
  explicitly non-predictive.
- **Analytics (§12):** transparent mastery formula shown in the UI
  (0.40 recent accuracy + 0.25 flashcard recall + 0.20 calculation +
  0.15 application; <3 attempts caps at 40), weak/developing/strong bands with
  reasons, dismissable/overridable recommendations.
- **Planner (§13):** exam date default 2027-02-06, hours/day, study days,
  priorities → concrete daily sessions, complete/miss/reschedule, no
  gamification.
- **Dashboard (§14), search (§15), backup (§16):** as specified — FTS5 across
  text/definitions/rules/questions/examples/notes/bookmarks with chapter/topic
  filters and jump-to-source; manual+auto backup with never-overwrite-the-only-
  copy restore guard; CSV/Markdown export.
- **Accuracy rules (§17):** verbatim source text, OCR/unverified flagging, real
  page numbers, missing solutions labelled missing, correction history,
  no invented rates/provisions, DEMO labelling wherever sample data surfaces.
- **Chapter Maps (Phase 7):** per-chapter mind maps rendered as interactive
  collapsible trees (pure inline HTML/CSS, offline); importance tiers
  (★★★ Essential / ★★ High-yield / ★ Core / ○ Foundation) computed from the
  book's own practice-question distribution and chapter sizes with the formula
  shown in the UI — study guidance, not ICAP official weightage; student tier
  overrides; per-chapter suggested study format (mind map / computation flow /
  checklist / flashcards-first) with stated reasons; topics ranked by
  slide-coverage share; deep links into Flashcards, Question Bank and Learn.
  New: `core/studymaps.py` (pure logic), `ui/maps.py`, `chapter_importance`
  table (schema v2 migration), 11 new tests (133 pass total).

### Limitations (honest)
- **Port moved to 8505** (2026-10-21): the app previously used 8504, which
  collides with the ICAP case-engine app. `run_windows.bat`, the user guide
  and all docs now reference 8505; no 8504 reference to this app remains in
  the repo. If Bilal already bookmarked `http://127.0.0.1:8504` for this app,
  the bookmark needs updating.
- The **real content pack** is integrated: `data/content_pack.json`
  (14 chapters, 287 pages, 131 questions, 14 definitions) loads cleanly via
  `load_pack` (verified end-to-end into a scratch DB: chapters, pages,
  slides, questions, definitions, FTS5) and ships in the Windows ZIP, so a
  fresh Windows install starts with Bilal's real book content, not DEMO data.
- **Streamlit-on-localhost**, not a native PySide6/PyInstaller app (documented
  trade-off above); needs a browser; runs on localhost only.
- UI verified **headless only** (AppTest render checks, no exceptions) — no
  visual walkthrough was possible in this Linux environment; Windows runtime
  behaviour (first `run_windows.bat` launch, winget install) is untested.
- Optional OCR (`rapidocr_onnxruntime`) not installed/tested here; only the
  missing-engine path is covered.
- Theory answers are rubric self-assessed by design — the app does not grade
  prose.
- Source PDF page rendering tested against the real `assets/book.pdf`; the
  "View source page" feature requires the PDF to be present next to the app.
- Answer-approach workflows are **exam technique, not tax law** — seeded from
  the chapters' real topic structure but labelled "suggested workflow";
  step→rule/definition/question links are best-effort matches made at seed
  time and should be reviewed.
- Pitfall seed quotes are verbatim from the pack's extraction, which contains
  OCR artefacts; `[…]` marks known gaps, and the rendered PDF page remains
  the source of truth.

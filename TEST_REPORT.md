# CAPT Tax Prep — Test Report

Date: 2026-10-21. Suite run: `python -m pytest tests/ -q` → **122 passed, 0 failed**
(4.5 s). Plus a headless Streamlit boot test (`streamlit.testing.v1.AppTest`):
all 12 sidebar sections render with **no exceptions**.

## Coverage by area (spec §18 mapping)

| Area | Test file(s) | Tests | Result |
|---|---|---|---|
| Pack import (validation, chapters, idempotent reload) | test_pack_load.py | 8 | pass |
| Chapter/topic assignment, hierarchy corrections + history | test_syllabus.py | 15 | pass |
| Source-page traceability (question→pages preserved) | test_pack_load.py | incl. | pass |
| FTS5 search (incl. chapter/topic filters, snippet marks) | test_search.py | 9 | pass |
| Save/restore progress (DB round-trips) | test_backup.py, test_pack_load.py | incl. | pass |
| SM-2 scheduling math (intervals 1→6→prev×EF, ease floor 1.3, again-reset, lapses, due ordering) | test_sr.py | 12 | pass |
| Question selection filters (chapter/type/difficulty/unattempted/incorrect/due/source/origin) | test_exams.py, test_learn_data.py | incl. | pass |
| Numerical marking (tolerance in/out, rounding modes, alt answers) | test_marking.py | 11 | pass |
| Exam timing + scoring (autosave upsert, submit, totals, in-progress recovery) | test_exams.py | 9 | pass |
| Mastery formula (components, renormalisation, 1-attempt cap at 40, bands, empty topic) | test_mastery.py | 7 | pass |
| Study-plan generation (date range, study days, weak-first, reschedule) | test_planner.py | 5 | pass |
| Backup/restore (zip+row, only-copy guard, force restore, CSV/MD export) | test_backup.py | 8 | pass |
| Textbook import pipeline (extract pdf/docx/txt, chapter suggestion, confirm w/ corrections log, failed pages flagged) | test_import.py | 11 | pass |
| PDF page rendering (real 287-page book.pdf, cache hit, missing-file error) | test_pageshot.py | 5 | pass |
| Numeric variants (determinism per seed, constraints, safe-eval rejects malicious input, "generated practice" label) | test_variants.py | 8 | pass |
| Revision sheet assembly (definitions, rules, missed questions) | test_learn_data.py | 4 | pass |

## Degraded / edge cases (spec §18)

- Partially-unreadable doc: pages with thin/empty text layers get `failed=1` and
  appear in the Library's "pages needing review" list — covered in test_import.py.
- Missing source PDF: `pageshot.render_page` raises `FileNotFoundError`; every UI
  "View source page" call catches it and shows a message instead of crashing.
- Question with no verified answer: bank shows "answer not verified"; student can
  add a solution (origin=`student`, logged) — covered in test_learn_data.py.
- Multiple acceptable answers: `alt_answers_json` accepted by the numerical
  marker — covered in test_marking.py.
- App closed mid-session: exam sessions stay `in_progress` and are recoverable
  via `exam_summary`/`list_sessions` — covered in test_exams.py.
- Theory marking: self-assessment rubric stores attempts with `correct=NULL`;
  the app never auto-scores prose — covered in test_marking.py.

## What was NOT tested here

- Visual/manual UI walkthrough on Windows (no live browser in this environment);
  UI modules were exercised via `AppTest` headless runs (render, no exceptions)
  and import checks with real Streamlit 1.66.
- ~~The real content pack was not available at test time~~ — superseded:
  the real pack (`data/content_pack.json`, 131 questions, 287 pages) finished
  extraction after this report and was validated + integrated (see
  "Integration pass: real content pack" below). The tests themselves still run
  against the synthetic DEMO `data/sample_pack.json`, labelled as such.
- `run_windows.bat` was reviewed line-by-line against the proven tax-engine
  template (port changed to 8505) but not executed — it targets Windows.
- Optional OCR path (`rapidocr_onnxruntime`) not installed here; the
  missing-engine error path is tested, the OCR itself is not.

## Notes

- Two transient failure clusters seen during parallel development (workers
  testing before the foundation module landed) resolved themselves once all
  modules were present; the final full-suite run is green.
- One earlier report of the suite "hanging" was not reproduced in the final
  run (122 passed in 4.52 s).

## Integration pass: real content pack (2026-10-21, ~14:36 PKT)

The background extraction of Bilal's 287-page textbook finished (1791 s).
The resulting `data/content_pack.json` (855 KB) was validated and integrated:

- **Pack validity:** valid JSON; 14 chapters, 287 pages, 131 questions,
  14 definitions — matches the extraction log exactly.
- **Page-mapping spot check:** 3 random questions had their `statement` text
  compared against `assets/book.pdf` (printed page == PDF page) with pymupdf —
  all 3 matched the recorded `page_start` pages. (One interim probe mismatch
  was a probe-phrase artefact, not a data error; re-checked with a proper
  phrase, the text is on the recorded page.)
- **`load_pack` into scratch DB:** `core.content_pack.load_pack` run against a
  temp database — landed 14 chapters, 287 pages, 392 slides, 131 questions,
  14 definitions, 392 slide notes; FTS5 rebuilt with 929 rows; one question's
  `statement` confirmed stored verbatim. Active-book row carries the correct
  title/author/edition metadata. Scratch DB was temporary; no existing user
  data touched.
- **Full suite re-run:** `pytest tests/ -q` → **133 passed, 0 failed** (3.38 s).
  (Header above still records the 122-pass run from delivery time; the suite
  grew with the Chapter Maps tests.)
- **Headless boot:** `streamlit run app.py --server.headless true` on port 8505
  returned HTTP 200; server killed after the check.
- **Windows ZIP:** `~/workspace/capt-tax-windows.zip`, 27.9 MB (58 files):
  app.py, core/, ui/, tests/, data/content_pack.json, data/sample_pack.json,
  assets/book.pdf, requirements.txt, run_windows.bat, USER_GUIDE.md,
  BUILD_NOTES.md (no __pycache__/.venv/logs/.tmp).

## Phase 8 feature pass: map cards, answer approaches, pitfalls, port move (2026-10-21)

- **Port fix:** every `8504` reference for this app replaced with `8505`
  (`run_windows.bat` ×5, USER_GUIDE.md, TEST_REPORT.md, BUILD_NOTES.md);
  repo-wide grep confirms zero remaining `8504` references outside the ZIP
  binary. 8504 belongs to the ICAP case-engine app.
- **New tests (23):** `tests/test_mapcards.py` (7: counts match the map tree,
  idempotency, breadcrumb in front/back, every card links to a real page,
  definition cards carry full bodies, question cards point to the bank, SM-2
  review round-trip), `tests/test_approaches.py` (8: demo-book generic seed,
  all 14 chapters seeded on the real pack, per-chapter keyword grounding,
  requirement-first/last steps, edit persistence + edit-log, add/delete step,
  checklist session round-trip, seed idempotency), `tests/test_pitfalls.py`
  (8: no seed without commentary, 13 seeded + idempotent, page refs 7–12,
  browse-by-chapter, student add/delete, flashcard conversion idempotent,
  verbatim spans checked against the real pack, sentinel line-break
  regression test).
- **Accuracy spot checks:** 3 random map cards and 3 random questions checked
  against `assets/book.pdf` — page refs correct (one probe artefact traced to
  an OCR ligature, not a data error). All 13 pitfall quoted spans verified
  verbatim (alphanumeric-normalised) against pack pages 7–12; `[…]` marks the
  one interleaved extraction gap.
- **Seeding on real pack (scratch DB):** approaches 14/14, pitfalls 13/13
  (sentinel-gated), map cards generated for ch03 (37), schema at v3, FTS
  includes pitfalls after rebuild.
- **Full suite:** `pytest tests/ -q` → **160 passed, 0 failed**.
- **Headless boot:** port 8505 → HTTP 200, zero tracebacks; AppTest render of
  Answer Approaches, Pitfalls, Flashcards, Chapter Maps, Question Bank, Learn
  → no exceptions.
- **First-run correctness fix:** `app.py` previously auto-loaded only the DEMO
  pack on a fresh database, ignoring the shipped real `data/content_pack.json`.
  Now `_initial_pack()` prefers the real pack (verified: fresh DB loads
  "Taxation: Principles and Compliance", is_demo=0, 14 chapters, 131
  questions, 14 approaches, 13 pitfalls, pitfalls indexed in FTS, integrity
  check OK). Covered by `tests/test_app_boot.py` (4 tests).

## What was NOT tested here (updated)

- The real content pack is now integrated and covered above, but the app has
  still only been exercised headless on Linux — no visual walkthrough and no
  Windows launch (`run_windows.bat` not executed; it targets Windows).
- Optional OCR path (`rapidocr_onnxruntime`) not installed here; only the
  missing-engine error path is covered.

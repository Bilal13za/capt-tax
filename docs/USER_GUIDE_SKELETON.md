# CAPT Taxation — User Guide (SKELETON — for the docs pass)

> **Status: skeleton.** This file is a section skeleton with 1–2 sentence notes
> per section, written by the syllabus/app-shell team from
> `BUILD_NOTES.md` and `docs/CONTENT_PACK_SCHEMA.md`. The docs team should
> expand each section with screenshots and step-by-step detail during the docs
> pass. Nothing below is final copy.

## Install on Windows

The app ships as a ZIP containing a `run_windows.bat` launcher: on first run it
installs Python itself via winget when missing, creates a virtual environment,
installs requirements, and opens the app in the browser — no terminal needed
day-to-day (per BUILD_NOTES.md, architecture decision).

## First launch

On first launch the app imports the bundled content pack into a local SQLite
database and opens on localhost only; there are no accounts, no network calls
and no AI — everything runs offline on the student's machine.

## Importing your textbook

The bundled book is Volume 1 (*Murtaza Quaid, FCA, "Taxation: Principles and
Compliance", Spring and Autumn 2027*, 287-page slide deck, income tax) and is
pre-extracted, so no OCR is needed for it; a future Volume 2 (or another book)
can be imported through the in-app importer in the Textbook Library section.
Development builds may show a synthetic DEMO pack — it is labelled DEMO
everywhere and is not the real textbook.

## The study workflow section-by-section

Twelve sidebar sections, in order: **Dashboard** (today's position at a glance),
**Textbook Library** (imported books and source pages), **Syllabus**
(Subject → Chapter → Topic tree, topic editing, hierarchy corrections, official
syllabus mapping), **Learn** (study workspace), **Flashcards** (SM-2 review),
**Question Bank** (practice questions from the book — solutions shown verbatim,
missing ones labelled missing, never invented), **Calculation Practice**,
**Mock Examinations** (timed, marked), **Tax Rule Library** (definitions/rules —
auto-detected definitions stay flagged unverified until the student verifies or
corrects them), **Revision Planner**, **Progress Analytics**, and **Settings &
Backup**.

## Backup & restore

All study data lives in one local SQLite database file; the Settings & Backup
section exports and restores it. Back it up before Windows reinstalls or moving
machines — there is no cloud copy.

## FAQ

- *Which exam is this for?* ICAP CAF-2 Taxation: Principles and Compliance;
  the bundled Volume 1 targets the Spring and Autumn 2027 attempts.
- *Do I need the internet?* No — the app is offline-first; only the optional
  OCR step for newly imported PDFs needs its pip package installed once.
- *A question has no solution — is that a bug?* No: the book prints solutions
  for many but not all practice questions; where the author's solution is absent
  the app labels it missing and the student may add their own (marked as
  student origin, never presented as the author's).

## Limitations

No AI and no network in the core app; key bold terms in the source PDF exist
only as vector/raster content, so OCR-filled words are flagged `ocr` and the
rendered PDF page remains the source of truth (page numbers are real and
extracted, never invented). The app is Streamlit-on-localhost rather than a
native desktop app (documented trade-off in BUILD_NOTES.md); printed page
numbers equal PDF page numbers for the bundled book. Unverified definitions are
never presented as confirmed facts, and every manual hierarchy correction is
logged to `import_corrections`.

# CAPT Taxation Exam Prep

Offline-first study app for ICAP **CAF-2 Taxation: Principles and Compliance**
(Spring/Autumn 2027 attempts). No accounts, no internet, no AI — everything
runs on your own computer.

## What it does

- **Content library** — browsable chapters, definitions, and practice questions
  with page references.
- **Chapter maps** — per-chapter mind maps with importance tiers computed
  transparently from the book's own question distribution.
- **Flashcards** — SM-2 spaced repetition, including map-derived cards.
- **Question bank & calculation practice** — practice by chapter and topic.
- **Mock exams** — timed exam simulation.
- **Answer approaches** — guided exam-answer checklists per chapter.
- **Pitfalls & examiner insights** — common mistakes, convertible to flashcards.
- **Revision planner & analytics** — schedule and track revision.

## Run it (Windows)

1. Extract the ZIP into a folder.
2. Double-click **run_windows.bat**. The launcher installs Python itself if
   needed (via winget), sets up an isolated environment, and opens the app at
   http://127.0.0.1:8505.
3. Keep the launcher window open while studying; closing it stops the app.

First run needs internet once (dependency install). Fully offline after that.

## About the content pack

The full content pack (`data/content_pack.json`, extracted from the course
textbook, and `assets/book.pdf`) is **not committed to this repository** for
copyright reasons. The repo ships with `data/sample_pack.json`, a demo pack so
everything runs out of the box.

To use your own textbook content locally: place your extracted
`content_pack.json` in `data/` (replacing the sample) — the app detects it
automatically on next launch. Nothing is uploaded anywhere.

## Developer

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/
```

See `USER_GUIDE.md` for the full user guide and `BUILD_NOTES.md` for design
notes. Deterministic throughout: the app never invents syllabus content.


## Run on any device (in your browser)

The Windows download above is the full offline version. To open this app on
your phone, tablet, or any computer without installing anything, host it free
on **Streamlit Community Cloud**:

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. **New app** → pick this repository (`Bilal13za/capt-tax`), branch `main`,
   main file `app.py`.
3. **Deploy** — after a minute or two you get a link like
   `https://capt-tax.streamlit.app` that works on any device.

Two honest caveats: anything you save in the cloud copy is temporary (it
resets when the app sleeps from inactivity), and the Windows version
remains the full, keep-everything version.

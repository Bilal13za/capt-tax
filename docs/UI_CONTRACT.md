# CAPT Taxation — UI Contract (foundation, v1)

Shared UI helpers live in `core/uihelpers.py`. Every `ui.*` section module
must use them instead of re-implementing equivalent logic. The API below is
**stable** — signatures will not change; new helpers are appended, never
edited in place.

## Navigation contract (`app.py`)

- 12 sidebar sections, each delegating to `ui.<module>.render(conn)`:
  Dashboard → `ui.dashboard` · Textbook Library → `ui.library` ·
  Syllabus → `ui.syllabus` · Learn → `ui.learn` · Flashcards → `ui.flashcards` ·
  Question Bank → `ui.questions` · Calculation Practice → `ui.calc_practice` ·
  Mock Examinations → `ui.exams` · Tax Rule Library → `ui.rules` ·
  Revision Planner → `ui.revision` · Progress Analytics → `ui.analytics` ·
  Settings & Backup → `ui.settings`.
- If a module cannot be imported (or exposes no callable `render`), the app
  shows "Module not yet built — coming soon." and keeps running.
- First run: DB init → integrity check → auto-load `data/sample_pack.json`
  as DEMO (`books.is_demo=1`). Every page shows the DEMO banner while the
  active book is demo, plus the book's `tax_context_note` banner.

## Helpers

### `get_setting(conn, key, default=None)`
Read a `settings` value; returns `default` when absent.

### `set_setting(conn, key, value)`
Insert-or-replace a `settings` value (stored as text; commits).

### `is_demo_book(conn, book_id=None) -> bool`
True when the active book (or the book with the given id) has `is_demo=1`.
Call before rendering any content sourced from the book to decide whether
the DEMO banner applies.

### `demo_banner() -> None`
Renders `st.warning("DEMO data — synthetic, not real tax law")`. Use the
shared text — do not reword it (consistency across sections).

### `chapter_options(conn) -> list[(id, label)]`
`[(chapter_id, "Ch <number> · <title>")]` for the active book's chapters,
ordered by number then title. For selectboxes: `dict(chapter_options(conn))`
maps id → label.

### `topic_options(conn, chapter_id=None) -> list[(id, label)]`
`[(topic_id, name)]`, optionally filtered to one chapter, ordered by
`sort_order` then name.

### `source_ref_line(row) -> str`
Builds a human-readable source line from a content row (sqlite3.Row, dict,
or object with the attributes): e.g. `"p. 12–13 · 12(2)"`, `"p. 5"`,
`"PRACTICE QUESTIONS - PERSON"`. Uses only `page_start`, `page_end`,
`source_ref`, `section` — **never fabricates** page numbers; returns `""`
when nothing is known.

### `show_source_page(page_no, label="View source page", conn=None) -> None`
Expander that renders the real PDF page image (the source of truth).
Never crashes:
- `page_no=None` → "No page number was recorded for this item."
- `core.pageshot` missing → clear "not available yet" message.
- PDF missing → "The source PDF is not present in assets/".
The PDF is resolved from the active book's `source_file` under `assets/`,
falling back to `assets/book.pdf`.

**Contract for `core/pageshot` (importer team):** it must expose
`render_page_image(pdf_path: str, page_no: int, dpi: int = 150)
-> PIL.Image.Image | None`.

### `status_chip(text) -> None`
Small inline status pill (e.g. a definition's verification status). Plain
text only; keep labels short.

## Rules for section modules

1. `render(conn)` is the single entry point; it receives the shared cached
   SQLite connection. Do not open your own connection to `data/app.db`.
2. Never invent tax content or page numbers. Demo data is always bannered.
3. Show verification status (`status`/`verification_status`) wherever imported
   content is displayed; unverified items must never read as confirmed facts.
4. Long DB work belongs behind `@st.cache_data`/`@st.cache_resource`, not in
   `render`'s hot path.

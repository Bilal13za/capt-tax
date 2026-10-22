# CAPT Taxation — Database Contract (foundation, v1)

Authoritative schema owned by `core/db.py`. Table and column names are
**frozen** — other teams code against them; renames require a coordinated
migration. Current `schema_version = 1` (tracked in the `migrations` table).

## Connection (`core/db.get_conn`)

- Path: `data/app.db` relative to the project root (runtime data, never committed).
- Pragmas on every open: `journal_mode=WAL`, `foreign_keys=ON`,
  `synchronous=NORMAL`, `busy_timeout=5000`.
- `row_factory = sqlite3.Row`; `check_same_thread=False` (Streamlit reuse).
- `core/db.init_db(conn)` — idempotent; creates all tables + `migrations` row.
- `core/db.integrity_check(conn)` — runs `PRAGMA integrity_check` and
  `PRAGMA foreign_key_check`; returns `True`, raises `RuntimeError` otherwise.
  Called at every app startup.

## Tables

### books
`id INTEGER PK, title, volume, edition, author, publisher, source_file,
page_count INT, tax_context_note, solutions_note, is_demo INT DEFAULT 0,
created_at` (ISO-8601 UTC). One row per imported textbook. `is_demo=1` marks
synthetic demo content (must be bannered DEMO in the UI). `source_file` is the
idempotency key for pack re-imports.

### chapters
`id TEXT PK` (pack id, e.g. `ch01`), `book_id INT REFERENCES books(id)`,
`number INT`, `title`, `page_start INT`, `page_end INT`, `parts_json` (JSON list
of chapter parts as printed; also materialised as topics, see below).

### topics
`id TEXT PK`, `chapter_id TEXT REFERENCES chapters(id)`, `name`,
`sort_order INT`, `objectives_json DEFAULT '[]'`, `source_ref`.
Two id styles, both deterministic:
- `<chapter_id>::part::<i>` — from the pack chapter's `parts[]` list;
- `<chapter_id>::slide::<slug>` — auto-created from slide footer `topic`
  labels that match no part (case-insensitive). Only created when the label is
  non-empty; empty labels leave `topic_id` NULL (never invented).

### pages
`n INT PK` (printed page number — stored exactly as the pack gives, never
invented), `book_id INT`, `chapter_id TEXT`, `has_slides INT`,
`failed INT DEFAULT 0`, `text_merged TEXT` (pack `text` when present, else the
verbatim concatenation of that page's slide texts).

### slides
`id INTEGER PK`, `page_n INT REFERENCES pages(n)`, `title`, `topic` (raw footer
label), `text`, `sort_order INT` (position on the page).

### items
Generic content cards.
`id INTEGER PK, kind, topic_id TEXT, chapter_id TEXT, title, body,
page_start INT, page_end INT, source_ref, origin, status,
extra_json DEFAULT '{}'`.
- `kind`: `definition|example|concept_card|note|common_mistake|formula`
- `origin`: `imported|sample|student|generated|ocr`
- `status`: `auto_detected_unverified|verified|corrected|flagged`
- Pack `definitions[]` → `kind='definition'` (`title`=term, `body`=definition,
  `source_ref`=section_ref, `extra_json={"pack_id": ...}`, status/origin from
  the pack). Pack slides → `kind='note'` (`title`=slide title, `body`=slide
  text, status='verified', origin='imported' or 'sample' for demo packs).

### tax_rules
`id INTEGER PK, rule_code, title, category, explanation,
conditions_json DEFAULT '[]', tax_year, taxpayer_category, rate_or_threshold,
calc_method, exceptions_json DEFAULT '[]', exclusions_json DEFAULT '[]',
evidence_required, source_ref, page_start INT, page_end INT,
verification_status, student_notes, origin, chapter_id TEXT`.
- `verification_status`: `textbook|verified|student|ocr_unverified`

### questions
`id TEXT PK` (pack id, e.g. `q0001`), `book_id INT`, `chapter_id TEXT`,
`topic_id TEXT`, `number TEXT`, `section TEXT`, `statement TEXT`,
`solution TEXT`, `has_solution INT`, `page_start INT`, `page_end INT`,
`origin`, `verified_answer INT`, `answer_note TEXT`, `qtype TEXT`,
`difficulty TEXT`, `marks REAL`, `suggested_minutes REAL`,
`rubric_json DEFAULT '[]'`, `numeric_answer REAL`, `numeric_tolerance REAL`,
`rounding TEXT`, `mcq_options_json DEFAULT '[]'`, `mcq_answer TEXT`,
`alt_answers_json DEFAULT '[]'`.
- `qtype`: `mcq|tf|short|theory|numerical|scenario|long` — taken from the
  pack's `question_type`/`qtype`, defaulting to `theory`.
- `origin`: `imported|sample|student|generated`; `difficulty`: `easy|medium|hard`.
- Page traceability: `page_start`/`page_end` stored exactly as the pack gives.
- Student-authored rows (`origin='student'`) are **never** deleted by a pack
  re-import.

### question_variants
`id INTEGER PK, question_id TEXT REFERENCES questions(id), variant_json,
answer_json, label, created_at`.

### flashcards
`id INTEGER PK, item_id INT, question_text, answer_text, chapter_id TEXT,
topic_id TEXT, source_ref, origin, deck_tag, created_at`.

### sr_reviews (SM-2 state)
`id INTEGER PK, card_id INT REFERENCES flashcards(id), ease REAL DEFAULT 2.5,
interval INT DEFAULT 0, reps INT DEFAULT 0, lapses INT DEFAULT 0, next_due,
last_reviewed, last_rating`.

### attempts
`id INTEGER PK, question_id TEXT, variant_id INT, flashcard_id INT, kind,
qtype, correct INT, marks_obtained REAL, marks_max REAL, time_seconds INT,
confidence INT, mistakes_json DEFAULT '[]', exam_session_id INT, created_at`.

### exam_sessions
`id INTEGER PK, title, mode, blueprint_json DEFAULT '{}', starts_at, ends_at,
submitted_at, total_marks REAL, obtained REAL, status`.

### exam_answers
`id INTEGER PK, session_id INT REFERENCES exam_sessions(id),
question_id TEXT, variant_id INT, answer_json, correct INT,
marks_obtained REAL, time_seconds INT, created_at`.

### study_plans
`id INTEGER PK, name, exam_date, hours_per_day REAL,
study_days_json DEFAULT '[]', priorities_json DEFAULT '{}', created_at,
active INT DEFAULT 1`.

### plan_items
`id INTEGER PK, plan_id INT REFERENCES study_plans(id), day_date, activity,
detail_json DEFAULT '{}', status DEFAULT 'pending', created_at`.

### study_sessions
`id INTEGER PK, plan_item_id INT, started_at, ends_at, activity, notes`.

### notes
`id INTEGER PK, target_kind, target_id TEXT, body, created_at, updated_at`.
Soft references (`target_kind`/`target_id`); never cascade-deleted.

### bookmarks
`id INTEGER PK, target_kind, target_id TEXT, created_at`.

### import_corrections
`id INTEGER PK, target_kind, target_id TEXT, field, old_value, new_value,
created_at`. History of student corrections to imported content.

### settings
`key TEXT PK, value TEXT`. Key `active_book_id` selects the active book
(written by `load_pack`; read by `get_active_book`).

### backups
`id INTEGER PK, filename, created_at, note`.

## Full-text search

`fts_content` — FTS5 virtual table:
`(kind, ref_id, title, body, chapter_id, topic_id, tokenize='porter')`.
`kind` ∈ `slide|question|item|tax_rule|note`; `ref_id` is the row id as text.
No triggers — `core/db.rebuild_fts(conn)` rebuilds the index from
slides/questions/items/tax_rules/notes and returns the row count; it is called
automatically after `init_db` and after every `load_pack`. Source tables that
do not exist are skipped.

## Pack import (`core/content_pack`)

- `load_pack(conn, pack_path, is_demo=False) -> int` (book id). Validates
  `pack_format == 1` (else `ValueError`). Idempotent per `book.source_file`:
  re-importing replaces that book's *imported* content
  (delete-then-insert in one transaction); student-authored rows
  (`origin='student'`, notes, bookmarks, attempts, plans) are preserved.
  Sets `settings.active_book_id` and rebuilds FTS.
- `get_active_book(conn) -> sqlite3.Row | None` — `active_book_id` setting
  when valid, else the newest book.

## Accuracy rules enforced by the foundation

1. Page numbers stored exactly as the pack gives — never invented.
2. `statement`/`solution`/`definition` text stored verbatim.
3. Missing solutions stay missing (`has_solution=0`).
4. Slide `topic_id` is only set when a label exists (matched or auto-created);
   otherwise NULL.

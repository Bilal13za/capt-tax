"""CAPT Taxation — SQLite schema, connection handling, migrations, FTS.

This module owns the database contract documented in docs/DB_CONTRACT.md.
Other teams code against the tables created here; table/column names are
frozen. Runtime data lives at data/app.db (relative to the project root) and
is never committed.

Public API:
    get_conn(path)        -> sqlite3.Connection (WAL mode, FK on, Row factory)
    init_db(conn)         -> creates all tables / migrations row if missing
    integrity_check(conn) -> True; raises RuntimeError on any corruption
    rebuild_fts(conn)     -> rebuilds the fts_content FTS5 index from content
    SCHEMA_VERSION        -> current schema version (int)
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 3

_PRAGMAS = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("busy_timeout", "5000"),
    ("foreign_keys", "ON"),
)


def get_conn(path) -> sqlite3.Connection:
    """Open (creating if needed) the app database at *path*.

    Applies WAL mode, foreign-key enforcement, NORMAL synchronous mode and a
    5s busy timeout. Rows are returned as sqlite3.Row. check_same_thread is
    disabled because Streamlit may touch the cached connection from
    different threads (single-user local app).
    """
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for name, value in _PRAGMAS:
        conn.execute(f"PRAGMA {name}={value}")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create every table (and the FTS index) if the schema is not yet at
    SCHEMA_VERSION. Safe to call on every startup; idempotent."""
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS migrations(schema_version INTEGER NOT NULL)"
    )
    row = cur.execute("SELECT MAX(schema_version) AS v FROM migrations").fetchone()
    current = row["v"] or 0
    if current < 1:
        _create_schema_v1(cur)
        cur.execute("INSERT INTO migrations(schema_version) VALUES (1)")
        conn.commit()
    # Future versions: apply incremental migrations here.
    if current < 2:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS chapter_importance(
                chapter_id TEXT PRIMARY KEY REFERENCES chapters(id),
                tier TEXT NOT NULL,
                score REAL NOT NULL,
                question_count INT NOT NULL,
                page_count INT NOT NULL,
                rationale TEXT,
                is_override INT NOT NULL DEFAULT 0,
                updated_at TEXT
            )"""
        )
        cur.execute("INSERT INTO migrations(schema_version) VALUES (2)")
        conn.commit()
    if current < 3:
        _create_schema_v3(cur)
        cur.execute("INSERT INTO migrations(schema_version) VALUES (3)")
        conn.commit()
    rebuild_fts(conn)


def _create_schema_v3(cur: sqlite3.Cursor) -> None:
    """Mind-map flashcards, answer approaches, pitfalls (feature set, 2026-10-21)."""
    # -- map_cards: idempotency registry for flashcards generated from maps --
    cur.execute(
        """CREATE TABLE IF NOT EXISTS map_cards(
            chapter_id TEXT,
            node_path TEXT,
            card_id INTEGER REFERENCES flashcards(id),
            created_at TEXT,
            PRIMARY KEY (chapter_id, node_path)
        )"""
    )
    # -- approaches: per-chapter guided exam workflows -----------------------
    cur.execute(
        """CREATE TABLE IF NOT EXISTS approaches(
            id INTEGER PRIMARY KEY,
            chapter_id TEXT UNIQUE REFERENCES chapters(id),
            title TEXT,
            intro TEXT,
            origin TEXT DEFAULT 'seeded',
            updated_at TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS approach_steps(
            id INTEGER PRIMARY KEY,
            approach_id INTEGER REFERENCES approaches(id) ON DELETE CASCADE,
            step_no INTEGER,
            title TEXT,
            detail TEXT,
            link_kind TEXT,
            link_ref TEXT,
            sort_order INTEGER
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS approach_sessions(
            id INTEGER PRIMARY KEY,
            approach_id INTEGER REFERENCES approaches(id) ON DELETE CASCADE,
            label TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS approach_checks(
            id INTEGER PRIMARY KEY,
            session_id INTEGER REFERENCES approach_sessions(id) ON DELETE CASCADE,
            step_id INTEGER REFERENCES approach_steps(id) ON DELETE CASCADE,
            done INTEGER DEFAULT 0,
            updated_at TEXT,
            UNIQUE (session_id, step_id)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS approach_edits(
            id INTEGER PRIMARY KEY,
            approach_id INTEGER,
            step_id INTEGER,
            field TEXT,
            old_value TEXT,
            new_value TEXT,
            created_at TEXT
        )"""
    )
    # -- pitfalls: examiner insights + student mistakes ----------------------
    cur.execute(
        """CREATE TABLE IF NOT EXISTS pitfalls(
            id INTEGER PRIMARY KEY,
            chapter_id TEXT REFERENCES chapters(id),
            topic TEXT,
            title TEXT,
            observation TEXT,
            page INTEGER,
            source TEXT,
            status TEXT,
            created_at TEXT
        )"""
    )
    cur.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_mapcards_chapter ON map_cards(chapter_id);
        CREATE INDEX IF NOT EXISTS idx_approaches_chapter ON approaches(chapter_id);
        CREATE INDEX IF NOT EXISTS idx_asteps_approach ON approach_steps(approach_id);
        CREATE INDEX IF NOT EXISTS idx_asessions_approach ON approach_sessions(approach_id);
        CREATE INDEX IF NOT EXISTS idx_achecks_session ON approach_checks(session_id);
        CREATE INDEX IF NOT EXISTS idx_pitfalls_chapter ON pitfalls(chapter_id);
        """
    )


def integrity_check(conn: sqlite3.Connection) -> bool:
    """Run PRAGMA integrity_check + foreign_key_check.

    Returns True when the database is healthy; raises RuntimeError with the
    reported messages otherwise. Called at app startup.
    """
    msgs = [
        r[0]
        for r in conn.execute("PRAGMA integrity_check").fetchall()
        if str(r[0]).lower() != "ok"
    ]
    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_violations:
        msgs.append(
            "foreign_key_check: %d violation(s)" % len(fk_violations)
        )
    if msgs:
        raise RuntimeError("SQLite integrity check failed: " + "; ".join(msgs))
    return True


def _create_schema_v1(cur: sqlite3.Cursor) -> None:
    # -- books ------------------------------------------------------------
    cur.execute(
        """CREATE TABLE books(
            id INTEGER PRIMARY KEY,
            title TEXT,
            volume TEXT,
            edition TEXT,
            author TEXT,
            publisher TEXT,
            source_file TEXT,
            page_count INT,
            tax_context_note TEXT,
            solutions_note TEXT,
            is_demo INT DEFAULT 0,
            created_at TEXT
        )"""
    )
    # -- chapters ---------------------------------------------------------
    cur.execute(
        """CREATE TABLE chapters(
            id TEXT PRIMARY KEY,
            book_id INT REFERENCES books(id),
            number INT,
            title TEXT,
            page_start INT,
            page_end INT,
            parts_json TEXT
        )"""
    )
    # -- topics -----------------------------------------------------------
    cur.execute(
        """CREATE TABLE topics(
            id TEXT PRIMARY KEY,
            chapter_id TEXT REFERENCES chapters(id),
            name TEXT,
            sort_order INT,
            objectives_json TEXT DEFAULT '[]',
            source_ref TEXT
        )"""
    )
    # -- pages ------------------------------------------------------------
    cur.execute(
        """CREATE TABLE pages(
            n INT PRIMARY KEY,
            book_id INT,
            chapter_id TEXT,
            has_slides INT,
            failed INT DEFAULT 0,
            text_merged TEXT
        )"""
    )
    # -- slides -----------------------------------------------------------
    cur.execute(
        """CREATE TABLE slides(
            id INTEGER PRIMARY KEY,
            page_n INT REFERENCES pages(n),
            title TEXT,
            topic TEXT,
            text TEXT,
            sort_order INT
        )"""
    )
    # -- items ------------------------------------------------------------
    # kind: definition|example|concept_card|note|common_mistake|formula
    # origin: imported|sample|student|generated|ocr
    # status: auto_detected_unverified|verified|corrected|flagged
    cur.execute(
        """CREATE TABLE items(
            id INTEGER PRIMARY KEY,
            kind TEXT,
            topic_id TEXT,
            chapter_id TEXT,
            title TEXT,
            body TEXT,
            page_start INT,
            page_end INT,
            source_ref TEXT,
            origin TEXT,
            status TEXT,
            extra_json TEXT DEFAULT '{}'
        )"""
    )
    # -- tax_rules --------------------------------------------------------
    # verification_status: textbook|verified|student|ocr_unverified
    cur.execute(
        """CREATE TABLE tax_rules(
            id INTEGER PRIMARY KEY,
            rule_code TEXT,
            title TEXT,
            category TEXT,
            explanation TEXT,
            conditions_json TEXT DEFAULT '[]',
            tax_year TEXT,
            taxpayer_category TEXT,
            rate_or_threshold TEXT,
            calc_method TEXT,
            exceptions_json TEXT DEFAULT '[]',
            exclusions_json TEXT DEFAULT '[]',
            evidence_required TEXT,
            source_ref TEXT,
            page_start INT,
            page_end INT,
            verification_status TEXT,
            student_notes TEXT,
            origin TEXT,
            chapter_id TEXT
        )"""
    )
    # -- questions --------------------------------------------------------
    # qtype: mcq|tf|short|theory|numerical|scenario|long
    # origin: imported|sample|student|generated
    # difficulty: easy|medium|hard
    cur.execute(
        """CREATE TABLE questions(
            id TEXT PRIMARY KEY,
            book_id INT,
            chapter_id TEXT,
            topic_id TEXT,
            number TEXT,
            section TEXT,
            statement TEXT,
            solution TEXT,
            has_solution INT,
            page_start INT,
            page_end INT,
            origin TEXT,
            verified_answer INT,
            answer_note TEXT,
            qtype TEXT,
            difficulty TEXT,
            marks REAL,
            suggested_minutes REAL,
            rubric_json TEXT DEFAULT '[]',
            numeric_answer REAL,
            numeric_tolerance REAL,
            rounding TEXT,
            mcq_options_json TEXT DEFAULT '[]',
            mcq_answer TEXT,
            alt_answers_json TEXT DEFAULT '[]'
        )"""
    )
    # -- question_variants -------------------------------------------------
    cur.execute(
        """CREATE TABLE question_variants(
            id INTEGER PRIMARY KEY,
            question_id TEXT REFERENCES questions(id),
            variant_json TEXT,
            answer_json TEXT,
            label TEXT,
            created_at TEXT
        )"""
    )
    # -- flashcards --------------------------------------------------------
    cur.execute(
        """CREATE TABLE flashcards(
            id INTEGER PRIMARY KEY,
            item_id INT,
            question_text TEXT,
            answer_text TEXT,
            chapter_id TEXT,
            topic_id TEXT,
            source_ref TEXT,
            origin TEXT,
            deck_tag TEXT,
            created_at TEXT
        )"""
    )
    # -- sr_reviews (SM-2 state) -------------------------------------------
    cur.execute(
        """CREATE TABLE sr_reviews(
            id INTEGER PRIMARY KEY,
            card_id INT REFERENCES flashcards(id),
            ease REAL DEFAULT 2.5,
            interval INT DEFAULT 0,
            reps INT DEFAULT 0,
            lapses INT DEFAULT 0,
            next_due TEXT,
            last_reviewed TEXT,
            last_rating TEXT
        )"""
    )
    # -- attempts ----------------------------------------------------------
    cur.execute(
        """CREATE TABLE attempts(
            id INTEGER PRIMARY KEY,
            question_id TEXT,
            variant_id INT,
            flashcard_id INT,
            kind TEXT,
            qtype TEXT,
            correct INT,
            marks_obtained REAL,
            marks_max REAL,
            time_seconds INT,
            confidence INT,
            mistakes_json TEXT DEFAULT '[]',
            exam_session_id INT,
            created_at TEXT
        )"""
    )
    # -- exam_sessions ------------------------------------------------------
    cur.execute(
        """CREATE TABLE exam_sessions(
            id INTEGER PRIMARY KEY,
            title TEXT,
            mode TEXT,
            blueprint_json TEXT DEFAULT '{}',
            starts_at TEXT,
            ends_at TEXT,
            submitted_at TEXT,
            total_marks REAL,
            obtained REAL,
            status TEXT
        )"""
    )
    # -- exam_answers --------------------------------------------------------
    cur.execute(
        """CREATE TABLE exam_answers(
            id INTEGER PRIMARY KEY,
            session_id INT REFERENCES exam_sessions(id),
            question_id TEXT,
            variant_id INT,
            answer_json TEXT,
            correct INT,
            marks_obtained REAL,
            time_seconds INT,
            created_at TEXT
        )"""
    )
    # -- study_plans ----------------------------------------------------------
    cur.execute(
        """CREATE TABLE study_plans(
            id INTEGER PRIMARY KEY,
            name TEXT,
            exam_date TEXT,
            hours_per_day REAL,
            study_days_json TEXT DEFAULT '[]',
            priorities_json TEXT DEFAULT '{}',
            created_at TEXT,
            active INT DEFAULT 1
        )"""
    )
    # -- plan_items -------------------------------------------------------------
    cur.execute(
        """CREATE TABLE plan_items(
            id INTEGER PRIMARY KEY,
            plan_id INT REFERENCES study_plans(id),
            day_date TEXT,
            activity TEXT,
            detail_json TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )"""
    )
    # -- study_sessions ------------------------------------------------------------
    cur.execute(
        """CREATE TABLE study_sessions(
            id INTEGER PRIMARY KEY,
            plan_item_id INT,
            started_at TEXT,
            ended_at TEXT,
            activity TEXT,
            notes TEXT
        )"""
    )
    # -- notes ------------------------------------------------------------------------
    cur.execute(
        """CREATE TABLE notes(
            id INTEGER PRIMARY KEY,
            target_kind TEXT,
            target_id TEXT,
            body TEXT,
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    # -- bookmarks ----------------------------------------------------------------------
    cur.execute(
        """CREATE TABLE bookmarks(
            id INTEGER PRIMARY KEY,
            target_kind TEXT,
            target_id TEXT,
            created_at TEXT
        )"""
    )
    # -- import_corrections ----------------------------------------------------------------
    cur.execute(
        """CREATE TABLE import_corrections(
            id INTEGER PRIMARY KEY,
            target_kind TEXT,
            target_id TEXT,
            field TEXT,
            old_value TEXT,
            new_value TEXT,
            created_at TEXT
        )"""
    )
    # -- settings ----------------------------------------------------------------------------
    cur.execute(
        """CREATE TABLE settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )"""
    )
    # -- backups -------------------------------------------------------------------------------
    cur.execute(
        """CREATE TABLE backups(
            id INTEGER PRIMARY KEY,
            filename TEXT,
            created_at TEXT,
            note TEXT
        )"""
    )
    # -- FTS5 index ------------------------------------------------------------------------------
    cur.execute(
        """CREATE VIRTUAL TABLE fts_content USING fts5(
            kind, ref_id, title, body, chapter_id, topic_id, tokenize='porter'
        )"""
    )
    _create_indexes(cur)


def _create_indexes(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_chapters_book   ON chapters(book_id);
        CREATE INDEX IF NOT EXISTS idx_topics_chapter  ON topics(chapter_id);
        CREATE INDEX IF NOT EXISTS idx_pages_book      ON pages(book_id);
        CREATE INDEX IF NOT EXISTS idx_slides_page     ON slides(page_n);
        CREATE INDEX IF NOT EXISTS idx_items_chapter   ON items(chapter_id);
        CREATE INDEX IF NOT EXISTS idx_items_topic     ON items(topic_id);
        CREATE INDEX IF NOT EXISTS idx_rules_chapter   ON tax_rules(chapter_id);
        CREATE INDEX IF NOT EXISTS idx_questions_book ON questions(book_id);
        CREATE INDEX IF NOT EXISTS idx_questions_chap ON questions(chapter_id);
        CREATE INDEX IF NOT EXISTS idx_variants_q      ON question_variants(question_id);
        CREATE INDEX IF NOT EXISTS idx_cards_chapter   ON flashcards(chapter_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_card    ON sr_reviews(card_id);
        CREATE INDEX IF NOT EXISTS idx_attempts_q     ON attempts(question_id);
        CREATE INDEX IF NOT EXISTS idx_answers_sess   ON exam_answers(session_id);
        CREATE INDEX IF NOT EXISTS idx_planitems_plan  ON plan_items(plan_id);
        CREATE INDEX IF NOT EXISTS idx_notes_target    ON notes(target_kind, target_id);
        CREATE INDEX IF NOT EXISTS idx_marks_target    ON bookmarks(target_kind, target_id);
        """
    )


def rebuild_fts(conn: sqlite3.Connection) -> int:
    """Rebuild the fts_content FTS5 index from all searchable content.

    Indexes slides, questions, items, tax_rules and notes. ref_id holds the
    row id as text (question ids are already text). Returns the number of
    indexed rows. No triggers are used; call this after any bulk import.

    Source tables that do not exist (e.g. a partial/legacy database) are
    skipped rather than raising, so the rebuild is always safe to run.
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM fts_content")
    total = 0
    total += _fts_from(cur, "slide", "slides",
                      "SELECT id, title, text, NULL, NULL FROM slides")
    total += _fts_from(cur, "question", "questions",
                      "SELECT id, number, statement, chapter_id, topic_id FROM questions")
    total += _fts_from(cur, "item", "items",
                      "SELECT id, title, body, chapter_id, topic_id FROM items")
    total += _fts_from(cur, "tax_rule", "tax_rules",
                      "SELECT id, title, explanation, chapter_id, NULL FROM tax_rules")
    total += _fts_from(cur, "pitfall", "pitfalls",
                      "SELECT id, title, observation, chapter_id, NULL FROM pitfalls")
    total += _fts_from(cur, "note", "notes",
                      "SELECT id, target_kind, body, NULL, NULL FROM notes")
    conn.commit()
    return total


def _fts_from(cur: sqlite3.Cursor, kind: str, ref_kind: str, sql: str) -> int:
    try:
        rows = cur.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return 0  # source table missing: skip it
    for r in rows:
        cur.execute(
            "INSERT INTO fts_content(kind, ref_id, title, body, chapter_id, topic_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (kind, str(r[0]), r[1] or "", r[2] or "", r[3], r[4]),
        )
    return len(rows)

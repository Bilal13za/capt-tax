# Content Pack Schema (v1)

A content pack is a single JSON file that carries everything extracted from one
textbook into the app. The app imports it on first launch (and on demand) into
SQLite. Packs are produced by `tools/extract_pack.py` (real book) or authored by
hand (synthetic demo packs — always labelled).

## Top-level

```json
{
  "pack_format": 1,
  "book": {
    "title": "Taxation: Principles and Compliance",
    "volume": "VOLUME 1",
    "edition": "Spring and Autumn 2027",
    "author": "Murtaza Quaid, FCA",
    "publisher": "IQ School of Finance",
    "source_file": "CAF_2_-_Volume_1_-_Spring_2027__MQ__0_uwth.pdf",
    "page_count": 287,
    "tax_context_note": "free text: which tax year / syllabus the book targets",
    "solutions_note": "free text: where solutions live"
  },
  "extraction": {
    "method": "how text was obtained",
    "ocr_engine": "engine name or 'none'",
    "ocr_dpi": 150,
    "date": "2026-10-21",
    "caveats": ["list of known limitations"]
  },
  "chapters":   [ ... ],
  "pages":      [ ... ],
  "questions":  [ ... ],
  "definitions":[ ... ]
}
```

## chapters[]

| field | meaning |
|---|---|
| `id` | stable id, e.g. `ch03` |
| `number` | chapter number as printed |
| `title` | chapter title as printed |
| `page_start`, `page_end` | printed page numbers (== PDF page numbers for this book) |
| `parts` | topic list from the chapter's "In this Part" slide (may be empty) |

## pages[]

| field | meaning |
|---|---|
| `n` | printed page number |
| `chapter_id` | FK into chapters (null for front matter) |
| `has_slides` | true when the page is slide-deck layout |
| `slides` | list of `{title, topic, text}`; `topic` is the slide footer label (best effort, may be "") |
| `failed` | true if extraction failed for this page (app must flag for manual review) |

`text` is the merged text-layer + OCR text. OCR-filled words are searchable.
The app must always offer "View source page" which renders the real PDF page.

## questions[]

| field | meaning |
|---|---|
| `id` | `q0001`… |
| `chapter_id` | FK (may be null) |
| `number` | question number as printed ("1", "2"…) |
| `section` | practice-section header, e.g. `PRACTICE QUESTIONS - PERSON` |
| `statement` | question text (verbatim from book) |
| `solution` | author's printed solution (verbatim; "" when absent) |
| `has_solution` | bool |
| `page_start`, `page_end` | printed pages |
| `origin` | `imported` \| `sample` \| `student` \| `generated` |
| `verified_answer` | true only when the answer comes from the book/teacher |
| `answer_note` | human-readable provenance note |

Rules: never invent a solution. `has_solution=false` → the app marks the
question "answer not verified" and the student may add one (origin=`student`).

## definitions[]

Auto-detected "Term means …" candidates.

| field | meaning |
|---|---|
| `id` | `d0001`… |
| `chapter_id`, `term`, `definition` | as extracted |
| `page` | printed page |
| `section_ref` | e.g. `12(2)` when found nearby |
| `status` | `auto_detected_unverified` \| `verified` \| `corrected` |
| `origin` | `imported` \| `sample` \| `student` |

The app must show `status` and let the student verify/correct each definition.
Unverified definitions must never be presented as confirmed facts.

## Accuracy contract (binds the app, not just the pack)

1. Page numbers are real (extracted), never invented.
2. `statement`/`solution`/`definition` text is verbatim from the source.
3. Anything OCR-derived is flagged; the rendered PDF page is the source of truth.
4. Missing solutions are labelled missing — never auto-completed.
5. Student corrections keep history (`corrected`, previous text retained).

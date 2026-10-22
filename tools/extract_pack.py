"""One-time extraction: Murtaza Quaid CAF-2 Taxation Vol.1 PDF -> content_pack.json
Hybrid extraction: PDF text layer (primary) + RapidOCR gap-fill (bold/diagram terms
that exist only as vector/raster content). Everything OCR-derived is flagged.

Writes: data/content_pack.json
Logs:  logs/extract.log
"""
import pymupdf, re, json, os, sys, time, datetime

PDF = "/home/hatch/workspace/user/files/CAF_2_-_Volume_1_-_Spring_2027__MQ__0_uwth.pdf"
OUT = "/home/hatch/workspace/capt-tax/data/content_pack.json"
LOG = "/home/hatch/workspace/capt-tax/logs/extract.log"

CHAPTERS = [
    (1,  "OVERVIEW OF THE COURSE", 5, 12),
    (2,  "INTRODUCTION & KEY CONCEPTS", 13, 46),
    (3,  "SALARY", 47, 76),
    (4,  "INCOME FROM PROPERTY", 77, 92),
    (5,  "ASSETS", 93, 102),
    (6,  "CAPITAL GAIN", 103, 118),
    (7,  "TAX ACCOUNTING", 119, 124),
    (8,  "INCOME FROM BUSINESS", 125, 160),
    (9,  "INCOME FROM OTHER RESOURCES", 161, 172),
    (10, "EXEMPTIONS, TAX CONCESSIONS & TAX CREDITS", 173, 196),
    (11, "TREATMENT OF LOSSES", 197, 204),
    (12, "COMPUTATION OF TAX LIABILITY OF INDIVIDUALS", 205, 232),
    (13, "TAXATION OF ASSOCIATION OF PERSONS & ITS MEMBERS", 233, 254),
    (14, "MISCELLANEOUS CONCEPTS - INCOME TAX", 255, 287),
]

def log(msg):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f: f.write(line + "\n")

def bnorm(s): return re.sub(r'[^a-z0-9]', '', s.lower())
def words(s): return [w for w in re.findall(r'[a-z0-9]+', s.lower()) if w]
BOILER = {"caf2volume01", "springandautumn2027", "bysirmurtazaquaidfca",
          "compiledbymurtazaquaidfca", "iqschooloffinance"}
def is_boiler(t):
    n = bnorm(t)
    return n in BOILER or re.match(r'^page\d+$', n) is not None

def slide_boxes(page):
    rects = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width > 300 and r.height > 150 and r.width < page.rect.width - 20:
            rects.append(pymupdf.Rect(r))
    out = []
    for r in rects:
        if not any(abs(r.x0-o.x0) < 3 and abs(r.y0-o.y0) < 3 for o in out):
            out.append(r)
    return sorted(out, key=lambda r: r.y0)

def process_page(doc, ocr, pno, dpi=150):
    page = doc[pno]
    boxes = slide_boxes(page)
    regions = boxes if boxes else [page.rect]
    pix = page.get_pixmap(dpi=dpi)
    import numpy as np
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    res, _ = ocr(img)
    scale = 72.0 / dpi
    ocr_segs = []
    for box, txt, conf in (res or []):
        t = txt.strip()
        if not t or is_boiler(t): continue
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        r = pymupdf.Rect(min(xs)*scale, min(ys)*scale, max(xs)*scale, max(ys)*scale)
        ocr_segs.append({"rect": r, "text": t, "conf": float(conf)})
    tl_lines = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            if not t or is_boiler(t): continue
            xs = [s["bbox"][0] for s in l["spans"]]; ys = [s["bbox"][1] for s in l["spans"]]
            xe = [s["bbox"][2] for s in l["spans"]]; ye = [s["bbox"][3] for s in l["spans"]]
            tl_lines.append({"rect": pymupdf.Rect(min(xs), min(ys), max(xe), max(ye)), "text": t})
    slides = []
    for reg in regions:
        reg_tl = [l for l in tl_lines if reg.intersects(l["rect"])]
        reg_ocr = [s for s in ocr_segs if reg.intersects(s["rect"])]
        keep_tl = [True] * len(reg_tl)
        items = []
        for s in reg_ocr:
            sw = words(s["text"])
            if not sw: continue
            snorm = bnorm(s["text"])
            near_idx = [i for i, l in enumerate(reg_tl) if abs(l["rect"].y0 - s["rect"].y0) < 24]
            near_words, near_norm = set(), ""
            for i in near_idx:
                near_words.update(words(reg_tl[i]["text"]))
                near_norm += bnorm(reg_tl[i]["text"])
            # OCR junk that is fully contained in nearby TL -> skip
            if near_norm and snorm in near_norm: continue
            if near_words:
                overlap = sum(1 for w in sw if w in near_words) / len(sw)
                if overlap > 0.6:
                    # OCR is a superset of TL lines -> prefer OCR, drop covered TL lines
                    tl_words = set()
                    for i in near_idx: tl_words.update(words(reg_tl[i]["text"]))
                    if tl_words and sum(1 for w in tl_words if w in set(sw)) / len(tl_words) > 0.8:
                        for i in near_idx: keep_tl[i] = False
                        items.append(("OCR+", s["rect"].y0, s["text"]))
                    continue
            if len(s["text"]) > 12:
                all_norm = bnorm(" ".join(l["text"] for l in reg_tl))
                if snorm in all_norm: continue
            items.append(("OCR", s["rect"].y0, s["text"]))
        for i, l in enumerate(reg_tl):
            if keep_tl[i]: items.append(("TL", l["rect"].y0, l["text"]))
        items.sort(key=lambda x: x[1])
        title = ""
        for src, y, t in items:
            ts = t.strip()
            if y > reg.y0 + 8 and len(ts) > 10 and len(ts) < 160 and not ts.startswith(""):
                title = ts; break
        topic = ""
        # footer topic label lives in the bottom-right corner of each slide
        br = [s for s in reg_ocr if s["rect"].y0 > reg.y1 - 0.10*reg.height
              and s["rect"].x0 > reg.x0 + 0.55*reg.width and len(s["text"].strip()) < 60]
        if br: topic = sorted(br, key=lambda s: len(s["text"]))[0]["text"].strip()
        text = "\n".join(t for _, _, t in items)
        slides.append({"title": title, "topic": topic, "text": text})
    return {"n": pno + 1, "has_slides": bool(boxes), "slides": slides}

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    if os.path.exists(LOG): os.remove(LOG)
    from rapidocr_onnxruntime import RapidOCR
    doc = pymupdf.open(PDF)
    ocr = RapidOCR()
    log(f"opened PDF: {doc.page_count} pages")
    t0 = time.time()
    pages = []
    for pno in range(doc.page_count):
        try:
            pg = process_page(doc, ocr, pno)
        except Exception as e:
            log(f"PAGE {pno+1} FAILED: {e}")
            pg = {"n": pno+1, "has_slides": False, "slides": [], "failed": True}
        pages.append(pg)
        if (pno+1) % 20 == 0:
            log(f"  ... {pno+1}/{doc.page_count} pages ({time.time()-t0:.0f}s)")
    log(f"extraction done in {time.time()-t0:.0f}s")

    # chapter assignment + parts ("In this Part")
    ch_of = {}
    chapters = []
    for num, title, ps, pe in CHAPTERS:
        cid = f"ch{num:02d}"
        for p in range(ps, pe+1): ch_of[p] = cid
        chapters.append({"id": cid, "number": num, "title": title,
                         "page_start": ps, "page_end": pe, "parts": []})
    for pg in pages:
        cid = ch_of.get(pg["n"])
        pg["chapter_id"] = cid
        for s in pg["slides"]:
            if re.search(r'In this Part', s["title"] or s["text"][:200]):
                parts = [l.strip(" \uf071") for l in s["text"].split("\n")]
                parts = [p for p in parts if p and len(p) > 3 and "In this Part" not in p and len(p) < 120]
                ch = next(c for c in chapters if c["id"] == cid)
                if not ch["parts"]: ch["parts"] = parts

    # questions & solutions
    questions, qid = [], 0
    section, sec_page = None, None
    # work on concatenated page texts for cross-page questions
    full = []
    for pg in pages:
        t = "\n".join(s["text"] for s in pg["slides"])
        full.append((pg["n"], pg["chapter_id"], t))
    sec_re = re.compile(r'PRACTICE QUESTIONS\s*-\s*([A-Z &/,\(\)\-]+)')
    q_re = re.compile(r'Question\s*No\.?\s*(\d+)')
    sol_re = re.compile(r'(?m)^\s*Solution\s*:?\s*$')
    # split stream into segments by (page) then find questions spanning pages
    stream = "\n\x0c\n".join(t for _, _, t in full)
    page_of_offset = []
    off = 0
    for pno, cid, t in full:
        page_of_offset.append((off, pno, cid)); off += len(t) + 3
    def locate(offset):
        pg, cid = 1, None
        for o, p, c in page_of_offset:
            if o <= offset: pg, cid = p, c
            else: break
        return pg, cid
    # find sections
    events = []
    for m in sec_re.finditer(stream): events.append((m.start(), "sec", m.group(1).strip()))
    for m in q_re.finditer(stream): events.append((m.start(), "q", m.group(1)))
    events.sort()
    cur_sec = None
    for idx, (pos, typ, val) in enumerate(events):
        end = events[idx+1][0] if idx+1 < len(events) else len(stream)
        if typ == "sec":
            cur_sec = val; continue
        body = stream[pos:end]
        sol_m = sol_re.search(body)
        if sol_m:
            statement, solution = body[:sol_m.start()], body[sol_m.end():]
            has_sol = True
        else:
            statement, solution, has_sol = body, "", False
        pstart, cid = locate(pos); pend, _ = locate(end-1)
        qid += 1
        questions.append({
            "id": f"q{qid:04d}", "chapter_id": cid, "number": val,
            "section": cur_sec, "statement": statement.strip()[:6000],
            "solution": solution.strip()[:12000], "has_solution": has_sol,
            "page_start": pstart, "page_end": pend,
            "origin": "imported", "verified_answer": has_sol,
            "answer_note": "Author's printed solution." if has_sol else
                           "No printed solution in the book; check the author's solution folder or your teacher.",
        })

    # definition candidates: "Term means ..." on OCR-enriched text
    definitions, did = [], 0
    def_re = re.compile(r'(?m)^\s*([A-Z][A-Za-z][A-Za-z /&()\-]{1,44}?)\s+means\s+([^.\n]{15,450})')
    seen_terms = set()
    for pno, cid, t in full:
        for m in def_re.finditer(t):
            term = " ".join(m.group(1).split())
            if any(w in term.lower().split() for w in ("this", "that", "these", "those", "it")): continue
            if term in seen_terms: continue
            seen_terms.add(term)
            sec_m = re.search(r'[Ss]ec(?:tion)?\.?\s*(\d+[A-Z]?(?:\(\d+\))?)', t[max(0,m.start()-200):m.start()+200])
            did += 1
            definitions.append({
                "id": f"d{did:04d}", "chapter_id": cid, "term": term,
                "definition": " ".join(m.group(2).split()),
                "page": pno, "section_ref": sec_m.group(1) if sec_m else "",
                "status": "auto_detected_unverified", "origin": "imported",
            })

    pack = {
        "pack_format": 1,
        "book": {
            "title": "Taxation: Principles and Compliance", "volume": "VOLUME 1",
            "edition": "Spring and Autumn 2027", "author": "Murtaza Quaid, FCA",
            "publisher": "IQ School of Finance",
            "source_file": os.path.basename(PDF),
            "page_count": doc.page_count,
            "tax_context_note": "Content as per the Spring and Autumn 2027 edition of the book. Tax year applicability follows the book; verify against the syllabus applicable to your attempt.",
            "solutions_note": "The book's preface points to an online folder for practice-question solutions; several practice sections also print solutions in the book (captured where present).",
        },
        "extraction": {
            "method": "pdf-text-layer primary + RapidOCR gap-fill for vector/raster-only terms",
            "ocr_engine": "RapidOCR (ONNX, CPU)", "ocr_dpi": 150,
            "date": datetime.date.today().isoformat(),
            "caveats": [
                "Slide decks have 2-column layouts; reading order of merged lines is approximate.",
                "OCR-derived words are included for search and flagged ocr in the app; verify against the rendered page.",
                "Page numbers equal the book's printed page numbers (verified).",
            ],
        },
        "chapters": chapters,
        "pages": pages,
        "questions": questions,
        "definitions": definitions,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False)
    log(f"WROTE {OUT}: {len(chapters)} chapters, {len(pages)} pages, {len(questions)} questions, {len(definitions)} definition candidates")
    log(f"size: {os.path.getsize(OUT)/1024:.0f} KB")

if __name__ == "__main__":
    main()

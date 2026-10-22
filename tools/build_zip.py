"""Build the Windows distribution ZIP for the CAPT Tax app.

Excludes everything that must never ship (notably *.db — a stray app.db
once caused fresh installs to show only DEMO content). Verifies integrity
and required files afterwards.
"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.expanduser("~/workspace/capt-tax-windows.zip")

SKIP_DIRS = {"__pycache__", ".venv", ".tmp", "logs", ".git", ".pytest_cache"}
SKIP_EXTS = (".pyc", ".db", ".db-wal", ".db-journal", ".db-shm")
SKIP_FILES = {".DS_Store"}

REQUIRED = [
    "app.py", "run_windows.bat", "requirements.txt", "USER_GUIDE.md",
    "BUILD_NOTES.md", "data/content_pack.json", "data/sample_pack.json",
    "assets/book.pdf", "core/db.py", "core/content_pack.py",
]


def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    names = []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f in SKIP_FILES or f.endswith(SKIP_EXTS):
                    continue
                p = os.path.join(root, f)
                arc = os.path.relpath(p, ROOT)
                z.write(p, arc)
                names.append(arc)
    with zipfile.ZipFile(OUT) as z:
        bad = z.testzip()
        if bad is not None:
            print(f"CORRUPT: {bad}")
            return 1
        final = z.namelist()
    missing = [r for r in REQUIRED if r not in final]
    leaked_db = [n for n in final if n.endswith((".db", ".db-wal"))]
    if missing:
        print("MISSING REQUIRED FILES:", missing)
        return 1
    if leaked_db:
        print("LEAKED DATABASE FILES:", leaked_db)
        return 1
    size_mb = os.path.getsize(OUT) / 1024 / 1024
    print(f"OK: {len(final)} files, {size_mb:.1f} MB -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

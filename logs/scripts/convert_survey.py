"""Runs the converter over real documents found under a folder and reports, per file, whether it
converted, how long it took and what structure came out (headings, list items, table rows).
Nothing is written anywhere and no document text is printed: only counts and file names.

    python logs/scripts/convert_survey.py FOLDER [--max 40] [--ext .pdf,.docx,.pptx]
"""
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
from mitra_workers import convert  # noqa: E402


def main():
    args = sys.argv[1:]
    folder = Path(args[0])
    limit = int(args[args.index("--max") + 1]) if "--max" in args else 40
    exts = set(args[args.index("--ext") + 1].split(",")) if "--ext" in args else {".pdf", ".docx", ".pptx", ".rtf", ".odt", ".html", ".epub"}
    per_ext, rows, failed = Counter(), [], []
    for p in folder.rglob("*"):
        ext = p.suffix.lower()
        if ext not in exts or not p.is_file() or per_ext[ext] >= limit or p.stat().st_size > 30 << 20 or p.name.startswith("~$"):
            continue
        per_ext[ext] += 1
        t0 = time.time()
        try:
            md = convert.to_markdown(p)
        except Exception as e:
            failed.append((p.name[:50], f"{type(e).__name__}: {str(e)[:80]}"))
            continue
        lines = md.splitlines()
        heads = Counter(len(m.group(1)) for l in lines if (m := re.match(r"(#{1,6}) ", l)))
        rows.append((ext, p.name[:44], len(md), round(time.time() - t0, 2), dict(sorted(heads.items())),
                     sum(1 for l in lines if re.match(r"\s*(- |\d+\. )", l)), sum(1 for l in lines if l.startswith("|")),
                     "page sections" if any(l.startswith("## Page ") for l in lines) else ""))
    print(f"{'type':<6}{'file':<46}{'chars':>8}{'s':>6}  headings by level / list items / table rows")
    for r in sorted(rows):
        print(f"{r[0]:<6}{r[1]:<46}{r[2]:>8}{r[3]:>6}  {r[4]} / {r[5]} / {r[6]} {r[7]}")
    print(f"\n{len(rows)} converted, {len(failed)} failed")
    for name, why in failed:
        print("  FAILED", name, why)


if __name__ == "__main__":
    main()

"""Take stock of the Meeting Intelligence archive as fine-tuning data. Read-only: opens files,
writes nothing into the archive.

    python logs/scripts/meeting_archive_stock.py ["<archive folder>"]

Reports how many transcripts exist, how many carry a summary or action section that could
serve as a training target, how many are marked with a client, and how long they are.
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path

ARCHIVE = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Dropbox" / "0. AP Persistent AI Brain" / "Meeting Intelligence")
csv.field_size_limit(10**9)

rows = list(csv.DictReader(open(ARCHIVE / "meta" / "manifest.csv", encoding="utf-8-sig", newline="")))
print(f"manifest rows: {len(rows)}   columns: {', '.join(rows[0].keys())}")
for col in ("status", "attribution", "source_added_from"):
    print(f"  {col}: {dict(Counter(r.get(col) or '(blank)' for r in rows).most_common(8))}")
client = Counter("client named" if (r.get("client") or "").strip().lower() not in ("", "null", "none") else "no client" for r in rows)
print(f"  client field: {dict(client)}")
print(f"  years: {dict(sorted(Counter((r.get('date') or 'undated')[:4] for r in rows).items()))}")
print(f"  'notes' column values: {dict(Counter((r.get('notes') or '(blank)')[:30] for r in rows).most_common(8))}")

SECTION = re.compile(r"^#{1,4}\s*(.+?)\s*$", re.M)
TARGET = re.compile(r"summary|action|decision|key point|takeaway|next step|overview|notes", re.I)
SPEAKER = re.compile(r"^\s*(\[?\d{1,2}:\d{2}(:\d{2})?\]?\s*)?[A-Z][\w .'-]{1,30}:\s", re.M)


def profile(folder: str, label: str):
    files = [f for f in (ARCHIVE / folder).rglob("*.md")]
    heads, with_target, with_turns, words, fm_type = Counter(), 0, 0, [], Counter()
    both = 0
    for f in files:
        try:
            text = f.read_text("utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"^type:\s*(\S+)", text[:600], re.M)
        fm_type[m.group(1) if m else "(none)"] += 1
        sections = [s.strip().lower()[:40] for s in SECTION.findall(text)]
        heads.update(set(sections))
        has_target = any(TARGET.search(s) for s in sections)
        turns = len(SPEAKER.findall(text))
        with_target += has_target
        with_turns += turns >= 10
        both += has_target and turns >= 10
        words.append(len(text.split()))
    words.sort()
    n = len(words) or 1
    print(f"\n{label}: {len(files)} files")
    print(f"  front-matter type: {dict(fm_type.most_common(6))}")
    print(f"  with a summary/action/decision heading: {with_target}")
    print(f"  with 10+ speaker turns (a real transcript): {with_turns}")
    print(f"  with BOTH in the same file (transcript + notes paired): {both}")
    print(f"  words per file: median {words[n // 2]}, 90th percentile {words[int(n * 0.9)]}, longest {words[-1]}")
    print(f"  commonest headings: {[h for h, _ in heads.most_common(14)]}")


profile("raw", "raw/")
profile("normalized", "normalized/")

# ---- pairing: which transcripts have a separate notes file for the same meeting? ----------
print(f"\n  kind: {dict(Counter(r.get('kind') or '(blank)' for r in rows).most_common(8))}")


def is_notes(path: Path) -> bool:
    try:
        text = path.read_text("utf-8", errors="replace")
    except OSError:
        return False
    return any(TARGET.search(s) for s in SECTION.findall(text)) and len(SPEAKER.findall(text)) < 10


def key(r):
    title = re.sub(r"^\d{6}\s*[—-]\s*", "", r.get("title") or "")
    return (r.get("date") or "")[:10], re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:40]


transcripts = [r for r in rows if r["status"] == "normalized"]
notes = [r for r in rows if r["status"] == "raw-only" and is_notes(ARCHIVE / r["raw_path"])]
by_id = {r["meeting_id"] for r in notes if r.get("meeting_id")}
by_key = {key(r) for r in notes}
by_date = Counter((r.get("date") or "")[:10] for r in notes)
pair_id = [r for r in transcripts if r.get("meeting_id") in by_id]
pair_key = [r for r in transcripts if key(r) in by_key]
pair_any = {r["hash"] for r in pair_id} | {r["hash"] for r in pair_key}
same_day = [r for r in transcripts if by_date.get((r.get("date") or "")[:10])]
no_client = lambda rs: sum(1 for r in rs if (r.get("client") or "").strip().lower() in ("", "null", "none"))
print(f"\npairing transcripts with a separate notes file:")
print(f"  notes-only files (summary headings, no transcript): {len(notes)}")
print(f"  transcripts paired by meeting_id: {len(pair_id)}")
print(f"  transcripts paired by date + title: {len(pair_key)}")
print(f"  paired either way: {len(pair_any)}   of which no client named: {no_client([r for r in transcripts if r['hash'] in pair_any])}")
print(f"  transcripts with a notes file on the same day (loose upper bound): {len(same_day)}")
print(f"  transcripts with no client named: {no_client(transcripts)} of {len(transcripts)}")

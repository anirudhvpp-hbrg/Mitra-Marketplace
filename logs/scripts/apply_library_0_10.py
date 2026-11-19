"""0.10.0, part 1: the meeting library and the people list in TwinMind's worker.

  - routes: library (list with filters and counts), meeting (transcript and summary of one), meta
    (tags, project), inside (search in the transcripts), people (names that must come out right),
    across (one project or tag over time)
  - names: the people list and the names heard most in the archive are given to the speech model,
    and every known wrong spelling is replaced in the transcript before notes are written
  - a transcript from the archive can be given a summary: its front matter is not read as speech
Run once from the project root: python logs/scripts/apply_library_0_10.py
"""
from pathlib import Path


def patch(path, edits):
    f = Path(path)
    s = f.read_text("utf-8")
    for a, b in edits:
        assert s.count(a) == 1, (path, s.count(a), a[:70])
        s = s.replace(a, b)
    f.write_text(s, "utf-8")


patch("workers/mitra_workers/models.py", [
    ("               info: dict | None = None, _skip: tuple = (), work=None, speed: str = \"accurate\") -> list[dict]:",
     "               info: dict | None = None, _skip: tuple = (), work=None, speed: str = \"accurate\", names: list | None = None) -> list[dict]:"),
    ("                lang_args, _ = transcribe_plan(p)\n                what = f\"what was said, piece {i + 1} of {n_pieces}\"",
     "                lang_args, _ = transcribe_plan(p)\n"
     "                if names:       # the people likely to be named, so the model spells them as they are spelt\n"
     "                    lang_args = lang_args + [\"--prompt\", \"People in this meeting or mentioned in it: \" + \", \".join(names[:40]) + \".\"]\n"
     "                what = f\"what was said, piece {i + 1} of {n_pieces}\""),
])

ROUTES = '''

# ---- the library: every meeting, old and new --------------------------------------------------
def _entries(refresh=True):
    return library.with_meta(library.index(out_dir(), refresh))


def _one(meeting_id):
    e = next((x for x in _entries(False) if x["id"] == meeting_id), None) or next((x for x in _entries(True) if x["id"] == meeting_id), None)
    if not e:
        raise ValueError("No such meeting.")
    return e


def lib_list(req):
    """Meetings, newest first, filtered; with the counts the page shows beside each filter."""
    all_ = _entries(req.q("refresh") != "0")
    rows = library.find(all_, req.q("q") or "", req.q("project") or "", req.q("year") or "", req.q("tag") or "", req.q("src") or "", req.q("summary") or "")
    off, lim = int(req.q("offset") or 0), min(int(req.q("limit") or 80), 300)
    keep = ("id", "src", "date", "title", "project", "speakers", "tags", "kind", "minutes", "lines", "path")
    return {"total": len(rows), "rows": [{**{k: e[k] for k in keep}, "has_summary": bool(e["summary_path"])} for e in rows[off:off + lim]],
            "facets": library.facets(all_), "archive": str(library.archive_dir() or "")}


def lib_meeting(req):
    """One meeting: the transcript as it is, the summary if there is one, and what was promised (quoted)."""
    e = _one(req.q("id", required=True))
    body = library.read(e)
    lines = [l for l in body["transcript"].splitlines() if l.strip()]
    promised = said(lines, lambda s: COMMIT.search(s) or NAMED_WILL.search(s))[:60]
    memory.log("twinmind", "action.open_meeting", {"src": e["src"], "has_summary": bool(body["summary"])})
    return {**{k: e[k] for k in ("id", "src", "date", "title", "project", "speakers", "tags", "kind", "minutes", "path", "summary_path")},
            "transcript": body["transcript"], "summary": body["summary"], "commitments": promised, "transcript_lines": len(lines)}


def lib_meta(req):
    b = req.json()
    e = _one(b["id"])
    return library.set_meta(e["id"], b.get("tags"), b.get("project"))


def lib_inside(req):
    hits = library.search_inside(_entries(False), req.q("q") or "")
    memory.log("twinmind", "action.search", {"hits": len(hits), "where": "library"})
    return hits


def people(req):
    return {"people": library.people(), "heard": library.known_names(_entries(False), 60)}


def set_people(req):
    return {"people": library.save_people(req.json().get("people") or [])}


def across(req):
    """One project (or tag) over time: its meetings, who was in them, and from the summaries that
    exist, the action items and decisions gathered in one place with the meeting each came from."""
    all_ = _entries(False)
    rows = library.find(all_, project=req.q("project") or "", tag=req.q("tag") or "", year=req.q("year") or "")
    acts, decs, opens = [], [], []
    for e in rows:
        if not e["summary_path"]:
            continue
        text = Path(e["summary_path"]).read_text("utf-8", errors="replace")
        ref = {"id": e["id"], "date": e["date"], "meeting": e["title"]}
        acts += [{**ref, "text": l[2:].strip()} for l in _section(text, "Action Items").split("### ")[0].splitlines() if l.startswith("- ")]
        decs += [{**ref, "text": m.group(1).strip()} for m in re.finditer(r"^\\*\\*Decisions made:\\*\\* (?!None recorded)(.+)$", text, re.M)]
        opens += [{**ref, "text": l[2:].strip()} for l in _section(text, "Follow-up Needed").splitlines() if l.startswith("- ")]
    who = {}
    for e in rows:
        for s in e["speakers"]:
            who[s] = who.get(s, 0) + 1
    months = {}
    for e in rows:
        months[e["date"][:7]] = months.get(e["date"][:7], 0) + 1
    return {"meetings": len(rows), "with_summary": len([e for e in rows if e["summary_path"]]), "first": rows[-1]["date"] if rows else None,
            "last": rows[0]["date"] if rows else None, "people": sorted(who.items(), key=lambda kv: -kv[1])[:20], "months": sorted(months.items()),
            "actions": acts[:200], "decisions": decs[:200], "open": opens[:200],
            "rows": [{k: e[k] for k in ("id", "date", "title", "minutes")} | {"has_summary": bool(e["summary_path"])} for e in rows[:400]]}


'''

f = Path("apps/twinmind/worker.py")
s = f.read_text("utf-8")
for a, b in [
    ("from mitra_workers import convert, gist, meeting, memory, models, paths, work\n",
     "from mitra_workers import convert, gist, library, meeting, memory, models, paths, work\n"),
    ("def _memo(path: str) -> Path:", ROUTES.lstrip("\n") + "def _memo(path: str) -> Path:"),
    ('          ("POST", "line"): set_line, ("POST", "pause"): pause, ("POST", "stop"): stop, ("POST", "discard"): discard}',
     '          ("POST", "line"): set_line, ("POST", "pause"): pause, ("POST", "stop"): stop, ("POST", "discard"): discard,\n'
     '          ("GET", "library"): lib_list, ("GET", "meeting"): lib_meeting, ("POST", "meta"): lib_meta, ("GET", "inside"): lib_inside,\n'
     '          ("GET", "people"): people, ("POST", "people"): set_people, ("GET", "across"): across}'),
    # names: tell the speech model who is likely to be named, then put right what it still got wrong
    ("        segs = models.transcribe(\"twinmind\", wav, wav_ready=True, progress=say, turns=turns or None, info=heard, work=w, speed=item[\"speed\"])\n",
     "        names = list(dict.fromkeys(attendees + library.known_names(library.index(out_dir(), refresh=False))))\n"
     "        segs = models.transcribe(\"twinmind\", wav, wav_ready=True, progress=say, turns=turns or None, info=heard, work=w, speed=item[\"speed\"], names=names)\n"
     "        fixed = 0\n"
     "        for seg in segs:\n"
     "            seg[\"text\"], n = library.fix_names(seg[\"text\"])\n"
     "            fixed += n\n"),
    ("                                + (\"; fast speed was chosen\" if item[\"speed\"] == \"fast\" else \"\"))\n",
     "                                + (\"; fast speed was chosen\" if item[\"speed\"] == \"fast\" else \"\")\n"
     "                                + (f\"; {fixed} name{'s' if fixed != 1 else ''} put right from your people list\" if fixed else \"\"))\n"),
    ("        lines = [l for l in convert.to_markdown(src).splitlines() if l.strip()]\n        stages[\"transcribe\"] = \"skipped: input was already text\"",
     "        raw = convert.to_markdown(src)\n"
     "        if raw.lstrip().startswith(\"---\"):       # a transcript from the archive: its front matter is a record, not speech\n"
     "            fm, raw = library._front(raw.lstrip())\n"
     "            title = title or re.sub(r\"^\\d{6}\\s+[—-]\\s+\", \"\", fm.get(\"title\") or \"\")\n"
     "            attendees = attendees or fm.get(\"_speakers\") or []\n"
     "        raw, _fixed = library.fix_names(raw)\n"
     "        lines = [l for l in raw.splitlines() if l.strip()]\n        stages[\"transcribe\"] = \"skipped: input was already text\""),
]:
    assert s.count(a) == 1, (s.count(a), a[:70])
    s = s.replace(a, b)
f.write_text(s, "utf-8")

# the people list starts with the owner's own name and the wrong spelling the speech model produced for it
from pathlib import Path as P
import json
people = P.home() / ".mitra" / "twinmind" / "people.json"
if not people.exists():
    people.parent.mkdir(parents=True, exist_ok=True)
    people.write_text(json.dumps([{"name": "Anirudh", "aliases": ["Anurag", "Anirud", "Aniruddh", "Anirudha", "Anirudhh"]}]), "utf-8")
print("ok")

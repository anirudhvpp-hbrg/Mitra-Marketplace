"""The meeting library: every meeting TwinMind can see, old and new, in one index.

Two kinds of source, both plain Markdown on disk:
  memo        a memo TwinMind wrote (summary first, transcript as an appendix), in its Dropbox folder
  transcript  a transcript from the meeting archive (front matter with date, title, client, speakers)

The archive is only ever read. Everything TwinMind adds about a meeting (tags, a project, the memo it
writes as that meeting's summary) lives in TwinMind's own folders, keyed by the meeting's id.

Reading 2,600 files on every request would be slow, so the index (front matter only) is kept in
~/.mitra/twinmind/index.json and a file is read again only when its size or modified time changes.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import paths

STORE = paths.HOME / "twinmind"
INDEX, META, PEOPLE = STORE / "index.json", STORE / "meta.json", STORE / "people.json"
# One spelling per project. An archive can hold the same client written two ways; the owner's own
# file (~/.mitra/twinmind/project_names.json, {"lowercase": "As It Should Be Written"}) settles it.
NAMES = STORE / "project_names.json"
_canon = None
H_TRANSCRIPT = "Appendix: Transcript"


def _load(f: Path, default):
    try:
        return json.loads(f.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _save(f: Path, obj) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
    paths.replace(tmp, f)


def archive_dir() -> Path | None:
    """Where old meetings are: `meeting_archive` in ~/.mitra/config.json (a folder of transcripts, read only)."""
    cfg = paths.config().get("meeting_archive")
    if not cfg:
        return None
    p = Path(cfg).expanduser()
    return p if p.is_dir() else None


def project_name(raw: str | None) -> str:
    raw = (raw or "").strip().strip('"')
    if not raw or raw.lower() in ("null", "none", "?"):
        return ""
    global _canon
    if _canon is None:
        _canon = {str(k).lower(): str(v) for k, v in _load(NAMES, {}).items()}
    return _canon.get(raw.lower(), raw)


def _front(text: str) -> tuple[dict, str]:
    """(front matter as a flat dict, the rest). Lists of speakers are read for their names only."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm, out = text[3:end], {}
    for m in re.finditer(r"^([A-Za-z_]+):[ \t]*(.*)$", fm, re.M):
        out[m.group(1)] = m.group(2).strip().strip('"')
    out["_speakers"] = list(dict.fromkeys(n.strip().strip('"') for n in re.findall(r"resolved_to:[ \t]*(.+)$", fm, re.M)
                                          if n.strip() not in ("null", "")))
    return out, text[end + 4:].lstrip("\n")


def _minutes(fm: dict) -> int | None:
    try:
        a, b = (int(x[:2]) * 60 + int(x[3:5]) for x in (fm["start"], fm["end"]))
        return (b - a) % 1440 or None
    except (KeyError, ValueError):
        return None


def _entry(f: Path, src: str, st: os.stat_result) -> dict:
    with open(f, encoding="utf-8", errors="replace") as fh:
        head = fh.read(3000)
    fm, _ = _front(head)
    title = re.sub(r"^\d{6}\s+[—-]\s+", "", fm.get("title") or "") or re.sub(r"^\d{4}-\d{2}-\d{2} \d{4} |^\d{6}\s+[—-]\s+", "", f.stem)
    date = (fm.get("date") or "")[:10]
    if not re.match(r"\d{4}-\d{2}-\d{2}", date):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", f.stem)
        date = m.group(1) if m else time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))
    e = {"id": hashlib.sha1(str(f).encode()).hexdigest()[:12], "src": src, "path": str(f), "size": st.st_size, "mtime": int(st.st_mtime),
         "date": date, "title": title, "project": project_name(fm.get("client")), "speakers": fm.get("_speakers") or [],
         "kind": "memo" if src == "mitra" else "transcript", "minutes": _minutes(fm), "lines": int(fm["lines"]) if (fm.get("lines") or "").isdigit() else None}
    if src == "mitra":
        e["of"] = fm.get("source") or ""          # the recording or transcript this memo was written from
        att = fm.get("attendees") or ""
        e["speakers"] = [a.strip() for a in att.split(",") if a.strip() and att != "not given"]
    return e


def index(memo_dir: Path, refresh: bool = True) -> list[dict]:
    """Every meeting, newest first. Files are read again only if they changed."""
    old = {e["path"]: e for e in _load(INDEX, [])}
    if not refresh and old:
        return sorted(old.values(), key=lambda e: (e["date"], e["mtime"]), reverse=True)
    out, changed = [], False
    roots = [("mitra", memo_dir)] + ([("archive", archive_dir())] if archive_dir() else [])
    for src, root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith(".md"):
                    continue
                f = Path(dirpath) / name
                try:
                    st = f.stat()
                except OSError:
                    continue
                e = old.get(str(f))
                if not e or e["size"] != st.st_size or e["mtime"] != int(st.st_mtime):
                    e, changed = _entry(f, src, st), True
                out.append(e)
    if changed or len(out) != len(old):
        _save(INDEX, out)
    return sorted(out, key=lambda e: (e["date"], e["mtime"]), reverse=True)


def with_meta(entries: list[dict]) -> list[dict]:
    """Add what TwinMind knows beyond the file: your tags and project, and which memo is a transcript's summary."""
    meta = _load(META, {})
    memo_of = {os.path.normcase(e["of"]): e for e in entries if e["kind"] == "memo" and e.get("of")}
    out = []
    for e in entries:
        m = meta.get(e["id"], {})
        e = {**e, "tags": m.get("tags", []), "project": m.get("project", e["project"])}
        if e["kind"] == "transcript":
            memo = memo_of.get(os.path.normcase(e["path"]))
            e["summary_path"] = memo["path"] if memo else None
        else:
            e["summary_path"] = e["path"]
        out.append(e)
    # a memo written as an archive meeting's summary is shown under that meeting, not as a second one
    linked = {os.path.normcase(e["path"]) for e in out if e["kind"] == "transcript"}
    return [e for e in out if not (e["kind"] == "memo" and os.path.normcase(e.get("of", "")) in linked)]


def find(entries: list[dict], q: str = "", project: str = "", year: str = "", tag: str = "", src: str = "", summary: str = "") -> list[dict]:
    words = [w for w in re.findall(r"[\wऀ-෿&]+", q.lower()) if len(w) > 1]
    out = []
    for e in entries:
        if project and (e["project"] or "(none)") != project:
            continue
        if year and not e["date"].startswith(year):
            continue
        if tag and tag not in e["tags"]:
            continue
        if src and e["src"] != src:
            continue
        if summary == "yes" and not e["summary_path"] or summary == "no" and e["summary_path"]:
            continue
        if words:
            hay = " ".join([e["title"], e["project"], " ".join(e["speakers"]), " ".join(e["tags"]), e["date"]]).lower()
            if not all(w in hay for w in words):
                continue
        out.append(e)
    return out


def facets(entries: list[dict]) -> dict:
    def count(key):
        c = {}
        for e in entries:
            for v in (key(e) if isinstance(key(e), list) else [key(e)]):
                c[v] = c.get(v, 0) + 1
        return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"projects": count(lambda e: e["project"] or "(none)"), "years": sorted(count(lambda e: e["date"][:4]), reverse=True),
            "tags": count(lambda e: e["tags"]), "people": count(lambda e: e["speakers"])[:60],
            "total": len(entries), "with_summary": len([e for e in entries if e["summary_path"]])}


def read(e: dict) -> dict:
    """One meeting in full: the transcript as it is, and the summary if there is one."""
    text = Path(e["path"]).read_text("utf-8", errors="replace")
    fm, body = _front(text)
    if e["kind"] == "memo":
        summary, _, transcript = body.partition(f"## {H_TRANSCRIPT}")
        return {"transcript": transcript.strip(), "summary": summary.strip(), "pipeline": {k: v for k, v in fm.items() if k in ("source", "date")}}
    summary = None
    if e.get("summary_path"):
        _, memo = _front(Path(e["summary_path"]).read_text("utf-8", errors="replace"))
        summary = memo.partition(f"## {H_TRANSCRIPT}")[0].strip()
    return {"transcript": body.strip(), "summary": summary}


def set_meta(meeting_id: str, tags=None, project=None) -> dict:
    meta = _load(META, {})
    m = meta.setdefault(meeting_id, {})
    if tags is not None:
        m["tags"] = list(dict.fromkeys(re.sub(r"[\r\n,#]+", " ", str(t)).strip()[:40] for t in tags if str(t).strip()))[:12]
    if project is not None:
        m["project"] = re.sub(r"[\r\n]+", " ", str(project)).strip()[:60]
    _save(META, meta)
    return m


def search_inside(entries: list[dict], q: str, limit: int = 60) -> list[dict]:
    """Find what was said, in the transcripts themselves. Passages are quoted exactly."""
    words = [w for w in re.findall(r"[\wऀ-෿]{3,}", q.lower())]
    if not words:
        return []
    hits = []
    for e in entries:
        try:
            text = Path(e["path"]).read_text("utf-8", errors="replace")
        except OSError:
            continue
        low = text.lower()
        if not all(w in low for w in words):
            continue
        for n, line in enumerate(text.splitlines()):
            l = line.lower()
            if len(line) > 12 and all(w in l for w in words) and not line.startswith(("source", "title:", "pipeline:")):
                hits.append({"id": e["id"], "meeting": e["title"], "date": e["date"], "project": e["project"], "line": n + 1, "text": line.strip()[:400]})
                break
        else:
            first = next((line for line in text.splitlines() if words[0] in line.lower() and len(line) > 12), "")
            hits.append({"id": e["id"], "meeting": e["title"], "date": e["date"], "project": e["project"], "line": 0, "text": first.strip()[:400]})
        if len(hits) >= limit:
            break
    return hits


# ---- people: the names that must come out right ---------------------------------------------
def people() -> list[dict]:
    """[{name, aliases}]. `aliases` are the wrong spellings a speech model produces for that name."""
    return _load(PEOPLE, [])


def save_people(rows: list) -> list[dict]:
    out = []
    for r in rows if isinstance(rows, list) else []:
        name = re.sub(r"[\r\n:\[\],]+", " ", str(r.get("name", ""))).strip()[:40]
        if name:
            al = [re.sub(r"[\r\n:\[\],]+", " ", str(a)).strip()[:40] for a in (r.get("aliases") or [])]
            out.append({"name": name, "aliases": list(dict.fromkeys(a for a in al if a and a.lower() != name.lower()))})
    _save(PEOPLE, out)
    return out


def known_names(entries: list[dict] | None = None, limit: int = 40) -> list[str]:
    """Names to give the speech model so it spells them right: your people list first, then the
    names heard most often in the archive."""
    names = [p["name"] for p in people()]
    if entries:
        c = {}
        for e in entries:
            for s in e["speakers"]:
                if re.fullmatch(r"[A-Z][a-zA-Z]{2,}(?: [A-Z][a-zA-Z]+)?", s) and not s.startswith("Speaker"):
                    c[s] = c.get(s, 0) + 1
        names += [n for n, _ in sorted(c.items(), key=lambda kv: -kv[1])]
    return list(dict.fromkeys(names))[:limit]


def fix_names(text: str) -> tuple[str, int]:
    """Replace every known wrong spelling with the right name. Returns (text, how many were fixed)."""
    total = 0
    for p in people():
        for a in p["aliases"]:
            text, n = re.subn(rf"(?<![\w]){re.escape(a)}(?![\w])", p["name"], text, flags=re.I)
            total += n
    return text, total

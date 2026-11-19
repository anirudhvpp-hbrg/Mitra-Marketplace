"""TwinMind pipeline: recording or transcript in, a grounded memo out.

Stages run one after another; each model is unloaded before the next loads:
  transcribe  whisper.cpp, for audio input (skipped when the input is already text)
  diarize     NVIDIA Sortformer in audio.cpp: who spoke when, merged into the transcript
  gist        two or three sentences quoted word for word; plain code, no model
  understand  the meeting-notes model, section by section: points, decisions, open questions,
              action items as constrained JSON; every item then passes the grounding guards
  write       a Markdown memo into the app's Dropbox folder
Every finished window, piece and section is saved (mitra_workers.work), so a job that stops picks up
where it was; recordings wait in a line and run one at a time; the notes model steps aside between
sections when another app is waiting. A stage that cannot run is recorded as skipped in the memo, never silently dropped. If the
model is unavailable the memo still has the gist and the commitments quoted by pattern.

The gist, the guards, the notes contract and the deterministic merge are absorbed from APTM.
"""
import json
import os
import re
import shutil
import signal
import time
import traceback
from datetime import datetime
from pathlib import Path

from mitra_workers import convert, gist, library, meeting, memory, models, paths, work

AUDIO = {".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".flac", ".webm", ".aac"}
_DAY = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|tonight|end of|next week|eod"
# "will" counts only with someone doing it ("I will", "we will", "Sam will"): "the problem will come" is not a promise.
COMMIT = re.compile(r"\b((I|we|you|he|she) will|I'll|we'll|you'll|I can take|I have to|we have to|I would require|please|can you|could you|"
                    r"needs? to|action item|(by|until|till) (at least )?(" + _DAY + r"))\b", re.I)
NAMED_WILL = re.compile(r"\b(?!(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|It|That|This|There|What|Which)\b)[A-Z][a-z]+ will\b")
DECIDE = re.compile(r"\b(decision|decided|we agreed|agreed to|let's go with|we will go with|final call|settled on|approved)\b", re.I)
# Section headings of the memo, as in the MeetingNoter format your archived notes follow.
H_FOCUS, H_POINTS, H_ACTIONS, H_FOLLOW, H_TRANSCRIPT = ("\U0001F3F9 Meeting Core Focus", "\U0001F4DC Key Discussion Points",
                                                         "\U0001F447 Action Items", "⏰ Follow-up Needed", "Appendix: Transcript")
SPEAKER_LINE = re.compile(r"^\s*(?:\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*)?([^:\n]{1,40}):\s*(.+)$")


def out_dir() -> Path:
    d = paths.resolve_connector(APP.manifest["connectors"][0]) or (paths.HOME / "twinmind")  # noqa: F821 (APP is injected)
    d.mkdir(parents=True, exist_ok=True)
    return d


def stamp(seconds: float) -> str:
    return f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d}"


def said(lines: list[str], test) -> list[str]:
    """The sentences that pass `test`, each quoted alone with its time and speaker. A transcript line
    can be half a minute of one person talking; the commitment is one sentence of it."""
    out = []
    for l in lines:
        m = re.match(r"^((?:\[[\d:]+\]\s*)?(?:[^:\n\[\]]{1,40}:\s+)?)(.+)$", l.strip())
        if not m:
            continue
        for s in re.split(r"(?<=[.?!])\s+", m.group(2)):
            if len(s.split()) >= 4 and len(s) < 400 and test(s):
                out.append(m.group(1) + s.strip())
    return out


def status(req):
    pub = APP.public()  # noqa: F821
    return {"needs": pub["needs"], "output": str(out_dir()), "audio_exts": sorted(AUDIO)}


def _section(text: str, *headings: str) -> str:
    """The body under a `##` heading. Headings are matched without their emoji and without regard
    to case, and several names can be given, so memos in the older layout still read."""
    for heading in headings:
        m = re.search(rf"^##[^\w\n]*{re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M | re.I)
        if m:
            return m.group(1).strip()
    return ""


def meetings(req):
    out = []
    for f in sorted(out_dir().glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:40]:
        text = f.read_text("utf-8", errors="replace")
        g = " ".join(l.lstrip("> ").strip() for l in _section(text, "Meeting Core Focus", "The gist").splitlines() if l.startswith(">"))[:260]
        acts = len([l for l in _section(text, "Action Items").split("### ")[0].splitlines() if l.startswith("- ")])
        out.append({"name": f.stem, "path": str(f), "mtime": f.stat().st_mtime, "gist": g, "actions": acts})
    return out


def search(req):
    """Find what was said, across every saved meeting. Passages are quoted exactly as written; no model."""
    words = [w for w in re.findall(r"[\wऀ-෿]{3,}", (req.q("q") or "").lower())]
    if not words:
        return []
    hits = []
    for f in out_dir().glob("*.md"):
        for n, line in enumerate(f.read_text("utf-8", errors="replace").splitlines()):
            low = line.lower()
            score = sum(low.count(w) for w in words)
            if score and len(line.strip()) > 12 and not line.startswith(("---", "source:", "pipeline:")):
                hits.append((sum(w in low for w in words), score, f.stat().st_mtime, {"meeting": f.stem, "path": str(f), "line": n + 1, "text": line.strip()[:400]}))
    # The same sentence appears in a memo's transcript and again where the notes quote it. Keep one
    # per meeting, and keep the transcript's copy (the later line), since that is the source.
    best = {}
    for h in hits:
        key = (h[3]["meeting"], re.sub(r"[^a-z0-9]+", " ", re.sub(r"^\s*(?:[-*>]\s*)?(?:\[[\d:]+\]\s*)?", "", h[3]["text"]).lower()).strip())
        if key not in best or h[3]["line"] > best[key][3]["line"]:
            best[key] = h
    hits = sorted(best.values(), key=lambda h: (-h[0], -h[1], -h[2], h[3]["line"]))
    memory.log("twinmind", "action.search", {"terms": len(words), "hits": len(hits)})
    return [h[3] for h in hits[:25]]


# ---- time: what a recording will take on this device ------------------------------------------
# Seconds of work per minute of audio, and per section of notes. The defaults were measured on the
# development laptop (2026-11-13); after every finished job they are replaced by this device's own.
RATES_FILE = paths.HOME / "run" / "twinmind-rates.json"
RATES = {"diarize": 15.8, "notes": 21.0, "sections_per_min": 0.36,
         "transcribe": {"whisper-medium-q5_0-cpp": 25.0, "whisper-small-q5_1-cpp": 10.5, "whisper-base-q5_1-cpp": 5.0}}


def rates() -> dict:
    out = json.loads(json.dumps(RATES))
    try:
        own = json.loads(RATES_FILE.read_text("utf-8"))
        out.update({k: v for k, v in own.items() if k != "transcribe"}, measured=True)
        out["transcribe"].update(own.get("transcribe") or {})
    except (OSError, ValueError):
        pass
    return out


def learn(key: str, value: float, model: str | None = None):
    """Fold one measured rate into this device's own (half old, half new)."""
    if not value or value <= 0:
        return
    try:
        own = json.loads(RATES_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        own = {}
    box = own.setdefault("transcribe", {}) if model else own
    k = model or key
    box[k] = round((box[k] + value) / 2 if k in box else value, 2)
    RATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RATES_FILE.write_text(json.dumps(own), "utf-8")


def plan_for(seconds: float, speed: str) -> dict:
    """Stages, pieces and estimated seconds for a recording of this length at this speed."""
    r, mins = rates(), seconds / 60
    p = models.transcription_choice(speed)
    model = p.get("model") or "?"
    windows = len(models.diar_windows(seconds))
    pieces = max(1, round(seconds / models.PIECE_S))
    sections = max(1, round(r["sections_per_min"] * mins))
    per = r["transcribe"].get(model) or RATES["transcribe"].get(model) or 25.0
    est = {"diarize": r["diarize"] * mins, "transcribe": per * mins, "understand": r["notes"] * sections}
    return {"speed": speed, "model": model, "windows": windows, "pieces": pieces, "sections": sections,
            "seconds": round(sum(est.values())), "stages": {k: round(v) for k, v in est.items()}, "measured": bool(r.get("measured"))}


def estimate(req):
    """How long this file will take at each speed, before anything runs."""
    src = Path(req.q("path", required=True))
    if src.suffix.lower() not in AUDIO:
        return {"audio": False}
    secs = models.audio_seconds(src)
    if not secs:
        return {"audio": True, "seconds": None}
    out = {"audio": True, "seconds": round(secs), "accurate": plan_for(secs, "accurate"), "fast": plan_for(secs, "fast")}
    out["same_model"] = out["accurate"]["model"] == out["fast"]["model"]
    return out


# ---- the line of recordings -------------------------------------------------------------------
LINE = paths.HOME / "run" / "twinmind-line.json"
RUNNER = paths.HOME / "run" / "twinmind-runner.json"


def _read(f: Path, default):
    try:
        return json.loads(f.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write(f: Path, obj):
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
    paths.replace(tmp, f)


def _runner() -> dict | None:
    """The process working through recordings now, if one is alive."""
    r = _read(RUNNER, None)
    if r and work.alive(r.get("pid")):
        return r
    RUNNER.unlink(missing_ok=True)
    return None


def _take_runner(job_id: str) -> bool:
    if _runner():
        return False
    try:
        with open(RUNNER, "x", encoding="utf-8") as f:
            f.write(json.dumps({"pid": os.getpid(), "job": job_id}))
        return True
    except FileExistsError:
        return False


def _item(b: dict) -> dict:
    src = Path(b["path"])
    if not src.is_file():
        raise ValueError(f"Not found: {src}")
    return {"path": str(src), "name": b.get("name") or src.name, "title": (b.get("title") or "").strip(),
            "attendees": (b.get("attendees") or "").strip(), "speed": "fast" if b.get("speed") == "fast" else "accurate",
            "fresh": bool(b.get("fresh")), "added": time.time()}


def _work_for(item: dict) -> work.Work:
    lang = paths.config().get("transcribe_language") or "english"
    return work.Work(Path(item["path"]), item["speed"], lang)


def state(req):
    """What the page needs to draw: the job running now, the recordings waiting, and jobs that stopped."""
    r = _runner()
    line = _read(LINE, [])
    for it in line:
        secs = models.audio_seconds(Path(it["path"])) if Path(it["path"]).suffix.lower() in AUDIO else None
        it["seconds"] = round(secs) if secs else None
        it["estimate"] = plan_for(secs, it["speed"])["seconds"] if secs else None
    stopped = []
    for m in work.unfinished():
        if r and m.get("key") == r.get("key"):
            continue
        item = m.get("item") or {}
        left = None
        if m.get("seconds_audio"):
            plan, prog = plan_for(m["seconds_audio"], item.get("speed", "accurate")), m.get("progress") or {}
            left = round(sum(secs * (1 - (prog.get(k, [0, 1])[0] / max(1, prog.get(k, [0, 1])[1]))) for k, secs in plan["stages"].items()))
        stopped.append({"key": m["key"], "item": item, "name": item.get("name") or Path(m.get("source", "")).name, "progress": m.get("progress") or {},
                        "state": m.get("state"), "stage": m.get("stage"), "why": m.get("why") or "", "touched": m.get("touched"),
                        "source_missing": bool(m.get("source_missing")), "left_s": left})
    return {"running": r, "line": line, "unfinished": stopped}


def set_line(req):
    """Reorder or remove waiting recordings: `order` is the old positions in their new order."""
    old = _read(LINE, [])
    order = [int(i) for i in (req.json().get("order") or []) if 0 <= int(i) < len(old)]
    _write(LINE, [old[i] for i in dict.fromkeys(order)])
    return {"line": len(order)}


def pause(req):
    """Stop after the piece in hand. Everything finished stays on disk; the model is freed."""
    r = _runner()
    if not r or not r.get("key"):
        return {"paused": False}
    (work.ROOT / r["key"] / "pause").write_text("", "utf-8")
    return {"paused": True}


def stop(req):
    """Stop now. The piece in hand is lost; the finished ones are kept until they are discarded."""
    r = _runner()
    if not r:
        return {"stopped": False}
    try:
        os.kill(int(r["pid"]), signal.SIGTERM)      # the governor sees its caller gone and stops the model
    except OSError:
        pass
    RUNNER.unlink(missing_ok=True)
    jf = paths.HOME / "run" / "jobs" / f"{r['job']}.json"
    j = _read(jf, None)
    if j and j.get("status") == "running":
        j.update(status="stopped", error=None)
        _write(jf, j)
    if r.get("key"):
        m = _read(work.ROOT / r["key"] / "job.json", None)
        if m:
            m.update(state="stopped", why="You stopped it.", pid=0)
            _write(work.ROOT / r["key"] / "job.json", m)
    memory.log("twinmind", "job.stopped", {"job": r["job"]})
    return {"stopped": True}


def discard(req):
    """Throw away the saved pieces of a job that stopped. They go to the Recycle Bin."""
    key = re.sub(r"[^0-9a-f]", "", str(req.json().get("key") or ""))
    r = _runner()
    d = work.ROOT / key
    if not key or not d.is_dir() or (r and r.get("key") == key):
        return {"discarded": False}
    return {"discarded": True, "to": work.recycle(d)}


def run(req):
    """Write the memo for one recording, then for each one waiting in the line. If recordings are
    already being worked through, this one joins the line instead."""
    item, job = _item(req.json()), req.job
    if not _take_runner(job.id):
        line = _read(LINE, [])
        line.append(item)
        _write(LINE, line)
        memory.log("twinmind", "job.queued", {"position": len(line), "ext": Path(item["path"]).suffix.lower()})
        return {"queued": True, "position": len(line)}
    out = None
    try:
        while True:
            w = None
            try:
                if item.get("fresh"):
                    work.recycle(_work_for(item).dir)
                w = _work_for(item)
                (w.dir / "pause").unlink(missing_ok=True)
                _write(RUNNER, {"pid": os.getpid(), "job": job.id, "key": w.key})
                out = process(item, job, w)
            except work.Paused:
                w.note(state="paused", why="You paused it.", pid=0)
                job.state.update(status="paused", seconds=round(time.time() - job.state["started"], 1))
                job.save()
                memory.log("twinmind", "job.paused", {"progress": w.meta.get("progress")})
                return None
            except models.Stopped:
                # Stopped by hand. The pieces are kept, and the line waits, as with a pause.
                w.note(state="stopped", why="The model was stopped by hand.", pid=0)
                job.state.update(status="stopped", seconds=round(time.time() - job.state["started"], 1))
                job.save()
                memory.log("twinmind", "job.stopped", {"how": "model stopped by hand", "progress": w.meta.get("progress")})
                return None
            except Exception as e:
                if w:
                    w.note(state="failed", why=str(e)[:300], pid=0)
                line = _read(LINE, [])
                if not line:
                    raise
                memory.log("twinmind", "error", {"msg": str(e), "trace": traceback.format_exc()[-800:]})
                out = None
                job.finish(error=str(e))
            line = _read(LINE, [])
            if not line:
                return out
            item = line.pop(0)
            _write(LINE, line)
            # each recording is its own job; the page follows `next` from one to the other
            nxt = f"{time.time_ns():x}"
            job.state["next"] = nxt
            if job.state["status"] == "running":
                job.finish(result=out)
            else:
                job.save()
            job = req.job = type(job)(nxt, "twinmind")
    finally:
        r = _read(RUNNER, None)
        if r and r.get("pid") == os.getpid():
            RUNNER.unlink(missing_ok=True)


def process(item: dict, job, w) -> dict:
    src = Path(item["path"])
    title = item["title"]
    attendees = [a.strip() for a in item["attendees"].split(",") if a.strip()]
    stages, flags = {}, []
    is_audio = src.suffix.lower() in AUDIO
    secs = models.audio_seconds(src) if is_audio else None
    plan = plan_for(secs, item["speed"]) if secs else None
    w.note(state="running", item=item, seconds_audio=secs, why="", job=job.id)
    if w.resumed:
        memory.log("twinmind", "job.resumed", {"progress": w.meta.get("progress")})
    job.state.update(item={k: item[k] for k in ("path", "name", "speed")}, key=w.key, seconds_audio=secs, resumed=w.resumed,
                     progress=dict(w.meta.get("progress") or {}), plan=plan, eta_s=plan["seconds"] if plan else None)
    job.save()
    # Time left: what is left of this stage at this run's own speed, plus the estimate for later stages.
    clock = {"stage": None, "t0": 0.0, "first": 0}
    spent, made_now, yields = {}, {}, 0

    def tick(stage, done, total):
        now = time.time()
        if clock["stage"] != stage:
            clock.update(stage=stage, t0=now, first=done - 1 if total and done else done)
            w.note(stage=stage)
        worked = done - clock["first"]
        made_now[stage], spent[stage] = worked, now - clock["t0"]
        job.state["progress"][stage] = [done, total]
        if plan:
            order = ["diarize", "transcribe", "understand"]
            later = sum(plan["stages"][k] for k in order[order.index(stage) + 1:]) if stage in order else 0
            each = (now - clock["t0"]) / worked if worked > 0 and now - clock["t0"] > 1 else plan["stages"].get(stage, 0) / max(total, 1)
            job.state["eta_s"] = round((total - done) * each + later)
        job.save()
    w.on_tick = tick

    def begin(stage):
        clock.update(stage=stage, t0=time.time(), first=(w.meta.get("progress") or {}).get(stage, [0, 0])[0])
        w.note(stage=stage)

    # 1 + 2. who spoke when comes first; the audio is then transcribed with each sentence given to its speaker
    if is_audio:
        job.step("diarize", "running", "preparing audio")
        wav, own_wav = w.dir / "audio.16k.wav", True
        if not wav.is_file():
            tmp, made = models.prepare_wav(src)
            if made:
                shutil.move(str(tmp), str(wav))
            else:
                wav, own_wav = tmp, False
        turns = []
        try:
            job.step("diarize", "running", "Sortformer")
            begin("diarize")
            turns = models.diarize("twinmind", wav, progress=lambda m: job.step("diarize", "running", m), work=w)
            who = len({t["speaker"] for t in turns})
            stages["diarize"] = f"{models.pick('diarization')['model']}, {who} speaker{'s' if who != 1 else ''}, {len(turns)} turns"
            job.step("diarize", "done", stages["diarize"])
        except (work.Paused, models.Stopped):
            raise
        except models.ModelUnavailable as e:
            stages["diarize"] = f"skipped: {e}"
            job.step("diarize", "skipped", str(e))
        except Exception as e:  # diarization must never cost you the transcript
            stages["diarize"] = f"failed, transcript kept without speakers: {e}"
            job.step("diarize", "skipped", stages["diarize"][:160])
            memory.log("twinmind", "error", {"msg": f"diarize: {e}"})
        job.step("transcribe", "running", "whisper.cpp")
        begin("transcribe")
        say = lambda m: job.step("transcribe", "running", m)  # noqa: E731
        heard = {}
        names = list(dict.fromkeys(attendees + library.known_names(library.index(out_dir(), refresh=False))))
        segs = models.transcribe("twinmind", wav, wav_ready=True, progress=say, turns=turns or None, info=heard, work=w, speed=item["speed"], names=names)
        fixed = 0
        for seg in segs:
            seg["text"], n = library.fix_names(seg["text"])
            fixed += n
        stages["transcribe"] = (f"{heard.get('model')}, {len(segs)} lines, language heard: {heard.get('language')}"
                                + (", translated into English by the model" if heard.get("translated") else "")
                                + (f"; {heard['stepped_down_from']} could not be given the memory it needs here, so the smaller model was used"
                                   if heard.get("stepped_down_from") else "")
                                + ("; fast speed was chosen" if item["speed"] == "fast" else "")
                                + (f"; {fixed} name{'s' if fixed != 1 else ''} put right from your people list" if fixed else ""))
        job.step("transcribe", "done", stages["transcribe"])
        if secs and made_now.get("diarize") and "diarize" in spent:
            total = job.state["progress"]["diarize"][1]
            learn("diarize", spent["diarize"] / (secs / 60 * made_now["diarize"] / total))
        if secs and made_now.get("transcribe") and " then " not in str(heard.get("model")):
            total = job.state["progress"]["transcribe"][1]
            learn("transcribe", spent["transcribe"] / (secs / 60 * made_now["transcribe"] / total), model=heard.get("model"))
        # Speakers stay "Speaker 1", "Speaker 2" here: which voice is whose is not something the
        # models know. The page asks you, with a line from each, once the memo is written.
        lines = [f"[{stamp(s['start'])}] {s['speaker'] + ': ' if s.get('speaker') else ''}{s['text']}" for s in segs]
    else:
        own_wav = False
        raw = convert.to_markdown(src)
        if raw.lstrip().startswith("---"):       # a transcript from the archive: its front matter is a record, not speech
            fm, raw = library._front(raw.lstrip())
            title = title or re.sub(r"^\d{6}\s+[—-]\s+", "", fm.get("title") or "")
            attendees = attendees or fm.get("_speakers") or []
        raw, _fixed = library.fix_names(raw)
        lines = [l for l in raw.splitlines() if l.strip()]
        stages["transcribe"] = "skipped: input was already text"
        stages["diarize"] = "skipped: no audio to listen to"
        job.step("transcribe", "skipped", "input is text")
        job.step("diarize", "skipped", "no audio")
    transcript = "\n".join(lines)
    if not transcript.strip():
        raise ValueError("The transcript is empty.")

    # 3. gist: quoted, no model
    job.step("gist", "running")
    spoken = [SPEAKER_LINE.match(l).group(2) if SPEAKER_LINE.match(l) else re.sub(r"^\[[\d:]+\]\s*", "", l) for l in lines]
    quoted = gist.extract(spoken)
    stages["gist"] = f"{len(quoted)} sentences quoted from the transcript, no model"
    job.step("gist", "done", stages["gist"])

    # 4. understand. The model is kept between sections while nobody else wants it, and let go
    # between sections the moment another app is in line (a question in Ask Mitra, say).
    notes, results = None, []

    def write_notes(model=None, why=""):
        nonlocal notes, results, flags, yields
        results, a, name = [], None, model or models.pick("meeting-notes").get("model")
        sections = meeting.chunk(lines)
        begin("understand")
        try:
            for i, sec in enumerate(sections):
                saved = w.load(f"notes-{i:04d}")
                if saved is None or (model and saved.get("model") != model):
                    w.check()
                    if a:
                        waiting = [t for t in models.someone_waiting() if t.get("app") != "twinmind"]
                        if waiting:
                            a.__exit__(None, None, None)
                            a, yields = None, yields + 1
                            memory.log("twinmind", "model.yield", {"to": waiting[0].get("app"), "section": i + 1, "of": len(sections)})
                            job.step("understand", "running", f"section {i + 1} of {len(sections)}: stepped aside for {waiting[0].get('app')}, continues by itself")
                    if a is None:
                        a = models.Assistant("twinmind", capability="meeting-notes", model=model, what="notes and action items").__enter__()
                        name = a.model
                    job.step("understand", "running", f"{a.model}, section {i + 1} of {len(sections)}")
                    saved = {**meeting.understand(a, sec, i), "model": a.model}
                    w.save(f"notes-{i:04d}", saved)
                results.append(saved)
                w.tick("understand", i + 1, len(sections))
        finally:
            if a:
                a.__exit__(None, None, None)
        notes = meeting.merge(results)
        flags = notes["flags"]
        stages["understand"] = f"{name}, {len(sections)} sections, {len(flags)} items removed by the grounding check" + why
        if made_now.get("understand"):
            learn("notes", spent["understand"] / made_now["understand"])
            if secs:
                learn("sections_per_min", len(sections) / (secs / 60))

    try:
        job.step("understand", "running", "loading model")
        try:
            write_notes()
        except models.MemoryDenied as e:
            # The first-choice notes model sits close to the ceiling. If this device could not give
            # it the memory, the next smaller one writes the notes and the memo says so.
            first = models.pick("meeting-notes").get("model")
            smaller = next((c["id"] for c in models.catalog()["meeting-notes"]["candidates"]
                            if c["id"] != first and c.get("contract", "generic") == "generic" and models.find_model(c["id"])), None)
            if not smaller:
                raise
            memory.log("twinmind", "model.fallback", {"from": first, "to": smaller, "why": str(e)[:200]})
            write_notes(smaller, f"; {first} could not be given the memory it needs here, so the smaller model was used")
        job.step("understand", "done", stages["understand"])
    except (models.ModelUnavailable, models.MemoryDenied) as e:
        notes, results, flags = None, [], []
        stages["understand"] = f"skipped: {e}"
        job.step("understand", "skipped", str(e))
    if w.resumed or yields:
        stages["job"] = ", ".join(x for x in ("picked up from saved pieces after a stop" if w.resumed else "",
                                              f"stepped aside for another app {yields} time{'s' if yields != 1 else ''}" if yields else "") if x)

    # 5. write
    job.step("write", "running")
    now = datetime.now()
    title = title or (notes or {}).get("title") or src.stem
    decided = said(lines, lambda s: DECIDE.search(s))
    promised = said(lines, lambda s: COMMIT.search(s) or NAMED_WILL.search(s))
    md = ["---", "type: note", f"title: {title}", f"date: {now:%Y-%m-%d %H:%M}", f"source: {src}",
          f"attendees: {', '.join(attendees) or 'not given'}", "author: mitra", "layout: meetingnoter", "pipeline:"]
    md += [f"  {k}: {v}" for k, v in stages.items()] + ["---", "", f"# {title}", "",
           f"**Date:** {now:%d %B %Y, %H:%M}  ", f"**Attendees:** {', '.join(attendees) or 'not given'}  ", f"**Source:** {src.name}", ""]
    # The layout is the one your own notes use (MeetingNoter): core focus, discussion by topic with
    # the decisions made under each, action items with owners, follow-up, and the transcript last.
    md += [f"## {H_FOCUS}", "", *([f"> {q['text']}" for q in quoted] or ["_Nothing quotable was found._"]), "",
           "_Quoted word for word from the transcript._"]
    if notes and notes["topics"]:
        md += ["", "**Topics covered:** " + "; ".join(notes["topics"])]
    md += ["", f"## {H_POINTS}", ""]
    if notes:
        shown = 0
        for r in results:
            n = r["index"] + 1
            pts = [x["text"] for x in notes["points"] if x["section"] == n]
            dec = [x["text"] for x in notes["decisions"] if x["section"] == n]
            if not pts and not dec:
                continue
            shown += 1
            md += [f"### {shown}. {r['notes'].get('topic') or r.get('title') or f'Part {n}'}", "", *[f"- {x}" for x in pts], "",
                   "**Decisions made:** " + (" ".join(d.rstrip(".") + "." for d in dec) if dec
                                             # the quoted list below has them: saying "none" above it reads as a contradiction
                                             else "see the decisions stated in the transcript, below." if decided and not notes["decisions"]
                                             else "None recorded in this part."), ""]
        if not shown:
            md += ["None recorded.", ""]
    else:
        md += ["_The notes model did not run (see the pipeline list at the top), so nothing is summarised here._", ""]
    if decided and not (notes and notes["decisions"]):
        md += ["### Decisions stated in the transcript", "", *[f"- {d}" for d in decided], "",
               "_Quoted from the transcript: lines where a decision was stated._", ""]
    md += [f"## {H_ACTIONS}", ""]
    if notes and notes["actions"]:
        md += [f"- **{a['owner'] or 'Unassigned'}**: {a['task']}" + (f" (due {a['due']})" if a["due"] else "") for a in notes["actions"]]
        md += ["", "_Extracted by the model, then checked: an owner or date is kept only if the transcript ties it to that task._"]
    else:
        md += ["None extracted."]
    # The model's list can miss or mis-pair things, so what was actually said is always shown too.
    md += ["", "### Commitments heard", ""]
    md += ([f"- {p}" for p in promised] + ["", "_Quoted from the transcript: every line that sounds like a commitment or request._"]) if promised else ["None found."]
    md += ["", f"## {H_FOLLOW}", ""]
    md += ([f"- {q['text']}" for q in notes["open_questions"]] or ["None recorded."]) if notes else ["_Not assessed: the notes model did not run._"]
    if notes:
        if flags:
            # What the model merely echoed (a pasted line, "Correct") is counted; what it got wrong
            # about the meeting (a number, an owner, a date never said) is listed.
            echo = [f for f in flags if "copied from the transcript" in f or "is not a task" in f or "says nothing" in f]
            wrong = [f for f in flags if f not in echo]
            md += ["", "## Removed by the grounding check", ""]
            md += [f"- {f}" for f in wrong]
            if echo:
                md += [f"- {len(echo)} item{'s' if len(echo) != 1 else ''} the model offered as a note or task "
                       f"{'were' if len(echo) != 1 else 'was'} only transcript lines or pleasantries repeated back, and {'were' if len(echo) != 1 else 'was'} dropped."]
        md += ["", "_Notes are written by a small local model. Check them against the transcript before relying on them._"]
    md += ["", f"## {H_TRANSCRIPT}", "", transcript.strip(), ""]
    safe = re.sub(r"\s+", " ", re.sub(r"[^\w \-]+", " ", title))[:60].strip() or "meeting"
    out = out_dir() / f"{now:%Y-%m-%d %H%M} {safe}.md"
    out.write_text("\n".join(md), "utf-8")
    job.step("write", "done", str(out))
    memory.log("twinmind", "action.meeting_processed", {"path": str(out), "chars": len(transcript), "stages": stages,
                                                        "actions": len((notes or {}).get("actions", [])), "removed": len(flags)})
    w.finish()     # the memo is written: the saved pieces and the prepared audio are no longer needed
    return {"path": str(out), "stages": stages, "title": title, "resumed": w.resumed, "yields": yields}


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
        decs += [{**ref, "text": m.group(1).strip()} for m in re.finditer(r"^\*\*Decisions made:\*\* (?!None recorded)(.+)$", text, re.M)]
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


def _memo(path: str) -> Path:
    """A memo path from the page, accepted only if it is a .md file inside this app's folder."""
    f = Path(path).resolve()
    if f.suffix.lower() != ".md" or out_dir().resolve() not in f.parents or not f.is_file():
        raise ValueError("That is not a memo in the TwinMind folder.")
    return f


def speakers(req):
    """Who is in a memo's transcript, each with how much they said and one line to recognise them by."""
    f = _memo(req.q("path", required=True))
    tr = f.read_text("utf-8", errors="replace").split(f"## {H_TRANSCRIPT}", 1)[-1]
    seen = {}
    for m in re.finditer(r"^\[[\d:]+\] ([^:\n]{1,40}): (.+)$", tr, re.M):
        s = seen.setdefault(m.group(1), {"speaker": m.group(1), "lines": 0, "sample": ""})
        s["lines"] += 1
        if len(m.group(2)) > len(s["sample"]) and len(s["sample"]) < 60:
            s["sample"] = m.group(2)[:140]
    return list(seen.values())


def name_speakers(req):
    """Put names in place of "Speaker 1", "Speaker 2" everywhere in one memo."""
    b = req.json()
    f = _memo(b["path"])
    names = {k: re.sub(r"[\r\n:\[\]]+", " ", str(v)).strip()[:40] for k, v in (b.get("names") or {}).items()}
    names = {k: v for k, v in names.items() if v and v != k}
    if not names:
        return {"changed": 0}
    text = f.read_text("utf-8")
    present = {m for m in re.findall(r"^\[[\d:]+\] ([^:\n]{1,40}): ", text, re.M)}
    total = 0
    for old, new in names.items():
        if old not in present:
            continue
        text, n = re.subn(rf"(?<![\w]){re.escape(old)}(?![\w])", lambda _m, new=new: new, text)
        total += n
    if total:
        people = ", ".join(dict.fromkeys(names.get(s, s) for s in sorted(present)))
        text = re.sub(r"^attendees: not given$", f"attendees: {people}", text, count=1, flags=re.M)
        text = text.replace("**Attendees:** not given", f"**Attendees:** {people}", 1)
        f.write_text(text, "utf-8")
        memory.log("twinmind", "action.speakers_named", {"path": str(f), "speakers": len(names), "replaced": total})
    return {"changed": total}


ROUTES = {("GET", "status"): status, ("GET", "meetings"): meetings, ("GET", "search"): search, ("POST", "job/run"): run,
          ("GET", "speakers"): speakers, ("POST", "speakers"): name_speakers, ("GET", "estimate"): estimate, ("GET", "state"): state,
          ("POST", "line"): set_line, ("POST", "pause"): pause, ("POST", "stop"): stop, ("POST", "discard"): discard,
          ("GET", "library"): lib_list, ("GET", "meeting"): lib_meeting, ("POST", "meta"): lib_meta, ("GET", "inside"): lib_inside,
          ("GET", "people"): people, ("POST", "people"): set_people, ("GET", "across"): across}

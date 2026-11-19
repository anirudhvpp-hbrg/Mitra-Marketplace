"""A meeting as it happens.

`mitra-ear` (Rust, a few megabytes) records two tracks in half-minute pieces: `mic` is you, `sys` is
whatever the computer plays, which in a call is everyone else. This module turns each finished
piece into lines of a live transcript, and when the meeting ends puts the pieces together into one
recording for the full pipeline (speakers, the accurate speech model, notes).

Memory stays flat for any length: one piece is handled at a time, nothing is held between pieces,
and everything written so far is on disk, so a meeting of three hours costs what one of three
minutes does and a crash loses at most the half minute in hand.
"""
import json
import os
import re
import shutil
import subprocess
import time
import wave
from array import array
from pathlib import Path

from . import library, memory, models, paths, work

LIVE = paths.HOME / "run" / "live"
RECORDINGS = paths.HOME / "twinmind" / "recordings"
EAR = str(paths.ROOT / "bin" / ("mitra-ear.exe" if os.name == "nt" else "mitra-ear"))
PIECE_S = 30
QUIET = 45           # a piece whose average loudness is below this (of 32767) is silence: no model is run for it
FAINT = 150          # below this a piece is faint, and a stock phrase heard on it is the model filling silence
CARRY_MAX = 14.0     # the most of a piece's end, in seconds, that is heard again with the next piece
_STOCK = re.compile(r"^\W*(thank you|thanks|thanks for watching|thank you very much|okay|ok|bye|you|yeah|hmm+|so)\W*$", re.I)
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _read(f: Path, default=None):
    try:
        return json.loads(f.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write(f: Path, obj) -> None:
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
    paths.replace(tmp, f)


def current() -> dict | None:
    """The meeting being recorded now, if its worker is alive."""
    c = _read(LIVE / "current.json")
    if c and work.alive(c.get("pid")):
        return c
    return None


def owner() -> str:
    """What to call the person at this computer: the first name on the people list, else "You"."""
    p = library.people()
    return p[0]["name"] if p else "You"


def live_model() -> dict:
    """The speech model for the running transcript: the smallest one that knows many languages, so a
    piece is written in a second or two and the model is out of memory again. The memo afterwards is
    written with the accurate model. (A provisional choice: see README, "Model choices".)"""
    cap = models.catalog()["transcription"]
    rt = models.runtime_path(cap["runtime"])
    budget = paths.config()["model_budget_mb"]
    for c in sorted(cap["candidates"], key=lambda c: c["est_mb"]):
        if "en-cpp" in c["id"] or "tiny" in c["id"] or c["est_mb"] > budget:
            continue                          # English-only and the tiny models cannot follow a mixed-language call
        found = models.find_model(c["id"])
        if found:
            return {"ready": bool(rt), "model": c["id"], "file": str(found), "est_mb": c["est_mb"], "runtime_path": rt, "args": c.get("args", [])}
    return {"ready": False, "hint": "No speech model for the live transcript is on this device."}


def loud(wav: Path) -> int:
    """Average loudness of a piece (root mean square of its samples)."""
    with wave.open(str(wav), "rb") as w:
        a = array("h")
        a.frombytes(w.readframes(w.getnframes()))
    part = a[::8]
    return int((sum(x * x for x in part) / max(1, len(part))) ** 0.5)


def _with_lead(wav: Path, before: Path | None, lead: float) -> Path:
    """`wav` with the last `lead` seconds of the piece before it put in front, so a sentence that ran
    over the join is heard whole. Returns `wav` itself when there is nothing to put in front."""
    if not before or lead <= 0.05 or not before.is_file():
        return wav
    out = wav.with_name(wav.stem + "-lead.wav")
    with wave.open(str(before), "rb") as b, wave.open(str(wav), "rb") as w, wave.open(str(out), "wb") as o:
        o.setnchannels(1)
        o.setsampwidth(2)
        o.setframerate(w.getframerate())
        n = min(b.getnframes(), int(lead * b.getframerate()))
        b.setpos(b.getnframes() - n)
        o.writeframes(b.readframes(n))
        o.writeframes(w.readframes(w.getnframes()))
    return out


def hear_piece(app: str, p: dict, wav: Path, before: Path | None = None, lead: float = 0.0, last: bool = False) -> tuple[list[dict], float]:
    """One piece through the live speech model. Returns (lines, held): `lines` are [{start, end, text}]
    in seconds from this piece's own start (negative for words carried over from the piece before);
    `held` is how many seconds of this piece's end were left for the next piece to hear whole."""
    src = _with_lead(wav, before, lead)
    lead = lead if src != wav else 0.0
    with wave.open(str(wav), "rb") as w:
        length = w.getnframes() / w.getframerate()
    out = src.with_suffix("")
    lang, _ = models.transcribe_plan(p)
    try:
        models._run_model(app, p, [p["runtime_path"], "-m", p["file"], "-f", str(src), "-oj", "-np", "-of", str(out),
                                   "-t", str(paths.config()["threads"]), *p.get("args", []), *lang], "the live transcript")
        data = json.loads(out.with_suffix(".json").read_text("utf-8", errors="replace"))
    finally:
        out.with_suffix(".json").unlink(missing_ok=True)
        if src != wav:
            src.unlink(missing_ok=True)
    faint = loud(wav) < FAINT
    lines = []
    for seg in data.get("transcription", []):
        text = models._NOISE.sub(" ", seg.get("text", "")).strip()
        if len(re.sub(r"\W+", "", text)) < 2 or (faint and _STOCK.match(text)):
            continue
        lines.append({"start": seg["offsets"]["from"] / 1000 - lead, "end": seg["offsets"]["to"] / 1000 - lead, "text": library.fix_names(text)[0]})
    held = 0.0
    if lines and not last and lines[-1]["end"] >= length - 0.4 and length - lines[-1]["start"] <= CARRY_MAX and lines[-1]["start"] > 0:
        held = length - lines[-1]["start"]          # it runs into the end: the next piece will hear it whole
        lines.pop()
    return lines, held


def record(app: str, job, title: str, attendees: str) -> dict:
    """Record until told to stop, writing the live transcript as it goes. Returns what was recorded."""
    if not Path(EAR).is_file():
        raise models.ModelUnavailable("The recorder (mitra-ear) is not built. Run the build script.")
    stamp = time.strftime("%Y-%m-%d %H%M")
    d = LIVE / time.strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": d.name, "dir": str(d), "pid": os.getpid(), "job": job.id, "title": title, "attendees": attendees, "started": time.time(), "stamp": stamp}
    _write(d / "meeting.json", meta)
    LIVE.mkdir(parents=True, exist_ok=True)
    _write(LIVE / "current.json", meta)
    ear = subprocess.Popen([EAR, "record", "--dir", str(d), "--segment", str(PIECE_S)], stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_NOWIN)
    memory.log(app, "live.start", {"id": d.name})
    p = live_model()
    names = list(dict.fromkeys([a.strip() for a in attendees.split(",") if a.strip()] + library.known_names(library.index(RECORDINGS, refresh=False))))
    me, n, lines_n, last, held = owner(), 1, 0, {}, {}
    job.state.update(live={"id": d.name, "seconds": 0, "pieces": 0, "lines": 0, "model": p.get("model"), "state": "recording"})
    job.step("record", "running", "listening")
    try:
        while True:
            st = _read(d / "status.json", {})
            ended = ear.poll() is not None
            ready = [(t, d / f"{t}-{n:04d}.wav") for t in ("mic", "sys")]
            have = [(t, f) for t, f in ready if f.is_file()]
            # a piece is ready when both tracks have it, or the recorder has ended
            tracks = len(st.get("tracks") or []) or 2
            if have and (len(have) >= tracks or ended):
                new = []
                for t, f in have:
                    try:
                        before, lead = (d / f"{t}-{n - 1:04d}.wav", held.get(t, 0.0)) if n > 1 else (None, 0.0)
                        held[t] = 0.0
                        if (loudness_of := loud(f)) >= QUIET or lead:
                            if p.get("ready"):
                                got, held[t] = hear_piece(app, p, f, before, lead, last=ended and not (d / f"{t}-{n + 1:04d}.wav").is_file())
                                for l in got:
                                    new.append({"t": round(max(0.0, (n - 1) * PIECE_S + l["start"]), 1), "who": me if t == "mic" else "Others", "text": l["text"]})
                    except (models.MemoryDenied, models.Stopped, RuntimeError) as e:
                        last["note"] = f"piece {n}: the live transcript skipped it ({str(e)[:120]}); the recording itself is safe"
                new.sort(key=lambda l: l["t"])
                with open(d / "live.jsonl", "a", encoding="utf-8") as fh:
                    for l in new:
                        fh.write(json.dumps(l, ensure_ascii=False) + "\n")
                lines_n += len(new)
                n += 1
                continue                      # catch up before sleeping, if pieces are waiting
            if ended and not have:
                break
            job.state["live"].update(seconds=st.get("seconds", 0), pieces=n - 1, lines=lines_n, levels={t["name"]: t["level"] for t in st.get("tracks") or []},
                                     problems=st.get("problems") or [], note=last.get("note", ""))
            job.step("record", "running", f"{st.get('seconds', 0) // 60} min recorded, {lines_n} lines so far")
            time.sleep(1.0)
    finally:
        if ear.poll() is None:              # we are stopping for another reason: end the recording cleanly
            (d / "stop").write_text("", "utf-8")
            try:
                ear.wait(timeout=8)
            except Exception:
                ear.kill()
        (LIVE / "current.json").unlink(missing_ok=True)
    err = (ear.stderr.read() or b"").decode("utf-8", errors="replace").strip()
    secs = (_read(d / "status.json", {}) or {}).get("seconds", 0)
    job.state["live"].update(state="ended", seconds=secs, pieces=n - 1, lines=lines_n)
    job.step("record", "done", f"{secs // 60} min {secs % 60} s recorded, {lines_n} lines in the live transcript" + (f"; recorder said: {err[:120]}" if err else ""))
    memory.log(app, "live.end", {"id": d.name, "seconds": secs, "pieces": n - 1, "lines": lines_n})
    return {**meta, "seconds": secs, "pieces": n - 1}


def assemble(d: Path, title: str) -> dict:
    """Put the pieces together: one file per track and one mix of both, for the full pipeline.
    Read and written a piece at a time, so a three-hour meeting needs no more memory than a short one."""
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    meta = _read(d / "meeting.json", {}) or {}
    safe = re.sub(r"\s+", " ", re.sub(r"[^\w \-]+", " ", title or "Meeting"))[:50].strip() or "Meeting"
    base = RECORDINGS / f"{meta.get('stamp') or time.strftime('%Y-%m-%d %H%M')} {safe}"
    pieces = sorted({int(f.stem.split("-")[1]) for f in d.glob("*-[0-9][0-9][0-9][0-9].wav")})
    if not pieces:
        raise ValueError("Nothing was recorded.")
    out = {t: wave.open(str(base) + f".{t}.wav", "wb") for t in ("mic", "sys", "mix")}
    for w in out.values():
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
    try:
        for n in pieces:
            got = {}
            for t in ("mic", "sys"):
                f = d / f"{t}-{n:04d}.wav"
                a = array("h")
                if f.is_file():
                    with wave.open(str(f), "rb") as w:
                        a.frombytes(w.readframes(w.getnframes()))
                got[t] = a
            size = max(len(got["mic"]), len(got["sys"]))
            for t in ("mic", "sys"):
                got[t].extend([0] * (size - len(got[t])))
                out[t].writeframes(got[t].tobytes())
            out["mix"].writeframes(array("h", (max(-32768, min(32767, a + b)) for a, b in zip(got["mic"], got["sys"]))).tobytes())
    finally:
        for w in out.values():
            w.close()
    shutil.copyfile(d / "live.jsonl", str(base) + ".live.jsonl") if (d / "live.jsonl").is_file() else None
    (d / "assembled").write_text(str(base), "utf-8")
    for f in d.glob("*-[0-9][0-9][0-9][0-9].wav"):      # the pieces are now in the three files above
        f.unlink(missing_ok=True)
    return {"mix": str(base) + ".mix.wav", "mic": str(base) + ".mic.wav", "sys": str(base) + ".sys.wav", "base": str(base)}


def loudness(wav: Path) -> list[int]:
    """Loudness of each second of a track, read a second at a time."""
    out = []
    with wave.open(str(wav), "rb") as w:
        rate = w.getframerate()
        while True:
            a = array("h")
            a.frombytes(w.readframes(rate))
            if not a:
                return out
            out.append(sum(abs(x) for x in a[::16]) // max(1, len(a[::16])))


def owner_speaker(turns: list[dict], mic: Path, sys_: Path) -> str | None:
    """Which diarized speaker is the person at this computer: the one whose turns are loud on the
    microphone track and quiet on the system track. None if nobody clearly is."""
    try:
        m, s = loudness(mic), loudness(sys_)
    except (OSError, wave.Error):
        return None
    score: dict[str, list[int]] = {}
    for t in turns:
        for sec in range(int(t["start"]), min(int(t["end"]) + 1, len(m), len(s))):
            mine = m[sec] > 60 and m[sec] > s[sec] * 1.5
            theirs = s[sec] > 60 and s[sec] > m[sec] * 1.5
            if mine or theirs:
                c = score.setdefault(t["speaker"], [0, 0])
                c[0 if mine else 1] += 1
    best = max(score.items(), key=lambda kv: kv[1][0], default=None)
    if not best or best[1][0] < 5 or best[1][0] < best[1][1] * 2:
        return None
    return best[0]


def tail(meeting_id: str, after: int = 0) -> dict:
    """Lines of the live transcript from line `after` on, and the recorder's status."""
    d = LIVE / re.sub(r"[^0-9\-]", "", meeting_id)
    lines = []
    try:
        with open(d / "live.jsonl", encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh.read().splitlines()[after:] if l.strip()]
    except OSError:
        pass
    return {"lines": lines, "next": after + len(lines), "status": _read(d / "status.json", {})}


def unassembled() -> list[dict]:
    """Recordings that ended without their memo being started (the app was closed mid-meeting)."""
    out = []
    cur = (current() or {}).get("id")
    for d in sorted(LIVE.glob("*/")) if LIVE.is_dir() else []:
        meta = _read(d / "meeting.json")
        if meta and d.name != cur and not (d / "assembled").exists() and list(d.glob("*-0001.wav")):
            out.append({"id": d.name, "title": meta.get("title") or "", "started": meta.get("started"), "pieces": len(list(d.glob("sys-*.wav"))) or len(list(d.glob("mic-*.wav")))})
    return out


def tidy(keep_days: int | None = None) -> int:
    """Recordings are kept for `keep_recordings_days` (30 unless set), then go to the Recycle Bin."""
    days = keep_days if keep_days is not None else int(paths.config().get("keep_recordings_days", 30))
    n = 0
    for f in RECORDINGS.glob("*.wav") if RECORDINGS.is_dir() else []:
        if time.time() - f.stat().st_mtime > days * 86400:
            work.recycle(f)
            n += 1
    return n

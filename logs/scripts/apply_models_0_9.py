"""0.9.0 changes to workers/mitra_workers/models.py:
  - every model start says what it is for and whether it is a question (goes first) or a long job
  - diarize and transcribe save each finished window / piece through a Work store and skip saved ones
  - transcribe takes a speed ("accurate" or "fast") and steps down from the piece that was refused
  - someone_waiting(): is another app in line for the model
Run once from the project root: python logs/scripts/apply_models_0_9.py
"""
from pathlib import Path

f = Path("workers/mitra_workers/models.py")
s = f.read_text("utf-8")


def rep(a, b, n=1):
    global s
    assert s.count(a) == n, (s.count(a), a[:70])
    s = s.replace(a, b)


rep('''def governed(app: str, name: str, est_mb: int, cmd: list[str], hold=False, timeout=3600, budget_mb=None) -> list[str]:
    g = [paths.GOVERNOR, "run", "--app", app, "--name", name, "--est-mb", str(est_mb), "--timeout", str(timeout)]''',
    '''def someone_waiting() -> list[dict]:
    """Who is in line for the model right now (another app's question, say)."""
    return governor_status().get("line") or []


def governed(app: str, name: str, est_mb: int, cmd: list[str], hold=False, timeout=3600, budget_mb=None,
             priority: str = "background", what: str = "") -> list[str]:
    """`priority` "interactive" is a person waiting for an answer: it goes ahead of long jobs in the
    line for the model. `what` says in a few words what the model is doing, for the System page."""
    g = [paths.GOVERNOR, "run", "--app", app, "--name", name, "--est-mb", str(est_mb), "--timeout", str(timeout),
         "--priority", priority, "--what", what]''')

rep('''    def __init__(self, app: str, model: str | None = None, budget_mb: int | None = None, extra_args: list | None = None,
                 capability: str = "assistant"):
        self.app, self.budget_mb = app, budget_mb''',
    '''    def __init__(self, app: str, model: str | None = None, budget_mb: int | None = None, extra_args: list | None = None,
                 capability: str = "assistant", priority: str = "background", what: str = ""):
        self.app, self.budget_mb, self.priority, self.what = app, budget_mb, priority, what''')
rep('''            hold=True, timeout=1800, budget_mb=self.budget_mb)''',
    '''            hold=True, timeout=1800, budget_mb=self.budget_mb, priority=self.priority, what=self.what)''')
# waiting in line for the model is not loading: the 90 seconds start when the model is ours
rep('''            for _ in range(900):  # up to 90 s for a first load from a cold disk
                if self.proc.poll() is not None:
                    _raise_for(self.proc.returncode, errlog.read_text("utf-8", errors="replace"))''',
    '''            left = 900            # up to 90 s for a first load from a cold disk, counted once the model is ours
            while left > 0:
                if self.proc.poll() is not None:
                    _raise_for(self.proc.returncode or 1, errlog.read_text("utf-8", errors="replace"))
                if _in_line(self.proc.pid):
                    time.sleep(0.3)
                    continue
                left -= 1''')
rep('''                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("The model did not finish loading within 90 seconds.")''',
    '''                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("The model did not finish loading within 90 seconds.")
            self.waited_ms = round((time.perf_counter() - t0) * 1000) - (900 - left) * 100''')
rep('''        self.load_ms = round((time.perf_counter() - t0) * 1000)
        return self''', '''        self.load_ms = round((time.perf_counter() - t0) * 1000)
        return self''')
rep('''def ask(app: str, prompt: str, system: str | None = None, max_tokens=400, history: list | None = None) -> dict:
    """One question to the assistant: load, answer, unload."""
    with Assistant(app) as a:
        return a.chat(prompt, system, max_tokens, history=history)''',
    '''def ask(app: str, prompt: str, system: str | None = None, max_tokens=400, history: list | None = None) -> dict:
    """One question to the assistant: wait for a turn if a long job has the model, load, answer, unload."""
    with Assistant(app, priority="interactive", what="a question") as a:
        out = a.chat(prompt, system, max_tokens, history=history)
        waited = max(0, getattr(a, "waited_ms", 0))
        out.update(waited_ms=waited, ms=out["ms"] - waited)
        return out


def _in_line(pid: int) -> bool:
    """True while the governor with this pid is still waiting for the model."""
    try:
        return any(t.name.endswith(f"-{pid}.json") for t in (paths.HOME / "run" / "line").iterdir())
    except OSError:
        return False''')

rep('''def _run_model(app: str, p: dict, cmd: list[str]) -> subprocess.CompletedProcess:''',
    '''def _run_model(app: str, p: dict, cmd: list[str], what: str = "") -> subprocess.CompletedProcess:''')
rep('''        return subprocess.run(governed(app, p["model"], p["est_mb"], cmd, budget_mb=budget), capture_output=True, text=True,''',
    '''        return subprocess.run(governed(app, p["model"], p["est_mb"], cmd, budget_mb=budget, what=what), capture_output=True, text=True,''')

# ---- diarize -------------------------------------------------------------------------------
a0 = s.index("def diarize(app: str, wav: Path, progress=None) -> list[dict]:")
a1 = s.index("DIAR_WINDOW_S, DIAR_OVERLAP_S = 300.0, 45.0")
s = s[:a0] + '''def diarize(app: str, wav: Path, progress=None, work=None) -> list[dict]:
    """Who spoke when, with NVIDIA Sortformer in audio.cpp. `wav` must be 16 kHz mono (see prepare_wav).
    With `work` (a work.Work store) every finished window is saved, and saved windows are not heard again."""
    p = pick("diarization")
    if not p["ready"]:
        raise ModelUnavailable(p.get("hint", "Diarization is not available."))
    import wave

    def listen(piece: Path, what: str) -> list[dict]:
        out = paths.HOME / "tmp" / f"turns-{int(time.time() * 1000)}.json"
        try:
            _run_model(app, p, [
                p["runtime_path"], "--task", "diar", "--family", "nemotron_3_diar", "--model", p["file"],
                "--model-spec-override", "embedded",  # the GGUF carries its own spec; no config.json beside it
                "--mode", "streaming",                # measured: same turns as offline, a third less memory
                *DIAR_ARENA,
                "--backend", "cpu", "--threads", str(paths.config()["threads"]), "--audio", str(piece), "--turns-out", str(out)], what)
            return parse_turns(json.loads(out.read_text("utf-8", errors="replace")))
        finally:
            out.unlink(missing_ok=True)

    total = wav_seconds(wav)
    # A long recording is heard in windows that overlap, so memory stays the same for any length.
    # Each window numbers its speakers afresh; the overlap is what ties them to the ones before.
    windows = diar_windows(total)
    piece_dir = paths.HOME / "tmp" / f"windows-{int(time.time() * 1000)}"
    piece_dir.mkdir(parents=True, exist_ok=True)
    merged: list[dict] = []
    try:
        for n, (s0, e0) in enumerate(windows):
            local = work.load(f"turns-{n:04d}") if work else None
            if local is None:
                if work:
                    work.check()
                what = f"who speaks when, part {n + 1} of {len(windows)}" if len(windows) > 1 else "who speaks when"
                if progress:
                    progress("listening for " + what if len(windows) > 1 else "listening for who speaks")
                if len(windows) == 1:
                    heard = listen(wav, what)
                else:
                    piece = piece_dir / f"w{n:04d}.wav"
                    with wave.open(str(wav), "rb") as src:
                        _write_piece(src, s0, e0, piece)
                    heard = listen(piece, what)
                    piece.unlink(missing_ok=True)
                local = [{"start": t["start"] + s0, "end": t["end"] + s0, "speaker": t["speaker"]} for t in heard]
                if work:
                    work.save(f"turns-{n:04d}", local)
            if work:
                work.tick("diarize", n + 1, len(windows))
            # what both windows heard runs from this window's start to the previous window's end
            merged = link_windows(merged, local, s0, windows[n - 1][1]) if n else local
        return merged
    finally:
        shutil.rmtree(piece_dir, ignore_errors=True)


''' + s[a1:]

# ---- transcribe ----------------------------------------------------------------------------
b0 = s.index("def transcribe(app: str, audio: Path, wav_ready: bool = False")
b1 = s.index("def transcribe_turns(app: str, wav: Path")
s = s[:b0] + '''def transcription_choice(speed: str = "accurate", skip: tuple = ()) -> dict:
    """The speech model for a speed. "accurate" is the first candidate this device can run; "fast"
    is the next one down (smaller, quicker, less exact). With only one model here, both are that one."""
    p = pick("transcription", exclude=skip)
    if speed == "fast" and p["ready"]:
        smaller = pick("transcription", exclude=skip + (p["model"],))
        if smaller["ready"]:
            return smaller
    return p


def transcribe(app: str, audio: Path, wav_ready: bool = False, progress=None, turns: list[dict] | None = None,
               info: dict | None = None, _skip: tuple = (), work=None, speed: str = "accurate") -> list[dict]:
    """Speech to text with whisper.cpp. Returns [{start, end, text[, speaker]}].

    The recording is transcribed in pieces of at most PIECE_S seconds, cut in pauses, so the memory
    needed does not grow with the length of the meeting, and each piece is heard whole so the model
    has the conversation around every word. With `turns` (from `diarize`), every clause is given to
    the speaker who was talking then. `info`, if given, receives the model, language and notes.
    With `work` (a work.Work store) every finished piece is saved and saved pieces are not heard again."""
    import wave
    p = transcription_choice(speed, _skip)
    if not p["ready"]:
        raise ModelUnavailable(p.get("hint", "Transcription is not available."))
    wav, made = (audio, False) if wav_ready else prepare_wav(audio)
    piece_dir = paths.HOME / "tmp" / f"pieces-{int(time.time() * 1000)}"
    piece_dir.mkdir(parents=True, exist_ok=True)
    stepped = _skip[-1] if _skip else None
    try:
        cuts = work.load("cuts") if work else None
        if not cuts:
            with wave.open(str(wav), "rb") as src:
                total = src.getnframes() / float(src.getframerate())
                cuts = [0.0]
                while total - cuts[-1] > PIECE_S * 1.25:
                    cuts.append(_quiet_point(src, cuts[-1] + PIECE_S))
                cuts.append(total)
            if work:
                work.save("cuts", cuts)
        n_pieces = len(cuts) - 1
        words, langs, used = [], [], []
        for i in range(n_pieces):
            got = work.load(f"words-{i:04d}") if work else None
            while got is None:
                if work:
                    work.check()
                lang_args, _ = transcribe_plan(p)
                what = f"what was said, piece {i + 1} of {n_pieces}" if n_pieces > 1 else "what was said"
                if progress:
                    progress(f"{p['model']}, part {i + 1} of {n_pieces}" if n_pieces > 1 else p["model"])
                f = piece_dir / f"p{i:04d}.wav"
                with wave.open(str(wav), "rb") as src:
                    _write_piece(src, cuts[i], cuts[i + 1], f)
                try:
                    _run_model(app, p, [p["runtime_path"], "-m", p["file"], "-f", str(f), "-oj", "-np", "-of", str(piece_dir / f"p{i:04d}"),
                                        "-t", str(paths.config()["threads"]), "-ml", "1", "-sow", *p.get("args", []), *lang_args], what)
                except MemoryDenied as e:
                    # The first-choice speech model sits close to the ceiling. If this device could not
                    # give it the memory, the next one down carries on from this piece and the memo says so.
                    smaller = pick("transcription", exclude=_skip + tuple(dict.fromkeys(used + [p["model"]])))
                    if not smaller["ready"] or smaller["model"] == p["model"]:
                        raise
                    memory.log(app, "model.fallback", {"from": p["model"], "to": smaller["model"], "piece": i + 1, "why": str(e)[:200]})
                    stepped, _skip, p = stepped or p["model"], _skip + (p["model"],), smaller
                    continue
                finally:
                    f.unlink(missing_ok=True)
                data = json.loads((piece_dir / f"p{i:04d}.json").read_text("utf-8", errors="replace"))
                got = {"model": p["model"], "lang": (data.get("result") or {}).get("language") or "", "words": []}
                for seg in data.get("transcription", []):
                    text = _NOISE.sub(" ", seg.get("text", "")).strip()
                    if text:
                        got["words"].append({"start": cuts[i] + seg["offsets"]["from"] / 1000, "end": cuts[i] + seg["offsets"]["to"] / 1000, "text": text})
                (piece_dir / f"p{i:04d}.json").unlink(missing_ok=True)
                if work:
                    work.save(f"words-{i:04d}", got)
            words += got["words"]
            langs.append(got["lang"])
            used.append(got["model"])
            if work:
                work.tick("transcribe", i + 1, n_pieces)
        if info is not None:
            lang_args, lang_note = transcribe_plan(p)
            if stepped:
                info["stepped_down_from"] = stepped
            heard = sorted({l for l in langs if l})
            info.update(model=" then ".join(dict.fromkeys(used)) or p["model"], language=", ".join(heard) or "unknown", note=lang_note,
                        pieces=n_pieces, translated="-tr" in lang_args and any(l != "en" for l in heard))
        return words_to_lines(words, turns)
    finally:
        shutil.rmtree(piece_dir, ignore_errors=True)
        if made:
            wav.unlink(missing_ok=True)


''' + s[b1:]
f.write_text(s, "utf-8")
print("ok")

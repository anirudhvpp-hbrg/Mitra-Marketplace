"""Capabilities and the models behind them.

An app never names a model. It names a capability ("assistant", "transcription"); `pick()`
chooses the first catalog candidate that exists in models_dir and fits the model budget.
Every model process is started through the Rust governor, which enforces the budget, allows
one model at a time, and stops the model the moment this worker is finished with it.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# socket and urllib are imported inside Assistant: they cost about 6 MB and most requests
# (listing apps, converting a file, reading the log) never talk to a model.

from . import memory, paths

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ModelUnavailable(Exception):
    pass


class MemoryDenied(Exception):
    pass


class Stopped(Exception):
    """The model was stopped by hand: from the System page, or because its app was closed."""


def catalog() -> dict:
    cat = json.loads((paths.ROOT / "catalog.json").read_text("utf-8"))
    return {k: v for k, v in cat.items() if not k.startswith("_")}


def find_model(folder: str, patterns=("*.gguf", "ggml-*.bin", "*.onnx")) -> Path | None:
    """A model is a folder name holding one weights file: first inside the package (<root>/models,
    filled by `mitra-marketplace models sync`), then somewhere under models_dir (band/category/name)."""
    pkg = paths.ROOT / "models" / folder
    if pkg.is_dir():
        for pat in patterns:
            files = sorted(pkg.glob(pat), key=lambda f: f.stat().st_size, reverse=True)
            if files:
                return files[0]
    base = Path(paths.config()["models_dir"])
    # Searching a large model library on every request is slow, so the answer is remembered
    # in a small file and trusted only while the weights file it points at still exists.
    index_file = paths.HOME / "run" / "model-index.json"
    try:
        index = json.loads(index_file.read_text("utf-8"))
    except Exception:
        index = {}
    key = f"{base}|{folder}"
    if key in index and (index[key] is None or Path(index[key]).is_file()):
        if index[key] is not None or time.time() - index.get("_checked", {}).get(key, 0) < 600:
            return Path(index[key]) if index[key] else None
    found = None
    for depth in ("", "*/", "*/*/", "*/*/*/"):
        for d in base.glob(depth + folder):
            if d.is_dir() and not found:
                for pat in patterns:
                    files = sorted(d.rglob(pat), key=lambda f: f.stat().st_size, reverse=True)
                    if files:
                        found = files[0]
                        break
        if found:
            break
    index[key] = str(found) if found else None
    index.setdefault("_checked", {})[key] = time.time()
    try:
        index_file.parent.mkdir(parents=True, exist_ok=True)
        index_file.write_text(json.dumps(index), "utf-8")
    except OSError:
        pass
    return found


def runtime_path(runtime: str) -> str | None:
    cfg = paths.config()
    if runtime == "llama-server":
        if cfg["llama_server"] and Path(cfg["llama_server"]).exists():
            return cfg["llama_server"]
        local = sorted((paths.ROOT / "runtimes" / "llama").glob("llama-server*"))
        if local:
            return str(local[0])
        found = shutil.which("llama-server")
        if found:
            return found
        bundled = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/lib/ollama/llama-server.exe",
                   Path("/Applications/Ollama.app/Contents/Resources/llama-server"), Path("/usr/lib/ollama/llama-server")]
        return next((str(p) for p in bundled if p.is_file()), None)
    if runtime == "whisper.cpp":
        if cfg["whisper_cli"] and Path(cfg["whisper_cli"]).exists():
            return cfg["whisper_cli"]
        local = sorted((paths.ROOT / "runtimes").glob("whisper.cpp/**/whisper-cli*"))
        return shutil.which("whisper-cli") or shutil.which("whisper-cpp") or (str(local[0]) if local else None)
    if runtime == "audio.cpp":
        if cfg.get("audiocpp_cli") and Path(cfg["audiocpp_cli"]).exists():
            return cfg["audiocpp_cli"]
        local = sorted((paths.ROOT / "runtimes").glob("audio.cpp/**/audiocpp_cli*"))
        return shutil.which("audiocpp_cli") or (str(local[0]) if local else None)
    return None


def pick(capability: str, exclude: tuple = ()) -> dict:
    """What would run for this capability on this device, and whether it can.
    `exclude` names candidates to pass over (used to step down to a smaller model)."""
    cap = catalog().get(capability)
    if not cap:
        return {"capability": capability, "ready": False, "hint": "Unknown capability"}
    budget = paths.config()["model_budget_mb"]
    rt = runtime_path(cap["runtime"])
    out = {"capability": capability, "purpose": cap["purpose"], "runtime": cap["runtime"], "ready": False}
    skipped = None
    for c in cap["candidates"]:
        if c["id"] in exclude:
            continue
        f = find_model(c["id"])
        if not f:
            continue
        if c["est_mb"] > budget:
            skipped = skipped or c
            continue
        out.update(model=c["id"], file=str(f), est_mb=c["est_mb"], why=c["why"], contract=c.get("contract", "generic"), args=c.get("args", []))
        if skipped:
            out["passed_over"] = f"{skipped['id']} needs {skipped['est_mb']} MB; the budget is {budget} MB."
        if rt:
            out.update(ready=True, runtime_path=rt)
        else:
            out["hint"] = f"Model is on disk; the {cap['runtime']} runtime is not installed."
        return out
    if skipped:
        out["hint"] = f"{skipped['id']} is on disk but needs about {skipped['est_mb']} MB; the budget is {budget} MB."
    else:
        out["hint"] = f"No candidate model found in {paths.config()['models_dir']}."
    return out


def governor_status() -> dict:
    try:
        out = subprocess.run([paths.GOVERNOR, "status"], capture_output=True, text=True, timeout=10, creationflags=_NOWIN).stdout
        return json.loads(out)
    except Exception as e:
        return {"error": str(e), "ram": {}, "leases": [], "limits": {}}


def someone_waiting() -> list[dict]:
    """Who is in line for the model right now (another app's question, say)."""
    return governor_status().get("line") or []


def governed(app: str, name: str, est_mb: int, cmd: list[str], hold=False, timeout=3600, budget_mb=None,
             priority: str = "background", what: str = "") -> list[str]:
    """`priority` "interactive" is a person waiting for an answer: it goes ahead of long jobs in the
    line for the model. `what` says in a few words what the model is doing, for the System page."""
    g = [paths.GOVERNOR, "run", "--app", app, "--name", name, "--est-mb", str(est_mb), "--timeout", str(timeout),
         "--priority", priority, "--what", what]
    if not budget_mb and est_mb:
        # Each model is held to what it was measured to need plus 10%, not to the global ceiling:
        # a 150 MB transcriber that starts using 600 MB is stopped, even though 600 is under the ceiling.
        budget_mb = min(paths.config()["model_budget_mb"], int(est_mb * 1.1) + 10)
    if budget_mb:
        g += ["--budget-mb", str(budget_mb)]
    return g + (["--hold-stdin"] if hold else []) + ["--"] + cmd


def _raise_for(code: int, err: str):
    tail = "\n".join(l for l in err.strip().splitlines() if l.startswith("[governor]")) or err.strip()[-400:]
    if code == 143:
        raise Stopped("The model was stopped by hand before it finished.")
    if code in (75, 137):
        raise MemoryDenied(tail.replace("[governor] ", "") or "The governor stopped the model.")
    if "mem_buffer != NULL" in err or "bad_alloc" in err or "failed to allocate" in err.lower():
        # The runtime asked the system for memory and was refused. That is the whole system being at
        # its limit (other programs), not this model going over its budget, so say that plainly.
        raise MemoryDenied("The system had no memory left to give this model (other programs are using nearly all of it). "
                           "Close something large and run it again.")
    raise RuntimeError(tail or f"model process exited with code {code}")


class Assistant:
    """The assistant model, held for the length of a `with` block and unloaded on exit.

    One question: `with Assistant(app) as a: a.chat(...)`. A pipeline with several steps keeps
    the same block open so the model loads once. `model` and `budget_mb` exist for measuring a
    candidate; normal use takes whatever `pick()` chose.
    """

    def __init__(self, app: str, model: str | None = None, budget_mb: int | None = None, extra_args: list | None = None,
                 capability: str = "assistant", priority: str = "background", what: str = ""):
        self.app, self.budget_mb, self.priority, self.what = app, budget_mb, priority, what
        # memory-saving server options; measured with logs/scripts/bench_llama_flags.py
        self.extra = list(extra_args if extra_args is not None else paths.config()["assistant_args"])
        self.p = pick(capability)
        if model:
            f = find_model(model)
            if not f:
                raise ModelUnavailable(f"{model} is not in {paths.config()['models_dir']}")
            self.p = {"ready": True, "model": model, "file": str(f), "est_mb": 0, "runtime_path": runtime_path("llama-server")}
        if not self.p["ready"]:
            raise ModelUnavailable(self.p.get("hint", "Assistant model is not available."))
        self.model, self.proc, self.url, self.load_ms = self.p["model"], None, None, 0

    def __enter__(self):
        import socket
        import urllib.request
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        cfg = paths.config()
        cmd = governed(self.app, self.model, self.p["est_mb"], [
            self.p["runtime_path"], "-m", self.p["file"], "--host", "127.0.0.1", "--port", str(port),
            "-c", str(cfg["assistant_ctx"]), "-t", str(cfg["threads"]), "--parallel", "1",
            "-ngl", "0",  # CPU only: the same footprint on every device, no GPU runtime in RAM
            *self.extra],
            hold=True, timeout=1800, budget_mb=self.budget_mb, priority=self.priority, what=self.what)
        errlog = paths.HOME / "run" / "llama-server.log"
        errlog.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        with open(errlog, "w", encoding="utf-8") as ef:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=ef, creationflags=_NOWIN)
        self.url = f"http://127.0.0.1:{port}"
        try:
            got = None
            left = 900            # up to 90 s for a first load from a cold disk, counted once the model is ours
            while left > 0:
                if self.proc.poll() is not None:
                    _raise_for(self.proc.returncode or 1, errlog.read_text("utf-8", errors="replace"))
                if not _holds_model(self.proc.pid):
                    time.sleep(0.2)
                    continue
                if got is None:
                    got = time.perf_counter()
                left -= 1
                try:
                    with urllib.request.urlopen(self.url + "/health", timeout=1) as r:
                        if r.status == 200:
                            break
                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("The model did not finish loading within 90 seconds.")
            self.waited_ms = round(((got or t0) - t0) * 1000)
        except Exception as e:
            memory.log(self.app, "error", {"msg": f"assistant: {e}"})
            self.__exit__(None, None, None)
            raise
        self.load_ms = round((time.perf_counter() - t0) * 1000)
        return self

    def chat(self, prompt: str, system: str | None = None, max_tokens=400, temperature=0.3, schema: dict | None = None,
             history: list | None = None) -> dict:
        """`schema` forces the reply to be JSON of that shape (the server constrains generation).
        `history` is earlier turns as [{"role": "user"|"assistant", "content": ...}]; passing them as
        real turns, not pasted into the question, stops a small model repeating its last answer."""
        import urllib.request
        t0 = time.perf_counter()
        past = [{"role": h["role"], "content": str(h["content"])[:1200]} for h in (history or [])
                if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content")][-4:]
        messages = ([{"role": "system", "content": system}] if system else []) + past + [{"role": "user", "content": prompt}]
        body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}
        if self.model.startswith("qwen3"):
            body["chat_template_kwargs"] = {"enable_thinking": False}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                res = json.loads(r.read())
        except Exception as e:
            try:
                self.proc.wait(timeout=3)     # give the governor a moment to report why the model went away
            except Exception:
                pass
            if self.proc.poll() is not None:  # the governor stopped it mid-answer
                _raise_for(self.proc.returncode, (paths.HOME / "run" / "llama-server.log").read_text("utf-8", errors="replace"))
            memory.log(self.app, "error", {"msg": f"assistant: {e}"})
            raise
        text = re.sub(r"<think>.*?</think>", "", res["choices"][0]["message"].get("content") or "", flags=re.S).strip()
        mb = (governor_status().get("leases") or [{}])[0].get("mb")
        ms = round((time.perf_counter() - t0) * 1000)
        memory.log(self.app, "model.call", {"model": self.model, "ms": ms, "mb": mb,
                                            "tokens_out": (res.get("usage") or {}).get("completion_tokens")})
        return {"text": text, "model": self.model, "ms": ms + self.load_ms, "load_ms": self.load_ms, "mb": mb}

    def __exit__(self, *exc):
        try:
            self.proc.stdin.close()   # releasing the pipe tells the governor to stop the model
            self.proc.wait(timeout=15)
        except Exception:
            self.proc.kill()
        return False


def ask(app: str, prompt: str, system: str | None = None, max_tokens=400, history: list | None = None) -> dict:
    """One question to the assistant: wait for a turn if a long job has the model, load, answer, unload."""
    with Assistant(app, priority="interactive", what="a question") as a:
        out = a.chat(prompt, system, max_tokens, history=history)
        waited = max(0, getattr(a, "waited_ms", 0))
        out.update(waited_ms=waited, ms=out["ms"] - waited)
        return out


def _holds_model(pid: int) -> bool:
    """True once the governor with this pid has the model lock (until then it is waiting its turn)."""
    try:
        return json.loads((paths.HOME / "run" / "model.lock").read_text("utf-8")).get("governor_pid") == pid
    except (OSError, ValueError):
        return False


def _run_model(app: str, p: dict, cmd: list[str], what: str = "") -> subprocess.CompletedProcess:
    """Run one audio model to completion under the governor.

    Each model is first held to its own measured need. If it is stopped for going over that, and the
    device-wide ceiling still has room, it is run once more held only to the ceiling, and the event
    is logged so the estimate can be corrected. The ceiling itself is never exceeded."""
    def once(budget):
        return subprocess.run(governed(app, p["model"], p["est_mb"], cmd, budget_mb=budget, what=what), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=_NOWIN)
    r = once(None)
    ceiling = paths.config()["model_budget_mb"]
    own = int(p["est_mb"] * 1.1) + 10
    if r.returncode == 137 and own < ceiling:
        memory.log(app, "model.cap_raised", {"model": p["model"], "own_cap_mb": own, "ceiling_mb": ceiling,
                                             "why": "stopped over its own cap; run again held to the ceiling"})
        r = once(ceiling)
    if r.returncode != 0:
        _raise_for(r.returncode, r.stderr or r.stdout)
    return r


def wav_seconds(wav: Path) -> float:
    import wave
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def audio_seconds(audio: Path) -> float | None:
    """How long a recording is, without converting it: the WAV header, or what ffmpeg reports."""
    try:
        if audio.suffix.lower() == ".wav":
            return wav_seconds(audio)
    except Exception:
        pass
    cfg_ff = paths.config().get("ffmpeg")
    ffmpeg = cfg_ff if cfg_ff and Path(cfg_ff).exists() else shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(audio)], capture_output=True, text=True, errors="replace", creationflags=_NOWIN)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def _quiet_point(src, around: float, span: float = 4.0) -> float:
    """The quietest tenth of a second within `span` seconds either side of `around`, so a cut
    between two pieces of a recording lands in a pause, not in the middle of a word."""
    from array import array
    rate, total = src.getframerate(), src.getnframes()
    a = max(0, int((around - span) * rate))
    z = min(total, int((around + span) * rate))
    if src.getsampwidth() != 2 or z - a < rate // 5:
        return around
    src.setpos(a)
    data = array("h")
    data.frombytes(src.readframes(z - a))
    hop, best, at = rate // 10, None, around
    for i in range(0, len(data) - hop, hop):
        level = sum(abs(x) for x in data[i:i + hop:8])
        if best is None or level < best:
            best, at = level, (a + i + hop // 2) / rate
    return at


def _write_piece(src, start: float, end: float, out: Path) -> None:
    import wave
    rate = src.getframerate()
    a, z = max(0, int(start * rate)), min(src.getnframes(), int(end * rate))
    src.setpos(a)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(src.getnchannels())
        w.setsampwidth(src.getsampwidth())
        w.setframerate(rate)
        left = z - a
        while left > 0:                       # copied a few seconds at a time; the recording is never held whole
            n = min(left, rate * 20)
            w.writeframes(src.readframes(n))
            left -= n


def prepare_wav(audio: Path) -> tuple[Path, bool]:
    """16 kHz mono WAV, which both the transcriber and the diarizer want. Returns (path, made):
    `made` is True when a temporary file was created and the caller should delete it."""
    cfg_ff = paths.config().get("ffmpeg")
    ffmpeg = cfg_ff if cfg_ff and Path(cfg_ff).exists() else shutil.which("ffmpeg")
    if not ffmpeg:
        if audio.suffix.lower() == ".wav":
            return audio, False
        raise ModelUnavailable("This audio is not WAV and ffmpeg is not installed to convert it.")
    wav = paths.HOME / "tmp" / f"{audio.stem}-{int(time.time())}.16k.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    conv = subprocess.run([ffmpeg, "-y", "-i", str(audio), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
                          capture_output=True, text=True, errors="replace", creationflags=_NOWIN)
    if conv.returncode != 0:
        raise RuntimeError("ffmpeg could not read this file: " + conv.stderr.strip()[-300:])
    return wav, True


def _num(d: dict, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                pass
    return None


def parse_turns(data) -> list[dict]:
    """Speaker turns from a diarizer's JSON, whatever it names its fields: [{start, end, speaker}],
    seconds, with speakers renamed 'Speaker 1', 'Speaker 2' in order of first appearance."""
    if isinstance(data, dict):
        data = next((data[k] for k in ("turns", "speaker_turns", "segments", "results") if isinstance(data.get(k), list)), [])
    names, out = {}, []
    for t in data if isinstance(data, list) else []:
        if not isinstance(t, dict):
            continue
        start = _num(t, "start", "start_s", "start_sec", "start_time", "begin", "t0")
        end = _num(t, "end", "end_s", "end_sec", "end_time", "finish", "t1")
        if start is None and _num(t, "start_ms") is not None:
            start, end = _num(t, "start_ms") / 1000, (_num(t, "end_ms") or 0) / 1000
        if start is None and _num(t, "start_sample") is not None:   # audio.cpp: samples at 16 kHz
            rate = _num(t, "sample_rate") or 16000.0
            start, end = _num(t, "start_sample") / rate, (_num(t, "end_sample") or 0) / rate
        spk = next((t[k] for k in ("speaker", "speaker_id", "speaker_label", "label", "id") if t.get(k) is not None), None)
        if start is None or end is None or spk is None or end <= start:
            continue
        names.setdefault(str(spk), f"Speaker {len(names) + 1}")
        out.append({"start": start, "end": end, "speaker": names[str(spk)]})
    return sorted(out, key=lambda t: t["start"])


def diarize(app: str, wav: Path, progress=None, work=None) -> list[dict]:
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


DIAR_WINDOW_S, DIAR_OVERLAP_S = 300.0, 45.0
# The runtime's graph_arena_mb / weight_context_mb options were tried on 2026-11-12 to shrink the
# 3.2 GB it reserves at start; this build ignores them (logs/scripts/measure_diar_options.ps1).
DIAR_ARENA: list[str] = []


def diar_windows(total: float) -> list[tuple[float, float]]:
    """(start, end) of each window for a recording `total` seconds long: one window if it is short,
    otherwise windows of DIAR_WINDOW_S that each begin DIAR_OVERLAP_S before the last one ended."""
    if total <= DIAR_WINDOW_S * 1.2:
        return [(0.0, total)]
    step = DIAR_WINDOW_S - DIAR_OVERLAP_S
    out, a = [], 0.0
    while a + DIAR_WINDOW_S < total:
        out.append((a, a + DIAR_WINDOW_S))
        a += step
    # The last window is a full one ending at the end, not a short stub: a stub of under a minute
    # was measured to hear two voices as one, and then everything after the join took one name.
    out.append((max(0.0, total - DIAR_WINDOW_S), total))
    return out


def link_windows(before: list[dict], local: list[dict], o0: float, o1: float) -> list[dict]:
    """Join a new window's turns onto the turns so far. `o0..o1` is the stretch both heard.

    A new window's speaker takes the name of the earlier speaker it shares the most speaking time
    with inside that stretch. A speaker who was silent there is matched by elimination when exactly
    one earlier speaker is also unmatched; otherwise it gets a new number, because guessing would
    put one person's words under another's name. The earlier turns are kept up to the middle of the
    overlap and the new window's from there on."""
    def share(a, b):
        return max(0.0, min(a["end"], b["end"], o1) - max(a["start"], b["start"], o0))
    old_names = list(dict.fromkeys(t["speaker"] for t in before))
    new_names = list(dict.fromkeys(t["speaker"] for t in local))
    pairs = sorted(((sum(share(a, b) for a in before if a["speaker"] == o for b in local if b["speaker"] == n), n, o)
                    for n in new_names for o in old_names), reverse=True)
    names: dict[str, str] = {}
    for secs, n, o in pairs:
        if secs >= 0.4 and n not in names and o not in names.values():
            names[n] = o
    recent = list(dict.fromkeys(t["speaker"] for t in before if t["end"] > o0 - 240))   # who has spoken lately
    free_new = [n for n in new_names if n not in names]
    free_old = [o for o in recent if o not in names.values()]
    if len(free_new) == 1 and len(free_old) == 1:
        names[free_new[0]] = free_old[0]
    count = len(old_names)
    for n in new_names:
        if n not in names:
            count += 1
            names[n] = f"Speaker {count}"
    mid = (o0 + o1) / 2
    out = []
    for t in before:
        if t["start"] < mid:
            out.append({**t, "end": min(t["end"], mid)})
    for t in local:
        if t["end"] > mid:
            out.append({"start": max(t["start"], mid), "end": t["end"], "speaker": names[t["speaker"]]})
    return [t for t in out if t["end"] - t["start"] > 0.05]


def assign_speakers(segments: list[dict], turns: list[dict]) -> int:
    """Give each transcript segment the speaker whose turn overlaps it most. Returns how many were labelled."""
    done = 0
    for s in segments:
        best, most = None, 0.0
        for t in turns:
            overlap = min(s["end"], t["end"]) - max(s["start"], t["start"])
            if overlap > most:
                best, most = t["speaker"], overlap
        if best:
            s["speaker"] = best
            done += 1
    return done


def speaker_blocks(turns: list[dict], join_gap: float = 1.2, max_len: float = 28.0) -> list[dict]:
    """Merge a speaker's consecutive turns into one block (a breath is not a new line), keeping
    blocks under Whisper's 30-second window so each is transcribed in one piece."""
    blocks = []
    for t in turns:
        last = blocks[-1] if blocks else None
        if last and last["speaker"] == t["speaker"] and t["start"] - last["end"] <= join_gap and t["end"] - last["start"] <= max_len:
            last["end"] = t["end"]
        else:
            blocks.append(dict(t))
    return [b for b in blocks if b["end"] - b["start"] >= 0.25]


PIECE_S = 300.0     # transcription piece, seconds
_NOISE = re.compile(r"\s*\[[^\]]{0,40}\]\s*|\s*\((silence|music|laughs?|laughter|inaudible|applause|speaking in (a )?foreign language)[^)]*\)\s*", re.I)
_END = re.compile(r"[.?!][\"')\]]*$")
_CLAUSE = re.compile(r"[,;:.?!][\"')\]]*$")


def transcribe_plan(p: dict) -> tuple[list[str], str]:
    """How the transcriber is asked to treat language. `transcribe_language` in the config is
    "english" (the default: whatever is spoken comes out in English, so a meeting that moves between
    Hindi and English reads as one transcript), "original" (keep each language as spoken), or a
    language code such as "hi". A model that only knows English ignores it."""
    if ".en" in Path(p["file"]).name:
        return [], "English-only model"
    want = str(paths.config().get("transcribe_language") or "english").lower()
    if want == "english":
        return ["-l", "auto", "-tr"], "written in English whatever was spoken"
    if want == "original":
        return ["-l", "auto"], "kept in the language spoken"
    return ["-l", want], f"language set to {want}"


def _dedupe_words(words: list[dict]) -> list[dict]:
    """A speech model that loses its place repeats itself ("then, then, then ..."). More than two
    of the same word in a row is that, not speech."""
    out = []
    for w in words:
        key = re.sub(r"\W+", "", w["text"].lower())
        if key and len(out) >= 2 and all(re.sub(r"\W+", "", o["text"].lower()) == key for o in out[-2:]):
            out[-1]["end"] = w["end"]
            continue
        out.append(w)
    return out


def words_to_lines(words: list[dict], turns: list[dict] | None = None, max_s: float = 30.0, max_chars: int = 380) -> list[dict]:
    """Timed words into transcript lines. With speaker turns, each sentence goes to the speaker who was
    talking for most of it, and a line ends when the speaker changes; without, lines are sentences."""
    words = _dedupe_words([w for w in words if w["text"].strip()])
    if not words:
        return []

    def who(w):
        best, most = None, 0.0
        for t in turns or []:
            if t["start"] > w["end"] + 0.6:
                break
            share = min(w["end"], t["end"]) - max(w["start"], t["start"])
            if share <= 0:      # a word the diarizer heard no one say: lean to the nearest turn
                gap = max(t["start"] - w["end"], w["start"] - t["end"])
                share = 0.02 if gap < 0.6 else 0.0
            if share > most:
                best, most = t["speaker"], share
        return best, most

    clauses, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 9.0
        # The unit is the sentence. Word timings are only approximate (more so when the model is
        # translating), so a clause of two or three words is too short to place on its own; measured
        # on a real call, clause units put "Yeah," and "No," at the end of the other person's line.
        long_clause = len(cur) >= 14 and _CLAUSE.search(w["text"].strip())
        if _END.search(w["text"].strip()) or gap > 1.5 or long_clause or len(cur) >= 60:
            clauses.append(cur)
            cur = []
    if cur:
        clauses.append(cur)
    units = []
    for c in clauses:
        tally: dict[str, float] = {}
        for w in c:
            s, share = who(w)
            if s:
                tally[s] = tally.get(s, 0.0) + share
        units.append({"start": c[0]["start"], "end": c[-1]["end"], "text": " ".join(w["text"].strip() for w in c),
                      "speaker": max(tally, key=tally.get) if tally else None, "n": len(c),
                      "stop": bool(_END.search(c[-1]["text"].strip()))})
    if turns:
        for i, u in enumerate(units):               # a clause no turn covers stays with whoever was speaking
            if u["speaker"] is None:
                u["speaker"] = units[i - 1]["speaker"] if i else next((x["speaker"] for x in units if x["speaker"]), None)
        for i in range(1, len(units) - 1):          # one or two words mid-sentence flipping speaker is timing jitter
            a, u, z = units[i - 1], units[i], units[i + 1]
            if u["n"] <= 2 and not u["stop"] and not a["stop"] and a["speaker"] == z["speaker"] != u["speaker"]:
                u["speaker"] = a["speaker"]
    lines = []
    for u in units:
        last = lines[-1] if lines else None
        same = last and last["speaker"] == u["speaker"]
        fits = last and u["end"] - last["start"] <= max_s and len(last["text"]) + len(u["text"]) < max_chars
        if same and fits and (turns or not last["stop"] or len(last["text"]) < 140) and u["start"] - last["end"] < 4.0:
            last["end"], last["text"], last["stop"] = u["end"], last["text"] + " " + u["text"], u["stop"]
        else:
            lines.append({"start": u["start"], "end": u["end"], "text": u["text"], "speaker": u["speaker"], "stop": u["stop"]})
    out, seen = [], []
    for l in lines:
        key = re.sub(r"\W+", " ", l["text"].lower()).strip()
        if key and seen[-2:] == [key, key]:          # the same line three times running is the model looping
            continue
        seen.append(key)
        d = {"start": l["start"], "end": l["end"], "text": l["text"]}
        if l["speaker"]:
            d["speaker"] = l["speaker"]
        out.append(d)
    return out


def transcription_choice(speed: str = "accurate", skip: tuple = ()) -> dict:
    """The speech model for a speed. "accurate" is the first candidate this device can run; "fast"
    is the next one down (smaller, quicker, less exact). With only one model here, both are that one."""
    p = pick("transcription", exclude=skip)
    if speed == "fast" and p["ready"]:
        smaller = pick("transcription", exclude=skip + (p["model"],))
        if smaller["ready"]:
            return smaller
    return p


def transcribe(app: str, audio: Path, wav_ready: bool = False, progress=None, turns: list[dict] | None = None,
               info: dict | None = None, _skip: tuple = (), work=None, speed: str = "accurate", names: list | None = None) -> list[dict]:
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
                if names:       # the people likely to be named, so the model spells them as they are spelt
                    lang_args = lang_args + ["--prompt", "People in this meeting or mentioned in it: " + ", ".join(names[:40]) + "."]
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


def transcribe_turns(app: str, wav: Path, turns: list[dict], progress=None) -> list[dict]:
    """Kept for callers of the earlier name: transcription with speakers."""
    return transcribe(app, wav, wav_ready=True, progress=progress, turns=turns)

"""Measure what the two audio models really need on a real recording, by length.

    python logs/scripts/measure_audio_memory.py "<recording>" [minutes ...]

For each length (the recording is looped or cut to that many minutes) it runs the diarizer and the
transcriber on the whole file with the per-model cap lifted to the global ceiling, and prints the
peak the governor saw and the seconds taken. Prints numbers only, never what was said.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import models, paths  # noqa: E402

CEIL = int(sys.argv[sys.argv.index("--ceil") + 1]) if "--ceil" in sys.argv else 2000
_orig = models.governed
models.governed = lambda *a, **k: _orig(*a, **{**k, "budget_mb": CEIL})


def last_run(name_part: str, since: float) -> dict:
    files = sorted((paths.HOME / "memory" / "events").glob("*.jsonl"))[-2:]
    best = {}
    for f in files:
        for line in f.read_text("utf-8", errors="replace").splitlines():
            if '"model.run"' in line and name_part in line:
                best = json.loads(line)["data"]
    return best


def make(src: Path, minutes: float) -> Path:
    out = paths.HOME / "tmp" / f"measure-{minutes:g}min.16k.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", str(minutes * 60),
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out)], check=True)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != str(CEIL)]
    src = Path(args[0])
    lengths = [float(x) for x in args[1:]] or [1, 4]
    only = "diar" if "--diar" in sys.argv else "asr" if "--asr" in sys.argv else "both"
    print(f"ceiling for this measurement: {CEIL} MB")
    for m in lengths:
        wav = make(src, m)
        row = [f"{m:g} min"]
        if only in ("both", "diar"):
            t = time.time()
            try:
                turns = models.diarize("measure", wav)
                d = last_run("nemotron", t)
                row.append(f"diarize peak {d.get('peak_mb')} MB, {time.time() - t:.0f} s, {len(turns)} turns, "
                           f"{len({x['speaker'] for x in turns})} speakers")
            except Exception as e:
                d = last_run("nemotron", t)
                row.append(f"diarize FAILED at peak {d.get('peak_mb')} MB: {str(e)[:140]}")
        if only in ("both", "asr"):
            t = time.time()
            try:
                segs = models.transcribe("measure", wav, wav_ready=True)
                d = last_run("whisper", t)
                row.append(f"transcribe peak {d.get('peak_mb')} MB, {time.time() - t:.0f} s, {len(segs)} lines, "
                           f"{sum(len(s['text']) for s in segs)} chars")
            except Exception as e:
                d = last_run("whisper", t)
                row.append(f"transcribe FAILED at peak {d.get('peak_mb')} MB: {str(e)[:140]}")
        print(" | ".join(row), flush=True)
        wav.unlink(missing_ok=True)


main()

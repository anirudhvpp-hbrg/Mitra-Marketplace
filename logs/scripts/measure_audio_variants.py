"""Try runtime options for the two audio models on a real recording and report peak memory.

    python logs/scripts/measure_audio_variants.py "<recording>" <minutes> diar|asr

Prints numbers only (peak MB, seconds, counts), never what was said.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import models, paths  # noqa: E402

TMP = paths.HOME / "tmp"


def peak(name_part: str) -> dict:
    best = {}
    for f in sorted((paths.HOME / "memory" / "events").glob("*.jsonl"))[-2:]:
        for line in f.read_text("utf-8", errors="replace").splitlines():
            if '"model.run"' in line and name_part in line:
                best = json.loads(line)["data"]
    return best


def run(name: str, cmd: list[str]):
    g = models.governed("measure", name, 100, cmd, budget_mb=2000)
    t = time.time()
    r = subprocess.run(g, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r, time.time() - t, peak(name)


def main():
    src, minutes, what = Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
    wav = TMP / f"variants-{minutes:g}.16k.wav"
    TMP.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", str(minutes * 60),
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
    th = str(paths.config()["threads"])
    if what == "diar":
        p = models.pick("diarization")
        base = [p["runtime_path"], "--task", "diar", "--family", "nemotron_3_diar", "--model", p["file"],
                "--model-spec-override", "embedded", "--backend", "cpu", "--audio", str(wav)]
        variants = [("offline, %s threads" % th, ["--threads", th]),
                    ("streaming, %s threads" % th, ["--threads", th, "--mode", "streaming"]),
                    ("streaming, 4 threads", ["--threads", "4", "--mode", "streaming"])]
        if "--stream-only" in sys.argv:
            variants = variants[1:2]
        for label, extra in variants:
            out = TMP / "variants-turns.json"
            out.unlink(missing_ok=True)
            r, secs, d = run("nemotron-variant", base + extra + ["--turns-out", str(out)])
            turns = models.parse_turns(json.loads(out.read_text("utf-8"))) if out.exists() else []
            print(f"{minutes:g} min | {label}: exit {r.returncode}, peak {d.get('peak_mb')} MB, {secs:.0f} s, "
                  f"{len(turns)} turns, {len({t['speaker'] for t in turns})} speakers"
                  + ("" if r.returncode == 0 else " | " + (r.stderr or r.stdout).strip()[-200:].replace("\n", " ")), flush=True)
    else:
        p = models.pick("transcription")
        base = [p["runtime_path"], "-m", p["file"], "-f", str(wav), "-oj", "-of", str(TMP / "variants-asr"), "-np"]
        for label, extra in [("default beam 5, %s threads" % th, ["-t", th]),
                             ("default beam 5, %s threads (again)" % th, ["-t", th]),
                             ("beam 5, 4 threads", ["-t", "4"]),
                             ("beam 2 best-of 2, 4 threads", ["-t", "4", "-bs", "2", "-bo", "2"]),
                             ("greedy (beam 1, best-of 1), 4 threads", ["-t", "4", "-bs", "1", "-bo", "1"]),
                             ("greedy, %s threads" % th, ["-t", th, "-bs", "1", "-bo", "1"])]:
            r, secs, d = run("whisper-variant", base + extra)
            n = 0
            f = TMP / "variants-asr.json"
            if f.exists():
                n = sum(len(s["text"]) for s in json.loads(f.read_text("utf-8", errors="replace")).get("transcription", []))
                f.unlink()
            print(f"{minutes:g} min | {label}: exit {r.returncode}, peak {d.get('peak_mb')} MB, {secs:.0f} s, {n} chars", flush=True)
    wav.unlink(missing_ok=True)


main()

"""Compare speech models and language settings on one real recording.

    python logs/scripts/compare_transcribers.py "<recording>" [--seconds N]

For each candidate it prints peak memory, seconds and character count, and writes the text to
~/.mitra/tmp/compare/<label>.txt so the wording can be read side by side. Nothing leaves the device.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import models, paths  # noqa: E402

OUT = paths.HOME / "tmp" / "compare"
LIB = Path(paths.config()["models_dir"])


def peak(name):
    best = {}
    for f in sorted((paths.HOME / "memory" / "events").glob("*.jsonl"))[-2:]:
        for line in f.read_text("utf-8", errors="replace").splitlines():
            if '"model.run"' in line and name in line:
                best = json.loads(line)["data"]
    return best


def main():
    src = Path(sys.argv[1])
    secs = sys.argv[sys.argv.index("--seconds") + 1] if "--seconds" in sys.argv else None
    OUT.mkdir(parents=True, exist_ok=True)
    wav = OUT / "input.16k.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), *(["-t", secs] if secs else []),
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
    exe = models.runtime_path("whisper.cpp") or models.pick("transcription")["runtime_path"]
    th = str(paths.config()["threads"])
    cands = []
    for folder, tag in [("whisper-tiny-en-cpp", "tiny.en"), ("whisper-tiny-multilingual", "tiny"),
                        ("whisper-base-q5_1-cpp", "base-q5"), ("whisper-small-q5_1-cpp", "small-q5"),
                        ("whisper-small-multilingual-cpp", "small"), ("whisper-medium-q5_0-cpp", "medium-q5"), ("whisper-small-en-cpp", "small.en"),
                        ("whisper-large-v3-turbo-q5_0-cpp", "turbo-q5")]:
        f = models.find_model(folder)
        if not f:
            continue
        if tag.endswith(".en"):
            cands.append((f"{tag}", f, []))
        else:
            cands += [(f"{tag}-auto", f, ["-l", "auto"]), (f"{tag}-translate", f, ["-l", "auto", "-tr"]),
                      (f"{tag}-en", f, ["-l", "en"])]
    more = sys.argv[sys.argv.index("--extra") + 1].split() if "--extra" in sys.argv else []   # e.g. --extra "-bs 1 -bo 1"
    cands = [(l, f, e + more) for l, f, e in cands]
    only = [a for a in sys.argv[2:] if not a.startswith("--") and a != secs and a != " ".join(more)]
    for label, f, extra in cands:
        if only and not any(o in label for o in only):
            continue
        base = OUT / label
        g = models.governed("measure", "cmp-" + label, 100, [exe, "-m", str(f), "-f", str(wav), "-oj", "-np", "-of", str(base),
                                                             "-t", th, *extra], budget_mb=2000)
        t = time.time()
        r = subprocess.run(g, capture_output=True, text=True, encoding="utf-8", errors="replace")
        d = peak("cmp-" + label)
        j = Path(str(base) + ".json")
        text = ""
        if j.exists():
            data = json.loads(j.read_text("utf-8", errors="replace"))
            text = "\n".join(f"[{s['offsets']['from'] // 1000:4d}s] {s['text'].strip()}" for s in data.get("transcription", []))
            lang = (data.get("result") or {}).get("language")
            j.unlink()
        else:
            lang = None
        (OUT / f"{label}.txt").write_text(text, "utf-8")
        print(f"{label:<18} exit {r.returncode} peak {d.get('peak_mb')} MB, {time.time() - t:.0f} s, {len(text)} chars, language {lang}", flush=True)
    wav.unlink(missing_ok=True)


main()

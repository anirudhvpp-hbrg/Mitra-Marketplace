"""Run the diarizer on one recording and show exactly what it returns.

    python logs/scripts/try_diarization.py <audio file>

Prints the head of the raw turns file (to check the field names the parser relies on), the
parsed speaker turns, the transcript with speakers merged in, and the RAM and time the
governor recorded for each model.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import memory, models, paths  # noqa: E402

audio = Path(sys.argv[1])
p = models.pick("diarization")
print("diarization:", {k: p.get(k) for k in ("model", "ready", "runtime_path", "hint")})
wav, made = models.prepare_wav(audio)
try:
    raw_out = paths.HOME / "tmp" / "turns-raw.json"
    cmd = models.governed("try-diar", p["model"], 0, [
        p["runtime_path"], "--task", "diar", "--family", "nemotron_3_diar", "--model", p["file"], "--model-spec-override", "embedded", "--backend", "cpu",
        "--threads", str(paths.config()["threads"]), "--audio", str(wav), "--turns-out", str(raw_out)], budget_mb=4000)
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"exit {r.returncode} in {time.perf_counter() - t0:.1f} s")
    if r.returncode != 0:
        print("stderr tail:\n" + (r.stderr or r.stdout)[-1500:])
        sys.exit(1)
    raw = raw_out.read_text("utf-8", errors="replace")
    print("--- raw turns file (first 700 characters)\n" + raw[:700])
    turns = models.parse_turns(json.loads(raw))
    print(f"--- parsed: {len(turns)} turns, {len({t['speaker'] for t in turns})} speakers")
    for t in turns:
        print(f"  {t['start']:6.2f} - {t['end']:6.2f}  {t['speaker']}")
    segs = models.transcribe_turns("try-diar", wav, turns)
    print(f"--- transcript, one speaker turn at a time ({len(models.speaker_blocks(turns))} blocks)")
    for s in segs:
        print(f"  [{s['start']:5.1f}] {s.get('speaker', '?'):<10} {s['text']}")
    time.sleep(0.6)
    print("--- governor")
    for e in memory.read(1):
        if e["type"] == "model.run" and e["app"] == "try-diar":
            d = e["data"]
            print(f"  {d['name']}: peak {d['peak_mb']} MB, {d['ms']} ms, end {d['end']}")
finally:
    if made:
        wav.unlink(missing_ok=True)

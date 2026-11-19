"""Does giving the speech model a list of names cost memory? (2026-11-20)

    python logs/scripts/measure_prompt_memory.py <five-minute 16 kHz mono wav>

Runs the accurate speech model on the same five-minute piece three times under the governor (cap
raised to 1,300 MB so nothing is stopped): with no prompt, with three names, with forty names. Prints
each run's peak memory from the memory log. Found because the suite's long recording peaked at
1,066 MB, over the 1,024 MB ceiling, after the names prompt was added.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
from mitra_workers import models, paths  # noqa: E402

piece = Path(sys.argv[1])
p = models.pick("transcription")
log = paths.HOME / "memory" / "events" / (time.strftime("%Y-%m-%d") + ".jsonl")


def run(label, extra):
    cmd = [p["runtime_path"], "-m", p["file"], "-f", str(piece), "-oj", "-np", "-of", str(piece.with_suffix("")), "-t", str(paths.config()["threads"]),
           "-ml", "1", "-sow", *p["args"], "-l", "auto", "-tr", *extra]
    r = subprocess.run(models.governed("measure", p["model"], p["est_mb"], cmd, budget_mb=1300, what=label), capture_output=True, text=True)
    runs = [json.loads(l) for l in open(log, encoding="utf-8") if '"measure"' in l and '"model.run"' in l]
    words = len(json.loads(piece.with_suffix(".json").read_text("utf-8", errors="replace")).get("transcription", [])) if r.returncode == 0 else 0
    print(f"{label:<10} exit {r.returncode}  peak {runs[-1]['data']['peak_mb']} MB  {round(runs[-1]['data']['ms'] / 1000)} s  {words} words", flush=True)


lead = "People in this meeting or mentioned in it: "
run("no prompt", [])
run("3 names", ["--prompt", lead + "Priya, Sam, Dana."])
run("40 names", ["--prompt", lead + ", ".join(["Anirudh"] + [f"Person{i}" for i in range(39)]) + "."])
piece.with_suffix(".json").unlink(missing_ok=True)

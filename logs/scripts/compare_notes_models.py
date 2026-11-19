"""Compare notes models on a real memo's transcript.

    python logs/scripts/compare_notes_models.py "<memo.md>" <model-folder> [<model-folder> ...] [--ceiling 1000] [--sections N]

Takes the transcript appendix of a memo TwinMind already wrote, runs each candidate through the
same section-by-section notes step the app uses (prompts, guards and merge unchanged), and prints
for each: peak memory, seconds, and the notes that survive the grounding check. Nothing is saved
and nothing leaves the device.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import meeting, models, paths  # noqa: E402


def peak(name):
    best = {}
    for f in sorted((paths.HOME / "memory" / "events").glob("*.jsonl"))[-2:]:
        for line in f.read_text("utf-8", errors="replace").splitlines():
            if '"model.run"' in line and name in line:
                best = json.loads(line)["data"]
    return best


def main():
    args = [a for a in sys.argv[1:]]
    ceiling = int(args[args.index("--ceiling") + 1]) if "--ceiling" in args else 1000
    limit = int(args[args.index("--sections") + 1]) if "--sections" in args else 99
    extra = args[args.index("--args") + 1].split() if "--args" in args else None
    skip = set()
    for flag in ("--ceiling", "--sections", "--args"):
        if flag in args:
            skip |= {args.index(flag), args.index(flag) + 1}
    plain = [a for i, a in enumerate(args) if i not in skip]
    memo, cands = Path(plain[0]), plain[1:]
    lines = [l for l in memo.read_text("utf-8").split("Appendix: Transcript", 1)[1].splitlines() if l.strip()]
    sections = meeting.chunk(lines)[:limit]
    print(f"{len(lines)} transcript lines, {len(sections)} sections; ceiling {ceiling} MB")
    for cand in cands:
        print(f"\n================ {cand}")
        t0 = time.time()
        try:
            with models.Assistant("measure", model=cand, budget_mb=ceiling, extra_args=extra) as a:
                results = [meeting.understand(a, sec, i) for i, sec in enumerate(sections)]
        except Exception as e:
            d = peak(cand)
            print(f"FAILED at peak {d.get('peak_mb')} MB: {str(e)[:300]}")
            continue
        d = peak(cand)
        notes = meeting.merge(results)
        print(f"peak {d.get('peak_mb')} MB, {time.time() - t0:.0f} s for {len(sections)} sections")
        print("title:", notes["title"])
        print("topics:", notes["topics"])
        for k in ("points", "decisions", "open_questions"):
            print(f"{k}:")
            for x in notes[k]:
                print(f"   [{x['section']}] {x['text']}")
        print("actions:")
        for x in notes["actions"]:
            print(f"   [{x['section']}] {x['owner'] or 'Unassigned'}: {x['task']}" + (f" (due {x['due']})" if x["due"] else ""))
        echo = [f for f in notes["flags"] if "copied from the transcript" in f or "is not a task" in f or "says nothing" in f]
        print(f"removed by the check: {len(notes['flags'])} ({len(echo)} echoes)")
        for f in notes["flags"]:
            if f not in echo:
                print("   ", f[:160])


main()

"""Compare models on the meeting-notes task: grounded notes, action items, RAM and time.

    python logs/scripts/bench_meeting_notes.py [model-folder ...]

Default: your Mitra Ear fine-tune (trained on this exact prompt contract) against Qwen3 0.6B.
Each model reads the same test standup; the output shown is after the grounding guards, with
whatever they removed listed as flags.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import meeting, memory, models  # noqa: E402

TRANSCRIPT = """00:00 Priya: Morning everyone. Quick standup. Let's start with the invoice export.
00:08 Sam: The export job is done for PDF. CSV still fails on invoices with more than two hundred line items, it times out after thirty seconds.
00:21 Sam: The query loads every line item into memory before writing. I can stream it instead. I think that is one day of work.
00:30 Priya: Okay. Sam, please fix the CSV timeout by Thursday.
00:35 Dana: The new onboarding screens are in review. Two comments from design about the colour contrast on the second screen. I will address them today.
00:47 Dana: If the CSV fix lands by Thursday we keep the twentieth. If not we slip to the twenty-fourth.
00:55 Priya: Decision then: release stays on the twentieth, with the twenty-fourth as fallback.
01:02 Sam: The staging database is at ninety percent disk. Someone needs to clear old snapshots.
01:10 Dana: I will clear snapshots older than thirty days this afternoon.
01:16 Priya: I will send the release note draft to marketing by Wednesday."""

CONTRACTS = {"gemma-3-270m-mitra-ear": "mind-v1"}
for model in sys.argv[1:] or ["gemma-3-270m-mitra-ear", "qwen3-0.6b-q4_k_m"]:
    tag = f"bench:{model}"
    try:
        t0 = time.perf_counter()
        with models.Assistant(tag, model=model, budget_mb=4000) as a:
            a.p["contract"] = CONTRACTS.get(model, "generic")
            r = meeting.understand(a, TRANSCRIPT)
        secs = time.perf_counter() - t0
        time.sleep(0.6)
        peak = [e["data"]["peak_mb"] for e in memory.read(1) if e["type"] == "model.run" and e["app"] == tag][-1]
        n = r["notes"]
        print(f"\n===== {model}: peak {peak} MB, {secs:.1f} s, contract {a.p['contract']}")
        print(f"title: {r['title']}\ntopic: {n['topic']}")
        for k in ("points", "decisions", "open_questions"):
            print(f"{k}:")
            for b in n[k] or ["(none)"]:
                print(f"   - {b}")
        print("actions:")
        for act in r["actions"] or [{"owner": "", "task": "(none)", "due": None}]:
            print(f"   - {act['owner'] or 'unassigned'}: {act['task']}" + (f"  [due {act['due']}]" if act["due"] else ""))
        print("removed by the guards:")
        for f in r["flags"] or ["(nothing)"]:
            print(f"   ! {f}")
    except Exception as e:
        print(f"\n===== {model}: FAILED: {type(e).__name__}: {e}")

"""Find the llama-server settings that make a model use the least RAM without hurting answers.

    python logs/scripts/bench_llama_flags.py [model-folder]

Each setting is run on CPU under the governor (budget lifted so nothing is cut short). For
each one this prints the peak RAM the governor measured over the whole run, the time, and the
answer to a fixed meeting-summary question, so memory and quality can be read side by side.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import memory, models  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3-0.6b-q4_k_m"
TRANSCRIPT = """Priya: Morning everyone. Quick standup. Let's start with the invoice export.
Sam: The export job is done for PDF. CSV still fails on invoices with more than two hundred line items, it times out after thirty seconds.
Sam: The query loads every line item into memory before writing. I can stream it instead. I think that is one day of work.
Priya: Okay. Sam, please fix the CSV timeout by Thursday.
Dana: The new onboarding screens are in review. Two comments from design about the colour contrast on the second screen. I will address them today.
Dana: If the CSV fix lands by Thursday we keep the twentieth. If not we slip to the twenty-fourth.
Priya: Decision then: release stays on the twentieth, with the twenty-fourth as fallback.
Sam: The staging database is at ninety percent disk. Someone needs to clear old snapshots.
Dana: I will clear snapshots older than thirty days this afternoon.
Priya: I will send the release note draft to marketing by Wednesday."""
PROMPT = TRANSCRIPT + "\n\nSummarise this meeting in 4 short bullet points. Include any decision that was made."

SETTINGS = {
    "as shipped (ctx 2048)": [],
    "small batches": ["-b", "256", "-ub", "256"],
    "no prompt cache": ["--cache-ram", "0", "--ctx-checkpoints", "0"],
    "8-bit context cache": ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0"],
    "no warmup": ["--no-warmup"],
    "all of the above": ["-b", "256", "-ub", "256", "--cache-ram", "0", "--ctx-checkpoints", "0", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--no-warmup"],
    "all + ctx 4096": ["-b", "256", "-ub", "256", "--cache-ram", "0", "--ctx-checkpoints", "0", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--no-warmup", "-c", "4096"],
    "round2 8-bit, 4 threads": ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "-t", "4"],
    "round2 4-bit context cache": ["-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0"],
    "round2 8-bit, ctx 1536": ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "-c", "1536"],
    "round2 4-bit, ctx 1536, 4 threads": ["-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0", "-c", "1536", "-t", "4"],
    "all + ctx 1024": ["-b", "256", "-ub", "256", "--cache-ram", "0", "--ctx-checkpoints", "0", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--no-warmup", "-c", "1024"],
}

only = [a for a in sys.argv[2:]]
for name, args in SETTINGS.items():
    if only and not any(o in name for o in only):
        continue
    tag = f"bench:{name}"
    try:
        t0 = time.perf_counter()
        with models.Assistant(tag, model=MODEL, budget_mb=4000, extra_args=args) as a:
            r = a.chat(PROMPT, "You write meeting notes. Use only what the transcript says.", 200, 0.1)
        secs = time.perf_counter() - t0
        time.sleep(0.6)
        peak = [e["data"]["peak_mb"] for e in memory.read(1) if e["type"] == "model.run" and e["app"] == tag][-1]
        print(f"\n=== {name}: peak {peak} MB, {secs:.1f} s (load {r['load_ms'] / 1000:.1f} s)")
        print("    " + r["text"].replace("\n", "\n    "))
    except Exception as e:
        print(f"\n=== {name}: FAILED: {e}")

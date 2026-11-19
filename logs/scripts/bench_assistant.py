"""Measure assistant candidates: real RAM, load time, and the answer each gives.

    python logs/scripts/bench_assistant.py [model-folder ...]

Used on 2026-11-11 to pick the default assistant. Each model is loaded on CPU under the
governor with the budget lifted to 4000 MB so the measurement is not cut short; the governor
records the peak in the memory log as a model.run event for app "bench".
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import memory, models  # noqa: E402

PROMPT = "List three uses of a hash map, then explain in two sentences how collisions are handled."
candidates = sys.argv[1:] or [c["id"] for c in models.catalog()["assistant"]["candidates"]]

for model in candidates:
    try:
        with models.Assistant("bench", model=model, budget_mb=4000) as a:
            r = a.chat(PROMPT, max_tokens=200)
        print(f"{model:<28} {r['mb']} MB while answering, load {r['load_ms']} ms, total {r['ms']} ms")
        print("    " + r["text"][:240].replace("\n", " "))
    except Exception as e:
        print(f"{model:<28} FAILED: {e}")

print("\nPeaks recorded by the governor:")
for e in memory.read(1):
    if e["type"] == "model.run" and e["app"] == "bench":
        print("   ", e["ts"], json.dumps(e["data"]))

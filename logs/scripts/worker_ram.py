"""Show what each kind of request costs in worker RAM and time, from the memory log.

    python logs/scripts/worker_ram.py [days]

Reads api.call events (written by the gateway with the worker's peak RAM) and groups them by
app and route, so a route that has grown heavy stands out.
"""
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import memory  # noqa: E402

rows = defaultdict(lambda: {"n": 0, "mb": 0, "ms": 0})
for e in memory.read(int(sys.argv[1]) if len(sys.argv) > 1 else 1):
    d = e.get("data") or {}
    if e["type"] == "api.call" and d.get("worker_mb"):
        r = rows[(e["app"], d["path"].split("?")[0])]
        r["n"] += 1
        r["mb"] = max(r["mb"], d["worker_mb"])
        r["ms"] += d.get("ms", 0)

print(f"{'app':<18}{'route':<26}{'calls':>6}{'peak MB':>9}{'avg ms':>8}")
for (app, path), r in sorted(rows.items(), key=lambda kv: -kv[1]["mb"]):
    print(f"{app:<18}{path[:25]:<26}{r['n']:>6}{r['mb']:>9}{round(r['ms'] / r['n']):>8}")

"""Turn off llama.cpp's load-time weight repacking for every language model, and record what each
then measured. Repacking makes a second copy of the 4-bit weights in a layout that is faster on
CPU; measured on 2026-11-13 it costs 200 MB for Qwen3 0.6B (762 -> 564 MB) and about 70 MB for
Gemma 3 1B Q4_K_M (987 -> 915 MB), and on a 4_0 file it costs 360 MB (1192 -> 830 MB).
Run once from the project root.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]

p = root / "workers" / "mitra_workers" / "paths.py"
t = p.read_text("utf-8")
old = '"assistant_args": ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--cache-ram", "0"],'
assert old in t
p.write_text(t.replace(old, '"assistant_args": ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--cache-ram", "0", "--no-repack"],'), "utf-8")
print("edited paths.py")

c = root / "catalog.json"
t = c.read_text("utf-8")
pairs = [
    ('{"id": "qwen3-0.6b-q4_k_m", "est_mb": 750, "why": "Most accurate of the three on meeting summaries. Measured 748 MB with an 8-bit context cache and a 1536-token context (881 MB before tuning)."}',
     '{"id": "qwen3-0.6b-q4_k_m", "est_mb": 600, "why": "Most accurate of the three on meeting summaries. Measured 564 MB on 2026-11-13 with an 8-bit context cache, a 1536-token context and weight repacking off (881 MB before any tuning, 762 MB with repacking on)."}'),
    ('{"id": "gemma-3-1b-it-q4_k_m", "est_mb": 990, "contract": "generic", "why": "Gemma 3 1B (769 MB file). Measured 946 to 987 MB on two real calls on 2026-11-12/13.',
     '{"id": "gemma-3-1b-it-q4_k_m", "est_mb": 940, "contract": "generic", "why": "Gemma 3 1B (769 MB file). Measured 915 to 918 MB on two real calls on 2026-11-13 with weight repacking off (946 to 996 MB with it on).'),
    ('      {"id": "qwen3-0.6b-q4_k_m", "est_mb": 760, "contract": "generic", "why": "Measured 754 MB. On the test meeting: accurate points and four action items with owners and deadlines."},',
     '      {"id": "gemma-3-1b-it-q4_0", "est_mb": 850, "contract": "generic", "why": "The same model in a smaller file (688 MB). Measured 830 MB. Its notes on the same call were thinner than the Q4_K_M file\'s; used where the ceiling is between 860 and 940 MB. Not copied into the package."},\n'
     '      {"id": "qwen3-0.6b-q4_k_m", "est_mb": 600, "contract": "generic", "why": "Measured 564 MB. Fine on a clean written transcript; on real calls it repeats transcript lines as notes and tasks. Used where the ceiling is below 860 MB, or when the larger model is refused memory."},'),
]
for old, new in pairs:
    assert t.count(old) == 1, old[:60]
    t = t.replace(old, new)
c.write_text(t, "utf-8")
json.loads(c.read_text("utf-8"))
print("edited catalog.json")

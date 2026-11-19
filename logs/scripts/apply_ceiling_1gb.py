"""Raise the model ceiling from 800 MB to 1 GB (1,024 MB) and make Gemma 3 1B the first choice for
meeting notes. The user approved 1 GB on 2026-11-13. Run once from the project root.

Touches: the default in workers/mitra_workers/paths.py and governor/src/main.rs (rebuild after),
catalog.json, the tests that state the ceiling, and this device's ~/.mitra/config.json if it
sets model_budget_mb.
"""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]


def edit(rel, pairs):
    f = root / rel
    text = f.read_text("utf-8")
    for old, new in pairs:
        assert text.count(old) >= 1, f"{rel}: not found: {old[:70]}"
        text = text.replace(old, new)
    f.write_text(text, "utf-8")
    print("edited", rel)


edit("workers/mitra_workers/paths.py", [('"model_budget_mb": 800,', '"model_budget_mb": 1024,')])
edit("governor/src/main.rs", [('cfg(&c, "model_budget_mb", 800)', 'cfg(&c, "model_budget_mb", 1024)')])
edit("logs/tests/run_tests.py", [
    ('t.assertEqual(s["limits"]["model_budget_mb"], 800)', 't.assertEqual(s["limits"]["model_budget_mb"], 1024)'),
    ('t.assertEqual(out, ["186", "800"])', 't.assertEqual(out, ["186", "1024"])'),
    ('        t.assertLessEqual(r["budget_mb"], 800)', '        t.assertLessEqual(r["budget_mb"], 1024)'),
])

cat = root / "catalog.json"
text = cat.read_text("utf-8")
old = '      {"id": "qwen3-0.6b-q4_k_m", "est_mb": 760, "contract": "generic",'
assert text.count(old) == 1
new = ('      {"id": "gemma-3-1b-it-q4_k_m", "est_mb": 990, "contract": "generic", "why": "Gemma 3 1B (769 MB file). Measured 946 to 987 MB on '
       'two real calls on 2026-11-12/13. On those calls it wrote concrete points and real action items (share the proposal with the client by '
       'Wednesday; schedule a discovery session) where Qwen3 0.6B repeated transcript lines; it still misattributes some statements. '
       'Needs the 1 GB ceiling."},\n' + old)
cat.write_text(text.replace(old, new), "utf-8")
json.loads(cat.read_text("utf-8"))
print("edited catalog.json")

user = Path.home() / ".mitra" / "config.json"
if user.exists():
    cfg = json.loads(user.read_text("utf-8"))
    if "model_budget_mb" in cfg:
        print("this device's config had model_budget_mb =", cfg["model_budget_mb"])
        cfg["model_budget_mb"] = 1024
        user.write_text(json.dumps(cfg, indent=2), "utf-8")
        print("set to 1024 in", user)
    else:
        print("this device's config does not set model_budget_mb; the new default applies")

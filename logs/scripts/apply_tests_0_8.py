"""Add area N (TwinMind on real speech) to logs/tests/run_tests.py, before the final
"stopping everything" case so earlier case numbers do not move, and bring the older recording
case in line with the speech model now used. Run once from the project root."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
target = root / "logs" / "tests" / "run_tests.py"
text = target.read_text("utf-8")
if '@case("N",' in text:
    raise SystemExit("area N is already there")

block = (Path(__file__).parent / "area_n_block.py").read_text("utf-8")
last = '@case("K", "stopping everything leaves no app, worker or model process behind")'
assert text.count(last) == 1
text = text.replace(last, block + last)

old_areas = '"M": "files: Open with, drop to open, structure kept"}'
assert old_areas in text
text = text.replace(old_areas, '"M": "files: Open with, drop to open, structure kept", "N": "TwinMind on real speech"}')

# The recording case: caps are now each model's own measured need, not "under 250 MB".
old = ('''        t.assertLessEqual(d["peak_mb"], d["budget_mb"], f"{d['name']} peaked at {d['peak_mb']} MB")
        t.assertLessEqual(d["budget_mb"], 250)''')
assert old in text
text = text.replace(old, '''        t.assertLessEqual(d["peak_mb"], d["budget_mb"], f"{d['name']} peaked at {d['peak_mb']} MB")
        t.assertLessEqual(d["budget_mb"], 250)
        t.assertEqual(d["end"], "exit")''')
old = ('''    for run in runs:
        t.assertLessEqual(run["budget_mb"], 250)
        t.assertLessEqual(run["peak_mb"], run["budget_mb"]''')
assert old in text
text = text.replace(old, '''    ceiling = http("GET", "/api/models")[1]["budget_mb"]
    for run in runs:
        t.assertLessEqual(run["budget_mb"], ceiling)
        t.assertLessEqual(run["peak_mb"], run["budget_mb"]''')
old = '@case("L", "a recording is transcribed, with speakers, each model under its own small cap")'
assert old in text
text = text.replace(old, '@case("L", "a recording is transcribed, with speakers, each model under its own cap")')
target.write_text(text, "utf-8")
print("area N added:", block.count("@case("), "cases")

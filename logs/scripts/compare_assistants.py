"""Ask the same questions of several candidate models for Ask Mitra and print the answers side by
side, with peak memory and seconds. The answers are graded by reading, against the key below.

    python logs/scripts/compare_assistants.py <model-folder> [<model-folder> ...]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import models, paths  # noqa: E402

QUESTIONS = [
    ("What is the capital of Australia? One word.", "Canberra"),
    ("What is 17 times 23? Answer with the number only.", "391"),
    ("A train leaves at 9:40 and the journey takes 2 hours 35 minutes. When does it arrive?", "12:15"),
    ("Which is heavier, a kilogram of iron or a kilogram of cotton? One sentence.", "the same"),
    ("Rewrite politely in one sentence: 'Send me the report now.'", "polite request"),
    ("List three risks of moving a database to a new server. Short bullets.", "downtime, data loss, compatibility/performance"),
    ("Translate to English: 'Kal subah nau baje meeting hai, time par aana.'", "Meeting at nine tomorrow morning, come on time"),
    ("Summarise in one sentence: 'The export failed again on invoices above two hundred lines. Sam will fix the timeout by Thursday and the release stays on the twentieth.'", "export fails on large invoices; Sam fixes by Thursday; release stays on 20th"),
    ("If all bloops are razzies and all razzies are lazzies, are all bloops lazzies? Yes or no, with one reason.", "Yes"),
    ("Give the past tense of: go, eat, write, buy.", "went, ate, wrote, bought"),
    ("What does HTTP status 404 mean? One sentence.", "not found"),
    ("Sam has 12 apples, gives 5 to Priya and then buys 8 more. How many does Sam have?", "15"),
]


def peak(name):
    best = {}
    for f in sorted((paths.HOME / "memory" / "events").glob("*.jsonl"))[-2:]:
        for line in f.read_text("utf-8", errors="replace").splitlines():
            if '"model.run"' in line and name in line:
                best = json.loads(line)["data"]
    return best


for cand in sys.argv[1:]:
    print(f"\n================ {cand}")
    t0 = time.time()
    with models.Assistant("measure", model=cand, budget_mb=1024) as a:
        answers = [a.chat(q, None, 160, 0.2)["text"] for q, _ in QUESTIONS]
    d = peak(cand)
    print(f"peak {d.get('peak_mb')} MB, {time.time() - t0:.0f} s for {len(QUESTIONS)} questions")
    for (q, key), ans in zip(QUESTIONS, answers):
        print(f"Q: {q[:70]}\n   expected: {key}\n   answer:   {' / '.join(ans.split(chr(10)))[:260]}")

"""Show what the current notes model writes for the test suite's standup transcript: the raw
reply, then what survives parsing and the grounding check. Used when case T224 fails."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import meeting, models  # noqa: E402

src = (ROOT / "logs" / "tests" / "run_tests.py").read_text("utf-8")
T = re.search(r'^TRANSCRIPT = """(.+?)"""', src, re.S | re.M).group(1)
print(T)
print("-----")
with models.Assistant("measure", capability="meeting-notes") as a:
    print("model:", a.model)
    print(a.chat("Transcript:\n" + T, meeting.NOTES + meeting.FORMAT_HINT, 320, 0.0)["text"])
    print("-----")
    print(json.dumps(meeting.understand(a, T, 0), indent=1))

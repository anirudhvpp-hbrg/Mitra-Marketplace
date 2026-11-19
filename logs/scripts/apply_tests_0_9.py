"""Insert area O (taking turns, saved pieces, the line of recordings) into logs/tests/run_tests.py,
just before the final "stopping everything" case. Run once from the project root.
"""
from pathlib import Path

f = Path("logs/tests/run_tests.py")
s = f.read_text("utf-8")
assert "# O. taking turns" not in s, "already applied"
mark = '@case("K", "stopping everything leaves no app, worker or model process behind")'
assert s.count(mark) == 1
s = s.replace(mark, Path("logs/scripts/area_o_block.py").read_text("utf-8") + mark)
a = "  J security               K resources and the package     L real models\n"
assert s.count(a) == 1
s = s.replace(a, a + "  M, N TwinMind on real calls                               O taking turns, saved pieces, the line\n")
f.write_text(s, "utf-8")
print("ok")

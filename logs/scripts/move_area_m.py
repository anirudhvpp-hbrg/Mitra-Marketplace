"""One-off: area M was inserted after the suite's last case, which stops the test launcher.
This moves it to just before that case, so "stopping everything" stays the final case."""
import pathlib

t = pathlib.Path(__file__).resolve().parents[2] / "logs" / "tests" / "run_tests.py"
x = t.read_text("utf-8")
start = x.index("# ============================================================================================\n# M. files")
end = x.index("def main():\n")
block = x[start:end]
x = x[:start] + x[end:]
anchor = '@case("K", "stopping everything leaves no app, worker or model process behind")'
assert x.count(anchor) == 1
x = x.replace(anchor, block + anchor)
t.write_text(x, "utf-8")
print("moved")

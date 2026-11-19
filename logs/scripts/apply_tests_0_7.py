"""One-off: adds area M (files: Open with, drop to open, structure kept) to the test suite from
area_m_block.py, and makes three small corrections to the harness. Refuses to run twice."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
t = ROOT / "logs" / "tests" / "run_tests.py"
x = t.read_text("utf-8")
assert "# M. files" not in x
block = (ROOT / "logs" / "scripts" / "area_m_block.py").read_text("utf-8")


def swap(old, new):
    global x
    assert old in x, old[:60]
    x = x.replace(old, new, 1)


swap("def main():\n", block + "def main():\n")
swap('"K": "resources and package", "L": "real models"}', '"K": "resources and package", "L": "real models",\n             "M": "files: Open with, drop to open, structure kept"}')
# the harness calls the governor directly; like the gateway, it must say what the local time zone is,
# or between midnight and the UTC offset the governor writes to yesterday's log file
swap('    e["PYTHONPATH"] = str(ROOT / "workers")\n    return e\n',
     '    e["PYTHONPATH"] = str(ROOT / "workers")\n    e["MITRA_TZ_OFFSET_MIN"] = str(int(datetime.now().astimezone().utcoffset().total_seconds() // 60))\n    return e\n')
swap('_page("to-markdown", "/api/convert", "/api/upload", "/api/convert/save")', '_page("to-markdown", "/api/convert", "M.openFile", "/api/convert/save")')
t.write_text(x, "utf-8")
print("suite patched")

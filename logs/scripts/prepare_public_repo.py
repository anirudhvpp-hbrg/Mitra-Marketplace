"""Before the project is pushed to a public repository (2026-11-20): nothing about the owner's
clients, colleagues or folders stays in the source.

  - library.py: project spellings and the archive's location are read from the owner's own files
    (~/.mitra/twinmind/project_names.json and `meeting_archive` in ~/.mitra/config.json), which this
    script fills in on this machine so the app behaves as before
  - tests: made-up companies and people in the fixtures
  - .gitignore: models, runtimes, build output, binaries, the bundled APTM source zip
Run once from the project root: python logs/scripts/prepare_public_repo.py
"""
import json
import re
from pathlib import Path

HOME = Path.home() / ".mitra"

f = Path("workers/mitra_workers/library.py")
s = f.read_text("utf-8")
for a, b in [
    ('# One spelling per project: the archive has both "PWC" and "PwC".\nCANON = {"pwc": "PwC", "upgrad": "upGrad", "ey": "EY", "ust": "UST", "bnp": "BNP"}\n',
     '# One spelling per project. An archive can hold the same client written two ways; the owner\'s own\n'
     '# file (~/.mitra/twinmind/project_names.json, {"lowercase": "As It Should Be Written"}) settles it.\n'
     'NAMES = STORE / "project_names.json"\n_canon = None\n'),
    ("    return CANON.get(raw.lower(), raw)",
     "    global _canon\n    if _canon is None:\n        _canon = {str(k).lower(): str(v) for k, v in _load(NAMES, {}).items()}\n    return _canon.get(raw.lower(), raw)"),
    ('    """Where old meetings are. `meeting_archive` in the config, else the Meeting Intelligence archive in Dropbox."""\n'
     '    cfg = paths.config().get("meeting_archive")\n    if cfg:\n        p = Path(cfg).expanduser()\n        return p if p.is_dir() else None\n'
     '    root = paths.dropbox_root()\n    p = root / "0. AP Persistent AI Brain" / "Meeting Intelligence" / "normalized" if root else None\n    return p if p and p.is_dir() else None',
     '    """Where old meetings are: `meeting_archive` in ~/.mitra/config.json (a folder of transcripts, read only)."""\n'
     '    cfg = paths.config().get("meeting_archive")\n    if not cfg:\n        return None\n    p = Path(cfg).expanduser()\n    return p if p.is_dir() else None'),
]:
    assert s.count(a) == 1, a[:60]
    s = s.replace(a, b)
f.write_text(s, "utf-8")

# this machine keeps working as before: the owner's spellings and archive go in his own files
names = HOME / "twinmind" / "project_names.json"
if not names.exists():
    names.parent.mkdir(parents=True, exist_ok=True)
    names.write_text(json.dumps({"pwc": "PwC", "upgrad": "upGrad", "ey": "EY", "ust": "UST", "bnp": "BNP"}), "utf-8")
cfg_file = HOME / "config.json"
cfg = json.loads(cfg_file.read_text("utf-8-sig"))
if not cfg.get("meeting_archive"):
    import sys
    sys.path.insert(0, "workers")
    from mitra_workers import paths
    arch = paths.dropbox_root() / "0. AP Persistent AI Brain" / "Meeting Intelligence" / "normalized"
    if arch.is_dir():
        cfg["meeting_archive"] = str(arch)
        cfg_file.write_text(json.dumps(cfg, indent=2), "utf-8")

# tests and their block: made-up companies and people
swap = [("PwC Cloud Program Staffing Review", "Acme Cloud Program Staffing Review"), ("PwC Cloud Program Pricing", "Acme Cloud Program Pricing"),
        ("Hexaware Delivery Negotiation", "Northwind Delivery Negotiation"), ('"PWC"', '"ACME"'), ('"PwC"', '"Acme"'), ('"Hexaware"', '"Northwind"'),
        ("project=PwC%20Cloud", "project=Acme%20Cloud"), ("project=PwC", "project=Acme"), ('"PwC Cloud"', '"Acme Cloud"'),
        ('{"PwC": 2, "Hexaware": 1}, "PWC and PwC are one project"', '{"Acme": 2, "Northwind": 1}, "ACME and Acme are one project"'),
        ("Raghav", "Priya"), ("Dhruv", "Dev"), ("Sameer", "Sam")]
for p in ("logs/tests/run_tests.py", "logs/scripts/area_p_block.py"):
    t = Path(p).read_text("utf-8")
    for a, b in swap:
        t = t.replace(a, b)
    # the fixture's home must know that ACME and Acme are one project, as the owner's file does on his machine
    a = '    write_config(home, 7486, model_budget_mb=100, meeting_archive=str(arch))\n'
    if a in t and "project_names.json" not in t:
        t = t.replace(a, a + '    (home / "twinmind").mkdir(parents=True, exist_ok=True)\n'
                          '    (home / "twinmind" / "project_names.json").write_text(json.dumps({"acme": "Acme"}), "utf-8")\n')
    Path(p).write_text(t, "utf-8")

Path(".gitignore").write_text("""# models and runtimes are large and are not ours to redistribute: see README, "Models and runtimes"
models/
runtimes/
# build output; `build.ps1` / `build.sh` make these
bin/
governor/target/
__pycache__/
*.pyc
# another project's source, kept locally for reference only
reference/*.zip
# local editor and agent state
.claude/
.vscode/
*.tmp
""", "utf-8")
left = [p for p in ("workers/mitra_workers/library.py", "logs/tests/run_tests.py", "logs/scripts/area_p_block.py")
        if re.search(r"PwC|PWC|Hexaware|Raghav|Dhruv|Sameer|Persistent AI Brain", Path(p).read_text("utf-8"))]
print("ok; still naming them:", left)

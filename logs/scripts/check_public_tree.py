"""Before a push to the public repository: search every tracked file for private details.

    python logs/scripts/check_public_tree.py

Looks for email addresses, Indian phone numbers, the owner's surname and Windows user name,
Devanagari text, and every client, person and meeting title on the owner's lists (his meeting
archive's index plus `~/.mitra/twinmind/redact_extra.json`). The lists are read from his machine at
run time; none of them is written in this repository. Exits 1 and names the files if anything is found.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
from mitra_workers import library, paths  # noqa: E402

extra = {}
f = paths.HOME / "twinmind" / "redact_extra.json"
if f.is_file():
    extra = json.loads(f.read_text("utf-8"))
people, clients, titles = set(extra.get("people", [])), set(extra.get("clients", [])), set(extra.get("titles", []))
for e in library.index(paths.HOME / "twinmind" / "nothing-here", refresh=False):
    if e["src"] == "archive":
        titles.add(e["title"])
        if e["project"]:
            clients.add(e["project"])
keep = set(extra.get("keep", []))
people, clients = people - keep, clients - keep
titles = {t for t in titles if len(t) >= 12 and t not in keep}


def alt(words, flags=0, bound=True):
    body = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) or r"(?!x)x"
    return re.compile((r"(?<![\w])(?:" + body + r")(?![\w])") if bound else "(?:" + body + ")", flags)


checks = {"client": alt(clients), "person": alt(people), "meeting title": alt(titles, re.I, False),
          "email": re.compile(r"[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com|anthropic\.com|example\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
          "phone": re.compile(r"\+91[\s-]?\d{10}"), "surname": re.compile(extra.get("surname") or r"(?!x)x", re.I),
          "user name": re.compile(r"(?i)users[\\/]+" + re.escape(extra.get("user") or "\0")), "devanagari (not in code, where Hindi stop-words are expected)": re.compile("[ऀ-ॿ]{3,}")}
files = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, encoding="utf-8").stdout.split("\0")
bad = {}
for name in filter(None, files):
    try:
        text = Path(name).read_text("utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for kind, rx in checks.items():
        if kind.startswith("devanagari") and name.endswith((".py", ".go", ".rs", ".js")):
            continue
        hits = sorted(set(m if isinstance(m, str) else m[0] for m in rx.findall(text)))
        if hits:
            bad.setdefault(name, []).append(f"{kind}: {len(hits)} distinct")
for name, kinds in sorted(bad.items()):
    print(f"{name}: {'; '.join(kinds)}")
print(f"{len(files) - 1} files checked against {len(clients)} clients, {len(people)} people, {len(titles)} meeting titles; {len(bad)} with something private")
sys.exit(1 if bad else 0)

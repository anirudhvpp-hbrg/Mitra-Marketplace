"""Mitra test suite.

    mitra-marketplace test             everything, including the tests that load real models
    mitra-marketplace test --quick     skip model tests (a few minutes)
    mitra-marketplace test T007 T021   only the named cases
    mitra-marketplace test --list      print the cases without running them

Runs against a private launcher on its own port with its own MITRA_HOME, so your real memory
log, apps and config are never touched, and no window is opened. Results are written to
logs/tests/results/. Standard library only.

Cases are numbered in the order they are written below, grouped by area:
  A launcher and command   B each app is its own process   C the products are kept separate
  D each app's screen      E conversion                    F the governor
  G TwinMind pipeline      H memory log                    I moving between systems
  J security               K resources and the package     L real models
  M, N TwinMind on real calls                               O taking turns, saved pieces, the line
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(os.environ.get("MITRA_ROOT") or Path(__file__).resolve().parents[2])
EXE = ".exe" if os.name == "nt" else ""
CLI = str(ROOT / "bin" / f"mitra-marketplace{EXE}")
GOV = str(ROOT / "bin" / f"mitra-governor{EXE}")
QUICK = "--quick" in sys.argv
ONLY = [a for a in sys.argv[1:] if re.fullmatch(r"T\d{3}", a)]
PORT = 7499
BASE = f"http://127.0.0.1:{PORT}"
TMP = Path(tempfile.mkdtemp(prefix="mitra-test-"))
HOME = TMP / "home"
RELEASES = TMP / "releases"
DOCS = TMP / "docs"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BUILTIN = ["markdown-reader", "pdf-reader", "to-markdown", "assistant", "twinmind"]
t = unittest.TestCase()
t.maxDiff = None
S = {}          # state shared between cases that build on each other
CASES = []      # (area, name, fn)

real_cfg = {}
try:
    real_cfg = json.loads((Path.home() / ".mitra" / "config.json").read_text("utf-8-sig"))
except Exception:
    pass


def case(area, name):
    def deco(fn):
        CASES.append((area, name, fn))
        return fn
    return deco


def skip(why):
    raise unittest.SkipTest(why)


def env(home=HOME, root=ROOT):
    e = dict(os.environ, MITRA_HOME=str(home), MITRA_ROOT=str(root), PYTHONUTF8="1")
    e["PYTHONPATH"] = str(ROOT / "workers")
    e["MITRA_TZ_OFFSET_MIN"] = str(int(datetime.now().astimezone().utcoffset().total_seconds() // 60))
    return e


def write_config(home, port, **extra):
    home.mkdir(parents=True, exist_ok=True)
    cfg = {k: real_cfg[k] for k in ("models_dir", "finetuned_dir", "whisper_cli", "ffmpeg", "llama_server") if k in real_cfg}
    cfg.update(port=port, release_dir=str(RELEASES), idle_exit_min=0, app_idle_exit_s=0, close_grace_s=1.5, app_window="none",
               connectors={"dropbox": str(TMP / "dropbox")})
    cfg.update(extra)
    (home / "config.json").write_text(json.dumps(cfg), "utf-8")


def cli(*args, home=HOME, root=ROOT, timeout=180):
    r = subprocess.run([CLI, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env(home, root), timeout=timeout, creationflags=NOWIN)
    return r.returncode, r.stdout + r.stderr


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http(method, path, body=None, headers=None, raw=False, base=BASE, follow=True, timeout=300):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(base + path, data=data, headers=h, method=method)
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            content = r.read()
            return r.status, (content if raw else json.loads(content or b"null")), dict(r.headers)
    except urllib.error.HTTPError as e:
        content = e.read()
        try:
            return e.code, json.loads(content), dict(e.headers)
        except Exception:
            return e.code, content, dict(e.headers)


def alive(base):
    try:
        return http("GET", "/api/ping", base=base, timeout=2)[0] == 200
    except Exception:
        return False


def gone(base, within=8.0):
    end = time.time() + within
    while time.time() < end:
        if not alive(base):
            return True
        time.sleep(0.2)
    return False


def launch(app_id, base=BASE, **body):
    """Start an app the way an icon does; returns the launch answer."""
    s, r, _ = http("POST", f"/api/launch/{app_id}", body, base=base)
    t.assertEqual(s, 200, r)
    return r


def app(app_id, base=BASE):
    """The address of an app's own process, starting it if needed."""
    return f"http://127.0.0.1:{launch(app_id, base)['port']}"


def q(path):
    return urllib.parse.quote(str(path), safe="")


def events(home=HOME):
    out = []
    for f in sorted((home / "memory" / "events").glob("*.jsonl")):
        out += [json.loads(l) for l in f.read_text("utf-8").splitlines() if l.strip()]
    return out


def _process_table():
    """{pid: (ppid, command line)} for every process on this device."""
    if os.name == "nt":
        ps = "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.CommandLine)\" }"
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=NOWIN).stdout
    else:
        out = subprocess.run(["ps", "-eo", "pid=,ppid=,args="], capture_output=True, text=True).stdout.replace("  ", "\t")
    table = {}
    for l in out.splitlines():
        parts = l.strip().split(None, 2) if os.name != "nt" else l.split("\t", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2])
    return table


# A Mitra already running on this device when the suite starts (your own, at work on a recording)
# is not the suite's. Its processes, and everything they start later, are left out of the count.
# Limit: a second Mitra started while the suite runs is not told apart, and still counts.
_BEFORE = {pid for pid, (_, cmd) in _process_table().items() if "mitra-marketplace" in cmd and "run_tests" not in cmd}


def mitra_processes():
    """Worker, governor or model processes this suite started and that are still running."""
    table, mine = _process_table(), ("mitra_workers", "mitra-governor", str(ROOT))

    def foreign(pid):
        for _ in range(64):            # walk up to the root; a cycle or a vanished parent ends the walk
            if pid in _BEFORE:
                return True
            if pid not in table:
                return False
            pid = table[pid][0]
        return False
    return [f"{pid}<{table[pid][0]} {cmd}" for pid, (_, cmd) in table.items() if any(m in cmd for m in mine) and "Get-CimInstance" not in cmd
            and "run_tests" not in cmd and not foreign(pid)]


def kill_pid(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=NOWIN)
    else:
        os.kill(pid, 9)


def burner(mb, seconds):
    """A command that really occupies `mb` MB for `seconds` seconds."""
    return [sys.executable, "-c", f"import time; b=bytearray({mb}<<20); b[::4096]=b'x'*len(b[::4096]); time.sleep({seconds})"]


def gov(*args, home=HOME, timeout=90):
    r = subprocess.run([GOV, *args], capture_output=True, text=True, env=env(home), timeout=timeout, creationflags=NOWIN)
    return r.returncode, r.stdout, r.stderr


def py(code, home=HOME):
    """Run worker code directly and return what it printed as JSON."""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", env=env(home), creationflags=NOWIN)
    t.assertEqual(r.returncode, 0, r.stderr[-800:])
    return json.loads(r.stdout)


# ---- fixtures ------------------------------------------------------------------------------

def make_docx(p):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    xml = (f'<w:document {w}><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Quarterly plan</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Ship the export fix.</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Date</w:t></w:r></w:p></w:tc></w:tr>'
           '<w:tr><w:tc><w:p><w:r><w:t>Sam</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Thursday</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)


def make_xlsx(p):
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    r = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {r}><sheets><sheet name="Budget" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>'
                   '<row r="1"><c r="A1" t="inlineStr"><is><t>Item</t></is></c><c r="B1" t="inlineStr"><is><t>Cost</t></is></c></row>'
                   '<row r="2"><c r="A2" t="inlineStr"><is><t>Laptop</t></is></c><c r="B2"><v>1200</v></c></row></sheetData></worksheet>')


def make_pptx(p):
    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ppt/slides/slide1.xml", f'<sld {a}><a:p><a:r><a:t>Roadmap</a:t></a:r></a:p><a:p><a:r><a:t>Phase one ships in May</a:t></a:r></a:p></sld>')


def make_odt(p):
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"')
    cell = lambda s: f"<table:table-cell><text:p>{s}</text:p></table:table-cell>"
    xml = (f'<office:document-content {ns}><office:body><office:text><text:h text:outline-level="2">Agenda</text:h>'
           '<text:p>Review the budget.</text:p><text:list><text:list-item><text:p>First item</text:p></text:list-item></text:list>'
           f'<table:table><table:table-row>{cell("Owner")}{cell("Due")}</table:table-row><table:table-row>{cell("Sam")}{cell("Friday")}</table:table-row></table:table>'
           '</office:text></office:body></office:document-content>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("content.xml", xml)


def make_epub(p):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ch1.xhtml", "<html><body><h1>Chapter One</h1><p>It began on a Tuesday.</p></body></html>")


def make_pdf(p, text):
    stream = (b"BT /F1 18 Tf 20 100 Td (" + text.encode() + b") Tj ET") if text else b""
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj" % i + o + b"endobj\n"
    x = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % x
    Path(p).write_bytes(bytes(out))


TRANSCRIPT = """Priya: Morning everyone. Let's start with the invoice export.
Sam: CSV still fails on invoices with more than two hundred line items.
Priya: Sam, please fix the CSV timeout by Thursday.
Priya: Decision then: release stays on the twentieth, with the twenty-fourth as fallback.
Dana: I will clear snapshots older than thirty days this afternoon.
"""


def fixtures():
    DOCS.mkdir(parents=True, exist_ok=True)
    make_docx(DOCS / "plan.docx"); make_xlsx(DOCS / "budget.xlsx"); make_pptx(DOCS / "deck.pptx")
    make_odt(DOCS / "agenda.odt"); make_epub(DOCS / "book.epub")
    make_pdf(DOCS / "invoice.pdf", "Invoice total 4200"); make_pdf(DOCS / "scan.pdf", "")
    w = lambda name, text: (DOCS / name).write_text(text, "utf-8")
    w("note.md", "# Note\n\nSee [the plan](plan.docx).\n\n## Second part\n\ntext")
    w("readme.markdown", "# Readme\n\nbody"); w("plain.txt", "just text"); w("empty.txt", "")
    w("data.csv", "name,qty\nbolt,4\n"); w("data.tsv", "name\tqty\nnut\t9\n"); w("pipes.csv", "a,b\nx|y,2\n")
    w("big.csv", "id,v\n" + "".join(f"r{i},{i}\n" for i in range(2500)))
    w("page.html", "<html><head><script>x()</script><style>p{}</style></head><body><h2>Title</h2><p>Hello <b>world</b></p><ul><li>one</li></ul><a href='https://example.org'>link</a></body></html>")
    w("old.htm", "<h1>Old page</h1><p>para</p>"); w("conf.json", '{"a": 1}')
    w("nb.ipynb", json.dumps({"cells": [{"cell_type": "markdown", "source": ["# Analysis"]}, {"cell_type": "code", "source": ["print(1)"]}]}))
    w("tool.py", "def f():\n    return 1\n"); w("q.sql", "select 1;"); w("cap.vtt", "WEBVTT\n\n00:01.000 --> 00:02.000\nHello there"); w("cap.srt", "1\n00:00:01,000 --> 00:00:02,000\nHi again")
    w("standup.txt", TRANSCRIPT)
    (DOCS / "letter.rtf").write_bytes(rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}{\*\generator Riched20;}\f0 Dear Sam,\par The total is \b 4200\b0  rupees.\par caf\'e9 \u8212?done\par}")
    (DOCS / "blob.xyz").write_bytes(b"\x00\x01"); (DOCS / "broken.docx").write_bytes(b"this is not a zip"); (DOCS / "broken.pdf").write_bytes(b"%PDF-1.4 garbage")
    (DOCS / "sp ace").mkdir(exist_ok=True)
    (DOCS / "sp ace" / "r\u00e9sum\u00e9 notes.md").write_text("# R\u00e9sum\u00e9\n\nok", "utf-8")
    (DOCS / ".hidden").write_text("x", "utf-8")


def conv(name, base=None):
    return http("GET", "/api/convert?path=" + q(DOCS / name), base=base or app("to-markdown"))


# ============================================================================================
# A. launcher and command
# ============================================================================================
@case("A", "cli reports its version")
def _():
    code, out = cli("version")
    t.assertEqual(code, 0)
    t.assertRegex(out.strip(), r"^\d+\.\d+\.\d+$")


@case("A", "help lists the per-app commands")
def _():
    out = cli("help")[1]
    for word in ("open APP", "apps ", "close APP", "models", "size", "stop"):
        t.assertIn(word, out)


@case("A", "launcher answers and says it is the launcher")
def _():
    s, body, _ = http("GET", "/api/ping")
    t.assertEqual(s, 200)
    t.assertTrue(body["mitra"])
    t.assertEqual(body["app"], "", "the launcher is not an app")


@case("A", "nothing is running before any icon is clicked")
def _():
    t.assertEqual(http("GET", "/api/running")[1], [])
    t.assertEqual(list((HOME / "run" / "apps").glob("*.json")), [])


@case("A", "first screen is the welcome screen with an Enter button")
def _():
    s, page, _ = http("GET", "/", raw=True)
    t.assertEqual(s, 200)
    page = page.decode()
    t.assertIn('id="welcome"', page)
    t.assertIn('id="enter"', page)
    t.assertLess(page.index('id="welcome"'), page.index('id="applist"'), "the welcome screen comes before the apps")


@case("A", "apps are icons that call launch, not links to pages")
def _():
    page = http("GET", "/", raw=True)[1].decode()
    t.assertIn('class="tile', page)
    t.assertIn("M.launch(", page)
    t.assertNotIn('<a class="app" href="/apps/', page, "an icon must start the app's process, not navigate to a page of the launcher")


@case("A", "loading the launcher and listing apps starts no app")
def _():
    http("GET", "/", raw=True); http("GET", "/api/apps"); http("GET", "/api/recent/all")
    t.assertEqual(http("GET", "/api/running")[1], [])


@case("A", "shared assets are served")
def _():
    for asset in ("/static/sdk.js", "/static/mitra.css", "/static/brand/mitra-color.png", "/static/brand/mitra-tint.png"):
        t.assertEqual(http("GET", asset, raw=True)[0], 200, asset)


@case("A", "a missing asset is a 404, not a page")
def _():
    t.assertEqual(http("GET", "/static/nope.js", raw=True)[0], 404)


@case("A", "logo is the real image, never stretched, colour on light and tint on dark")
def _():
    page = http("GET", "/", raw=True)[1]
    css = http("GET", "/static/mitra.css", raw=True)[1].decode()
    sdk = http("GET", "/static/sdk.js", raw=True)[1].decode()
    for variant in ("mitra-color.png", "mitra-tint.png"):
        t.assertEqual(http("GET", f"/static/brand/{variant}", raw=True)[1][:8], b"\x89PNG\r\n\x1a\n", variant)
    t.assertIn(b'class="logo', page)
    t.assertIn('class="logo"', sdk, "every app's top bar shows the logo")
    t.assertRegex(css, r"\.logo\s*\{[^}]*aspect-ratio:\s*360\s*/\s*268")
    t.assertRegex(css, r"\.logo\s*\{[^}]*contain")
    light, dark = css.split("prefers-color-scheme: dark", 1)
    t.assertIn("mitra-color.png", light)
    t.assertIn("mitra-tint.png", dark)


@case("A", "screens use the drawn icon set, not emoji")
def _():
    page = http("GET", "/", raw=True)[1].decode()
    sdk = http("GET", "/static/sdk.js", raw=True)[1].decode()
    t.assertNotRegex(page + sdk, r"[\U0001F300-\U0001FAFF]")


@case("A", "all built-in apps are listed with what an icon needs")
def _():
    s, apps, _ = http("GET", "/api/apps")
    t.assertEqual(s, 200)
    t.assertTrue(set(BUILTIN) <= {a["id"] for a in apps})
    for a in apps:
        for key in ("name", "description", "category", "needs", "connectors", "glyph", "builtin"):
            t.assertIn(key, a, f"{a['id']} lacks {key}")


@case("A", "the three named products are present by name")
def _():
    names = {a["name"] for a in http("GET", "/api/apps")[1]}
    t.assertTrue({"Mitra PDF", "Anything to MD", "TwinMind"} <= names, names)


@case("A", "launcher has the create, memory and system pages")
def _():
    page = http("GET", "/", raw=True)[1].decode()
    for sec in ('<section id="create"', '<section id="memory"', '<section id="system"', 'id="procs"'):
        t.assertIn(sec, page)


@case("A", "heartbeat is answered with nothing to read")
def _():
    s, body, _ = http("GET", "/api/heartbeat", raw=True)
    t.assertEqual((s, body), (204, b""))


@case("A", "system status has RAM, limits and the launcher's own size")
def _():
    s = http("GET", "/api/system")[1]
    for key in ("ram", "limits", "leases", "gateway_mb", "state"):
        t.assertIn(key, s)
    t.assertEqual(s["app"], "")


@case("A", "launcher stays under 40 MB")
def _():
    t.assertLessEqual(http("GET", "/api/system")[1]["gateway_mb"], 40)
    t.assertLessEqual(http("GET", "/api/ping")[1]["mb"], 40)


@case("A", "status command reports the launcher, the model and the apps")
def _():
    code, out = cli("status")
    t.assertEqual(code, 0, out)
    for part in ("Launcher: running", "Models loaded: none", "Apps running: none"):
        t.assertIn(part, out)


@case("A", "apps command says when none is running")
def _():
    t.assertIn("No app is running", cli("apps")[1])


@case("A", "list command prints every installed app")
def _():
    code, out = cli("list")
    t.assertEqual(code, 0, out)
    for a in BUILTIN:
        t.assertIn(a, out)


# ============================================================================================
# B. each app is its own process
# ============================================================================================
@case("B", "clicking an icon starts a separate process on its own port")
def _():
    launcher = http("GET", "/api/ping")[1]
    r = launch("markdown-reader")
    S["md"] = r
    t.assertTrue(r["started"])
    t.assertNotEqual(r["pid"], launcher["pid"], "the app must not run inside the launcher")
    t.assertNotEqual(r["port"], PORT)
    t.assertIn(f":{r['port']}/apps/markdown-reader/", r["url"])


@case("B", "the app's process answers as that app")
def _():
    base = f"http://127.0.0.1:{S['md']['port']}"
    ping = http("GET", "/api/ping", base=base)[1]
    t.assertEqual((ping["app"], ping["pid"], ping["port"]), ("markdown-reader", S["md"]["pid"], S["md"]["port"]))


@case("B", "starting an app is logged as a spawn and a launch")
def _():
    ev = [e for e in events() if e["app"] == "markdown-reader"]
    spawn = [e for e in ev if e["type"] == "app.spawn"]
    t.assertTrue(spawn and spawn[-1]["data"]["pid"] == S["md"]["pid"])
    lau = [e for e in ev if e["type"] == "app.launch"]
    t.assertTrue(lau and lau[-1]["data"]["from"] == "launcher" and lau[-1]["data"]["fresh"])


@case("B", "clicking the icon again reuses the running process")
def _():
    r = launch("markdown-reader")
    t.assertFalse(r["started"])
    t.assertEqual((r["pid"], r["port"]), (S["md"]["pid"], S["md"]["port"]))


@case("B", "the launcher shows what is running, with port, process and size")
def _():
    run = http("GET", "/api/running")[1]
    t.assertEqual([r["id"] for r in run], ["markdown-reader"])
    t.assertEqual(run[0]["pid"], S["md"]["pid"])
    t.assertGreater(run[0]["mb"], 0)


@case("B", "a run file exists exactly while the app runs")
def _():
    info = json.loads((HOME / "run" / "apps" / "markdown-reader.json").read_text())
    t.assertEqual(info["port"], S["md"]["port"])


@case("B", "an app starts in under two seconds")
def _():
    http("POST", "/api/stop/markdown-reader")
    r = launch("markdown-reader")
    S["md"] = r
    t.assertTrue(r["started"])
    t.assertLess(r["ms"], 2000, f"took {r['ms']} ms")


@case("B", "an app's process stays under 40 MB")
def _():
    t.assertLessEqual(http("GET", "/api/ping", base=f"http://127.0.0.1:{S['md']['port']}")[1]["mb"], 40)


def _own_process(app_id):
    def check():
        r = launch(app_id)
        base = f"http://127.0.0.1:{r['port']}"
        t.assertEqual(http("GET", "/api/ping", base=base)[1]["app"], app_id)
        s, page, _ = http("GET", f"/apps/{app_id}/", raw=True, base=base)
        t.assertEqual(s, 200)
        t.assertIn(b"/static/sdk.js", page)
        S.setdefault("ports", {})[app_id] = (r["pid"], r["port"])
    return check


for _id in BUILTIN:
    case("B", f"{_id} runs as its own process and serves its own screen")(_own_process(_id))


@case("B", "five apps are five processes on five ports")
def _():
    t.assertEqual(len({p for p, _ in S["ports"].values()}), 5)
    t.assertEqual(len({p for _, p in S["ports"].values()}), 5)
    t.assertEqual(len(http("GET", "/api/running")[1]), 5)


@case("B", "the app's address alone leads to its screen")
def _():
    base = app("pdf-reader")
    s, _, h = http("GET", "/", raw=True, base=base, follow=False)
    t.assertEqual(s, 302)
    t.assertEqual(h["Location"], "/apps/pdf-reader/")


@case("B", "asking the launcher for an app's page starts the app and sends you there")
def _():
    http("POST", "/api/stop/pdf-reader")
    s, _, h = http("GET", "/apps/pdf-reader/?path=x.pdf", raw=True, follow=False)
    t.assertEqual(s, 302)
    t.assertRegex(h["Location"], r"^http://127\.0\.0\.1:\d+/apps/pdf-reader/\?path=x\.pdf$")
    t.assertNotIn(f":{PORT}/", h["Location"], "the launcher never serves an app's screen itself")
    t.assertTrue(alive(h["Location"].split("/apps/")[0]))


@case("B", "launching with a file opens the app on that file")
def _():
    r = launch("markdown-reader", path=str(DOCS / "note.md"))
    u = urllib.parse.urlparse(r["url"])
    t.assertEqual(urllib.parse.parse_qs(u.query)["path"], [str(DOCS / "note.md")])


@case("B", "stopping an app from the launcher ends its process and logs why")
def _():
    base = app("assistant")
    s, r, _ = http("POST", "/api/stop/assistant")
    t.assertTrue(r["stopped"])
    t.assertTrue(gone(base))
    t.assertFalse((HOME / "run" / "apps" / "assistant.json").exists())
    ex = [e for e in events() if e["app"] == "assistant" and e["type"] == "app.exit"][-1]["data"]
    t.assertEqual(ex["reason"], "stopped")
    t.assertIn("lived_s", ex)


@case("B", "stopping an app that is not running says so")
def _():
    t.assertFalse(http("POST", "/api/stop/assistant")[1]["stopped"])


@case("B", "closing the window ends the process within seconds")
def _():
    base = app("to-markdown")
    t.assertEqual(http("POST", "/api/bye", b"", base=base, raw=True)[0], 204)
    t.assertTrue(gone(base, 6), "the app must end after its window says goodbye")
    ex = [e for e in events() if e["app"] == "to-markdown" and e["type"] == "app.exit"][-1]["data"]
    t.assertEqual(ex["reason"], "window closed")


@case("B", "a reload does not end the app")
def _():
    base = app("to-markdown")
    http("POST", "/api/bye", b"", base=base, raw=True)
    time.sleep(0.3)
    http("GET", "/apps/to-markdown/", raw=True, base=base)   # the page asking again, as a reload does
    time.sleep(3)
    t.assertTrue(alive(base), "a goodbye followed by a new request is a reload, not a close")


@case("B", "the launcher checking on an app does not keep a closed app alive")
def _():
    base = app("to-markdown")
    http("POST", "/api/bye", b"", base=base, raw=True)
    for _ in range(4):                       # the launcher's page asks what is running every few seconds
        http("GET", "/api/running")
        time.sleep(0.4)
    t.assertTrue(gone(base, 5), "being asked 'are you there?' must not count as use")


@case("B", "the other apps keep running when one is closed")
def _():
    t.assertTrue(alive(f"http://127.0.0.1:{S['ports']['twinmind'][1]}"))
    t.assertTrue(alive(BASE))


@case("B", "a crash in one app leaves the launcher and the other apps running")
def _():
    r = launch("pdf-reader")
    kill_pid(r["pid"])
    t.assertTrue(gone(f"http://127.0.0.1:{r['port']}"))
    t.assertTrue(alive(BASE))
    t.assertTrue(alive(f"http://127.0.0.1:{S['ports']['twinmind'][1]}"))
    S["crashed"] = r


@case("B", "a crashed app is not shown as running and starts again cleanly")
def _():
    t.assertNotIn("pdf-reader", [r["id"] for r in http("GET", "/api/running")[1]])
    r = launch("pdf-reader")
    t.assertTrue(r["started"])
    t.assertNotEqual(r["pid"], S["crashed"]["pid"])


@case("B", "an app can start another app")
def _():
    http("POST", "/api/stop/to-markdown")
    r = launch("to-markdown", base=app("pdf-reader"), path=str(DOCS / "invoice.pdf"))
    t.assertTrue(alive(f"http://127.0.0.1:{r['port']}"))
    lau = [e for e in events() if e["app"] == "to-markdown" and e["type"] == "app.launch"][-1]["data"]
    t.assertEqual(lau["from"], "pdf-reader")


@case("B", "launching an app that does not exist fails clearly")
def _():
    s, r, _ = http("POST", "/api/launch/no-such-app", {})
    t.assertEqual(s, 404)
    t.assertIn("no-such-app", r["detail"])


@case("B", "apps command lists what is running")
def _():
    out = cli("apps")[1]
    t.assertIn("twinmind", out)
    t.assertRegex(out, r"pid \d+")


@case("B", "close command stops one app")
def _():
    base = app("assistant")
    t.assertIn("Closed assistant", cli("close", "assistant")[1])
    t.assertTrue(gone(base))
    t.assertIn("not running", cli("close", "assistant")[1])


@case("B", "the app command refuses an unknown app")
def _():
    code, out = cli("app", "no-such-app")
    t.assertEqual(code, 2)
    t.assertIn("No such app", out)


@case("B", "open command starts an app without the launcher, on a file")
def _():
    home = TMP / "home-open"
    write_config(home, 7489)
    try:
        code, out = cli("open", "pdf-reader", str(DOCS / "invoice.pdf"), home=home)
        t.assertEqual(code, 0, out)
        url = re.search(r"http://\S+", out).group(0)
        t.assertIn("path=", url)
        t.assertTrue(alive(url.split("/apps/")[0]))
        t.assertFalse(alive("http://127.0.0.1:7489"), "opening one app must not start the launcher")
    finally:
        cli("stop", home=home)


@case("B", "an app whose window vanished ends by itself after a quiet period")
def _():
    home = TMP / "home-appidle"
    write_config(home, 7488, app_idle_exit_s=2)
    out = cli("open", "markdown-reader", home=home)[1]
    base = re.search(r"http://[\d.:]+", out).group(0)
    t.assertTrue(gone(base, 8), "with no window talking to it, the app must exit")
    t.assertEqual([e for e in events(home) if e["type"] == "app.exit"][-1]["data"]["reason"], "idle")


@case("B", "stop command closes every app and the launcher")
def _():
    home = TMP / "home-stopall"
    write_config(home, 7492)
    t.assertEqual(cli("list", home=home)[0], 0)
    urls = [re.search(r"http://[\d.:]+", cli("open", a, home=home)[1]).group(0) for a in ("pdf-reader", "to-markdown")]
    code, out = cli("stop", home=home)
    t.assertIn("2 app(s) closed", out)
    for u in urls + ["http://127.0.0.1:7492"]:
        t.assertFalse(alive(u), u)
    t.assertIn("Not running", cli("stop", home=home)[1])


@case("B", "the launcher ends when its own window closes")
def _():
    home = TMP / "home-bye"
    write_config(home, 7493)
    p = subprocess.Popen([CLI, "serve"], env=env(home), creationflags=NOWIN)
    try:
        for _ in range(40):
            if alive("http://127.0.0.1:7493"):
                break
            time.sleep(0.2)
        http("POST", "/api/bye", b"", base="http://127.0.0.1:7493", raw=True)
        t.assertEqual(p.wait(timeout=10), 0)
    finally:
        if p.poll() is None:
            p.kill()
    t.assertEqual([e for e in events(home) if e["type"] == "server.exit"][-1]["data"]["reason"], "window closed")


@case("B", "the launcher ends by itself when unused")
def _():
    home = TMP / "home-idle"
    write_config(home, 7495, idle_exit_min=0.05)
    p = subprocess.Popen([CLI, "serve"], env=env(home), creationflags=NOWIN)
    try:
        t.assertEqual(p.wait(timeout=30), 0)
    finally:
        if p.poll() is None:
            p.kill()
    t.assertTrue(any(e["type"] == "server.idle_exit" for e in events(home)))


@case("B", "stop then start right away works")
def _():
    home = TMP / "home-restart"
    write_config(home, 7494)
    try:
        t.assertEqual(cli("list", home=home)[0], 0)
        t.assertIn("Stopped", cli("stop", home=home)[1])
        code, out = cli("list", home=home)
        t.assertEqual(code, 0, out)
        t.assertIn("markdown-reader", out)
        t.assertTrue(alive("http://127.0.0.1:7494"))
    finally:
        cli("stop", home=home)


# ============================================================================================
# C. the products are kept separate
# ============================================================================================
def _refused(method, path, status, base_of=None, body=None, word=None):
    def check():
        base = app(base_of) if base_of else BASE
        s, r, _ = http(method, path, body, base=base)
        t.assertEqual(s, status, r)
        if word:
            t.assertIn(word, r["detail"])
    return check


case("C", "the launcher cannot convert files")(_refused("GET", "/api/convert/formats", 409, word="inside an app"))
case("C", "the launcher cannot ask the model")(_refused("POST", "/api/ask", 409, body={"app_id": "assistant", "prompt": "hi"}))
case("C", "the launcher cannot take uploads")(_refused("POST", "/api/upload?name=a.txt", 409, body=b"x"))
case("C", "the launcher cannot answer for an app")(_refused("GET", "/api/apps/twinmind/status", 409, word="twinmind"))
case("C", "the launcher cannot start an app's job")(_refused("POST", "/api/apps/twinmind/job/run", 409, body={"path": "x"}))
case("C", "an app's process will not answer for another app")(_refused("GET", "/api/apps/twinmind/status", 403, "pdf-reader", word="pdf-reader only"))
case("C", "an app's process will not describe another app")(_refused("GET", "/api/apps/assistant", 403, "pdf-reader"))
case("C", "an app cannot create apps")(_refused("POST", "/api/builder/draft", 403, "markdown-reader", {"prompt": "x"}, "launcher"))
case("C", "an app cannot read or prune the memory log")(_refused("GET", "/api/memory/report", 403, "markdown-reader"))
case("C", "an app cannot remove an app")(_refused("DELETE", "/api/apps/markdown-reader", 403, "markdown-reader"))
case("C", "an app cannot stop other apps")(_refused("POST", "/api/stop/twinmind", 403, "markdown-reader"))
case("C", "an app cannot review another app")(_refused("GET", "/api/manager/twinmind", 403, "markdown-reader"))
case("C", "an app without the assistant cannot use the model")(_refused("POST", "/api/ask", 403, "pdf-reader", {"app_id": "assistant", "prompt": "hi"}, "does not declare"))
case("C", "the assistant app cannot convert files")(_refused("GET", "/api/convert/formats", 403, "assistant", word="convert"))
case("C", "TwinMind has no upload route")(_refused("POST", "/api/upload?name=a.txt", 403, "twinmind", b"x"))


@case("C", "an app's process will not serve another app's screen")
def _():
    s, r, _ = http("GET", "/apps/twinmind/", base=app("pdf-reader"))
    t.assertEqual(s, 404)
    t.assertIn("pdf-reader only", r["detail"])


@case("C", "an app can describe and review itself")
def _():
    base = app("twinmind")
    t.assertEqual(http("GET", "/api/apps/twinmind", base=base)[1]["id"], "twinmind")
    r = http("GET", "/api/manager/twinmind", base=base)[1]
    for key in ("findings", "stats", "budget_mb"):
        t.assertIn(key, r)


@case("C", "an app can list the other apps for its go-to menu")
def _():
    t.assertTrue(set(BUILTIN) <= {a["id"] for a in http("GET", "/api/apps", base=app("pdf-reader"))[1]})


@case("C", "document apps declare no model")
def _():
    needs = {a["id"]: [n["capability"] for n in a["needs"]] for a in http("GET", "/api/apps")[1]}
    for doc_app in ("markdown-reader", "pdf-reader", "to-markdown"):
        t.assertEqual(needs[doc_app], [])


@case("C", "only the assistant and TwinMind declare models, each for a stated purpose")
def _():
    needs = {a["id"]: [n["capability"] for n in a["needs"]] for a in http("GET", "/api/apps")[1] if a["builtin"]}
    t.assertEqual(needs["assistant"], ["assistant"])
    t.assertEqual(needs["twinmind"], ["transcription", "diarization", "meeting-notes"])
    t.assertEqual([k for k, v in needs.items() if v], ["assistant", "twinmind"] if list(needs).index("assistant") < list(needs).index("twinmind") else ["twinmind", "assistant"])


@case("C", "every manifest says what shared services the app uses")
def _():
    for a in BUILTIN:
        m = json.loads((ROOT / "apps" / a / "mitra.app.json").read_text("utf-8"))
        t.assertIn("uses", m, a)
    t.assertEqual(json.loads((ROOT / "apps" / "assistant" / "mitra.app.json").read_text("utf-8"))["uses"], [])


@case("C", "what an app does is logged under that app's name")
def _():
    conv("data.csv")
    calls = [e for e in events() if e["type"] == "api.call" and e["data"]["path"] == "convert"]
    t.assertTrue(calls)
    t.assertEqual(calls[-1]["app"], "to-markdown")
    t.assertGreater(calls[-1]["data"]["worker_mb"], 0)


@case("C", "an app's window can ask for the launcher")
def _():
    s, r, _ = http("POST", "/api/launcher?to=memory", base=app("pdf-reader"))
    t.assertEqual(s, 200, r)
    t.assertTrue(r["ok"])


# ============================================================================================
# D. each app's screen
# ============================================================================================
def _page(app_id, *needles):
    def check():
        page = http("GET", f"/apps/{app_id}/", raw=True, base=app(app_id))[1].decode()
        for n in needles:
            t.assertIn(n, page, f"{app_id} screen lacks {n}")
    return check


case("D", "Markdown Reader screen has the file list, outline and source view")(_page("markdown-reader", 'id="files"', "Outline", 'id="toggle"', "M.param('find')"))
case("D", "Mitra PDF screen has page view, text view and convert")(_page("pdf-reader", "<title>Mitra PDF</title>", "Text view", "Convert to Markdown", "M.launch('to-markdown'"))
case("D", "Anything to MD screen converts, uploads and saves")(_page("to-markdown", "/api/convert", "M.openFile", "/api/convert/save"))
case("D", "Ask Mitra screen asks the one general model")(_page("assistant", "/api/ask"))
case("D", "TwinMind screen has new meeting, search and the meetings list")(_page("twinmind", "Write the memo", "Find a meeting", "Search inside transcripts", 'id="meetings"', ".rtf", ".odt"))


@case("D", "every app's top bar carries its name, logo and go-to menu")
def _():
    sdk = http("GET", "/static/sdk.js", raw=True, base=app("twinmind"))[1].decode()
    for n in ("data-mgr", "data-pal", "M.palette", "Show all apps"):
        t.assertIn(n, sdk)


@case("D", "a link to another app starts that app instead of loading it here")
def _():
    sdk = http("GET", "/static/sdk.js", raw=True)[1].decode()
    t.assertIn("m[1] !== M.appId", sdk)
    t.assertIn("/api/heartbeat", sdk)
    t.assertIn("/api/bye", sdk)


@case("D", "Markdown Reader reads a file and knows its folder for links")
def _():
    s, r, _ = http("GET", "/api/convert?path=" + q(DOCS / "note.md"), base=app("markdown-reader"))
    t.assertEqual(s, 200, r)
    t.assertIn("## Second part", r["markdown"])
    t.assertEqual(Path(r["dir"]), DOCS)


@case("D", "Mitra PDF extracts a PDF's text")
def _():
    s, r, _ = http("GET", "/api/convert?path=" + q(DOCS / "invoice.pdf"), base=app("pdf-reader"))
    t.assertEqual(s, 200, r)
    t.assertIn("Invoice total 4200", r["markdown"])
    t.assertIn("## Page 1", r["markdown"])


@case("D", "Mitra PDF serves the file itself with seeking for the page view")
def _():
    s, body, h = http("GET", "/api/fs/file?path=" + q(DOCS / "invoice.pdf"), headers={"Range": "bytes=0-7"}, raw=True, base=app("pdf-reader"))
    t.assertEqual((s, body), (206, b"%PDF-1.4"))


@case("D", "Anything to MD lists the formats it reads")
def _():
    f = http("GET", "/api/convert/formats", base=app("to-markdown"))[1]
    for ext in (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".csv", ".epub", ".ipynb", ".rtf", ".odt"):
        t.assertIn(ext, f)


@case("D", "Anything to MD takes a dropped file, converts it and saves without overwriting")
def _():
    base = app("to-markdown")
    s, up, _ = http("POST", "/api/upload?name=dropped.csv", b"a,b\n1,2\n", headers={"Content-Type": "application/octet-stream"}, base=base)
    t.assertEqual(s, 200)
    t.assertIn("| 1 | 2 |", http("GET", "/api/convert?path=" + q(up["path"]), base=base)[1]["markdown"])
    src = DOCS / "report.csv"
    src.write_text("x\n1\n", "utf-8")
    first = http("POST", "/api/convert/save", {"markdown": "# one", "source": str(src)}, base=base)[1]["saved"]
    second = http("POST", "/api/convert/save", {"markdown": "# two", "source": str(src)}, base=base)[1]["saved"]
    t.assertNotEqual(first, second)
    t.assertEqual(Path(first).read_text("utf-8"), "# one")
    t.assertEqual(Path(first).parent, DOCS, "the Markdown is saved beside the original")


@case("D", "TwinMind reports its three stages, its output folder and the audio it accepts")
def _():
    st = http("GET", "/api/apps/twinmind/status", base=app("twinmind"))[1]
    t.assertEqual([n["capability"] for n in st["needs"]], ["transcription", "diarization", "meeting-notes"])
    t.assertTrue(st["output"].startswith(str(TMP / "dropbox")))
    t.assertIn(".wav", st["audio_exts"])


@case("D", "TwinMind starts with an empty meetings list and an empty search")
def _():
    base = app("twinmind")
    t.assertEqual(http("GET", "/api/apps/twinmind/meetings", base=base)[1], [])
    t.assertEqual(http("GET", "/api/apps/twinmind/search?q=ab", base=base)[1], [])


@case("D", "the file browser lists folders, hides dot files and remembers nothing it should not")
def _():
    base = app("markdown-reader")
    t.assertTrue(http("GET", "/api/fs/roots", base=base)[1])
    names = [i["name"] for i in http("GET", "/api/fs/list?path=" + q(DOCS), base=base)[1]["items"]]
    t.assertIn("note.md", names)
    t.assertIn("sp ace", names)
    t.assertNotIn(".hidden", names)
    t.assertLess(names.index("sp ace"), names.index("note.md"), "folders are listed before files")


@case("D", "a file range is served exactly")
def _():
    (DOCS / "a.txt").write_text("0123456789abcdef", "utf-8")
    s, body, _ = http("GET", "/api/fs/file?path=" + q(DOCS / "a.txt"), headers={"Range": "bytes=4-9"}, raw=True, base=app("markdown-reader"))
    t.assertEqual((s, body), (206, b"456789"))


@case("D", "a prompt becomes a correct manifest draft")
def _():
    p = "A research notes app called Paper Desk. It connects to Dropbox folder Research/Papers and lets me ask questions about each PDF."
    d = http("POST", "/api/builder/draft", {"prompt": p})[1]
    t.assertEqual((d["id"], d["name"]), ("paper-desk", "Paper Desk"))
    t.assertEqual(d["connectors"], [{"type": "dropbox", "path": "Research/Papers", "mode": "readwrite"}])
    t.assertEqual(d["needs"], ["assistant"])
    t.assertEqual(d["uses"], ["convert"])


@case("D", "no model is added unless the prompt calls for one")
def _():
    d = http("POST", "/api/builder/draft", {"prompt": "A tool named Folder Tidy that renames files in C:\\Temp\\inbox"})[1]
    t.assertEqual(d["needs"], [])
    t.assertEqual(d["connectors"][0]["type"], "folder")


@case("D", "an app created from a prompt gets its own icon")
def _():
    d = http("POST", "/api/builder/draft", {"prompt": "An app called Test Bench that connects to Dropbox folder Bench"})[1]
    s, a, _ = http("POST", "/api/builder/create", {"manifest": d})
    t.assertEqual(s, 200, a)
    S["draft"] = d
    t.assertTrue((TMP / "dropbox" / "Bench").is_dir(), "the connector folder is created")
    listed = {x["id"]: x for x in http("GET", "/api/apps")[1]}
    t.assertIn("test-bench", listed)
    t.assertFalse(listed["test-bench"]["builtin"])
    t.assertEqual(http("POST", "/api/builder/create", {"manifest": d})[0], 400, "a duplicate id is refused")


@case("D", "a created app runs as its own process on the generic workspace")
def _():
    base = app("test-bench")
    t.assertEqual(http("GET", "/api/ping", base=base)[1]["app"], "test-bench")
    t.assertIn(b"Generic workspace", http("GET", "/apps/test-bench/", raw=True, base=base)[1])
    t.assertEqual(http("GET", "/api/convert?path=" + q(DOCS / "plain.txt"), base=base)[0], 200, "it reads files through the shared converter")
    t.assertEqual(http("POST", "/api/ask", {"app_id": "test-bench", "prompt": "hi"}, base=base)[0], 403, "it has no model unless its manifest says so")


@case("D", "built-in apps cannot be removed; a created app is moved aside, not deleted")
def _():
    t.assertEqual(http("DELETE", "/api/apps/markdown-reader")[0], 400)
    http("POST", "/api/stop/test-bench")
    s, r, _ = http("DELETE", "/api/apps/test-bench")
    t.assertEqual(s, 200, r)
    t.assertTrue(Path(r["moved_to"]).is_dir())
    t.assertNotIn("test-bench", [x["id"] for x in http("GET", "/api/apps")[1]])


# ============================================================================================
# E. conversion (Anything to MD's process)
# ============================================================================================
def _converts(name, needles, absent=()):
    def check():
        s, r, _ = conv(name)
        t.assertEqual(s, 200, f"{name}: {r}")
        for n in needles:
            t.assertIn(n, r["markdown"], f"{name} lost: {n}")
        for n in absent:
            t.assertNotIn(n, r["markdown"], f"{name} kept: {n}")
    return check


for _name, _what, _needles, _absent in [
    ("note.md", "Markdown is passed through unchanged", ["# Note", "[the plan](plan.docx)"], []),
    ("readme.markdown", "the .markdown extension is read", ["# Readme"], []),
    ("plain.txt", "plain text is read", ["just text"], []),
    ("invoice.pdf", "PDF text is extracted page by page", ["## Page 1", "Invoice total 4200"], []),
    ("scan.pdf", "a PDF with no text says it needs OCR", ["No extractable text"], []),
    ("plan.docx", "Word headings and paragraphs are kept", ["# Quarterly plan", "Ship the export fix."], []),
    ("plan.docx", "Word tables become Markdown tables", ["| Owner | Date |", "| Sam | Thursday |"], []),
    ("deck.pptx", "PowerPoint slides become sections", ["## Slide 1: Roadmap", "Phase one ships in May"], []),
    ("budget.xlsx", "Excel sheets become tables", ["## Budget", "| Item | Cost |", "| Laptop | 1200 |"], []),
    ("page.html", "HTML keeps structure, emphasis and links", ["## Title", "Hello **world**", "- one", "(https://example.org)"], []),
    ("page.html", "HTML scripts and styles are dropped", ["Title"], ["x()", "p{}"]),
    ("old.htm", "the .htm extension is read", ["# Old page", "para"], []),
    ("data.csv", "CSV becomes a table", ["| name | qty |", "| bolt | 4 |"], []),
    ("data.tsv", "TSV becomes a table", ["| name | qty |", "| nut | 9 |"], []),
    ("pipes.csv", "a | inside a cell cannot break the table", ["x\\|y"], []),
    ("big.csv", "a very long CSV is cut at 2000 rows", ["| r100 | 100 |"], ["r2400"]),
    ("conf.json", "JSON is shown as a code block", ["```json", '{"a": 1}'], []),
    ("nb.ipynb", "notebooks keep their text and their code", ["# Analysis", "```python\nprint(1)"], []),
    ("book.epub", "EPUB chapters are read", ["# Chapter One", "It began on a Tuesday."], []),
    ("letter.rtf", "RTF text is read without its formatting codes, bold kept", ["Dear Sam,", "The total is **4200** rupees."], ["fonttbl", "Arial", "Riched20", "\\par"]),
    ("letter.rtf", "RTF accented and Unicode characters are decoded", ["caf\u00e9", "\u2014done"], ["?done"]),
    ("agenda.odt", "OpenDocument headings, paragraphs and lists are read", ["## Agenda", "Review the budget.", "- First item"], []),
    ("agenda.odt", "OpenDocument tables become Markdown tables", ["| Owner | Due |", "| Sam | Friday |"], []),
    ("tool.py", "source code is shown as a code block in its language", ["```py", "def f():"], []),
    ("q.sql", "SQL is shown as a code block", ["```sql", "select 1;"], []),
    ("cap.vtt", "subtitle files (VTT) are read as transcripts", ["Hello there"], []),
    ("cap.srt", "subtitle files (SRT) are read as transcripts", ["Hi again"], []),
    ("sp ace/r\u00e9sum\u00e9 notes.md", "paths with spaces and accents work", ["# R\u00e9sum\u00e9"], []),
]:
    case("E", _what)(_converts(_name, _needles, _absent))


@case("E", "an empty file converts to nothing rather than failing")
def _():
    s, r, _ = conv("empty.txt")
    t.assertEqual((s, r["markdown"]), (200, ""))


@case("E", "an unsupported format fails with the list of supported ones")
def _():
    s, r, _ = conv("blob.xyz")
    t.assertEqual(s, 422)
    t.assertIn("not supported", r["detail"])
    t.assertIn(".docx", r["detail"])


@case("E", "a missing file is a clear 404")
def _():
    s, r, _ = conv("nope.pdf")
    t.assertEqual(s, 404)
    t.assertIn("nope.pdf", r["detail"])


@case("E", "a damaged Word file fails clearly and leaves the app running")
def _():
    s, r, _ = conv("broken.docx")
    t.assertEqual(s, 422)
    t.assertIn("broken.docx", r["detail"])
    t.assertTrue(alive(app("to-markdown")))


@case("E", "a damaged PDF does not crash the converter")
def _():
    s, r, _ = conv("broken.pdf")
    t.assertIn(s, (200, 422), r)
    t.assertEqual(conv("data.csv")[0], 200, "the next conversion still works")


@case("E", "the converter itself needs no model and stays small")
def _():
    calls = [e["data"] for e in events() if e["type"] == "api.call" and e["app"] == "to-markdown" and e["data"]["path"] == "convert"]
    t.assertLessEqual(max(c["worker_mb"] for c in calls), 80, "converting a document must stay under 80 MB")
    t.assertEqual(json.loads(gov("status")[1])["leases"], [])


# ============================================================================================
# F. the governor: one model at a time, each inside its own limit
# ============================================================================================
@case("F", "status reports RAM and the limits")
def _():
    code, out, _ = gov("status")
    s = json.loads(out)
    t.assertEqual(code, 0)
    t.assertGreater(s["ram"]["total_mb"], 1000)
    t.assertEqual(s["limits"]["model_budget_mb"], 1024)
    t.assertEqual(s["limits"]["max_models"], 1)
    t.assertEqual(s["leases"], [])


@case("F", "a model larger than the budget is refused before it starts")
def _():
    code, _, err = gov("run", "--app", "t", "--name", "big", "--est-mb", "1200", "--", *burner(1, 1))
    t.assertEqual(code, 75)
    t.assertIn("budget", err)


@case("F", "a refusal is written to the memory log")
def _():
    t.assertTrue(any(e["type"] == "governor.denied" for e in events()))


@case("F", "a process that grows past its budget is stopped within seconds")
def _():
    t0 = time.time()
    code, _, err = gov("run", "--app", "t", "--name", "hog", "--est-mb", "50", "--budget-mb", "100", "--", *burner(350, 30))
    t.assertEqual(code, 137, err)
    t.assertLess(time.time() - t0, 15)
    run = [e for e in events() if e["type"] == "model.run" and e["data"]["name"] == "hog"][-1]
    t.assertEqual(run["data"]["end"], "over budget")
    t.assertGreater(run["data"]["peak_mb"], 110)


@case("F", "the lock is released after a model is stopped")
def _():
    t.assertFalse((HOME / "run" / "model.lock").exists())


@case("F", "a process inside its budget finishes and its peak is recorded")
def _():
    code, _, err = gov("run", "--app", "t", "--name", "ok", "--est-mb", "50", "--budget-mb", "200", "--", *burner(60, 2))
    t.assertEqual(code, 0, err)
    run = [e for e in events() if e["type"] == "model.run" and e["data"]["name"] == "ok"][-1]
    t.assertEqual(run["data"]["end"], "exit")
    t.assertGreater(run["data"]["peak_mb"], 40)


@case("F", "only one model runs at a time, whichever app asks")
def _():
    first = subprocess.Popen([GOV, "run", "--app", "app-one", "--name", "first", "--est-mb", "10", "--", *burner(5, 6)], env=env(), creationflags=NOWIN)
    try:
        time.sleep(1.5)
        lease = json.loads(gov("status")[1])["leases"][0]
        t.assertEqual(lease["name"], "first")
        t.assertEqual(lease["apps"], ["app-one"])
        code, _, err = gov("run", "--app", "app-two", "--name", "second", "--est-mb", "10", "--wait", "1", "--", *burner(1, 1))
        t.assertEqual(code, 75)
        t.assertIn("one runs at a time", err)
    finally:
        first.wait(timeout=20)
    t.assertEqual(json.loads(gov("status")[1])["leases"], [])


@case("F", "a second app waits its turn and then runs")
def _():
    first = subprocess.Popen([GOV, "run", "--app", "app-one", "--name", "turn-1", "--est-mb", "10", "--", *burner(5, 3)], env=env(), creationflags=NOWIN)
    time.sleep(1)
    t0 = time.time()
    code, _, err = gov("run", "--app", "app-two", "--name", "turn-2", "--est-mb", "10", "--wait", "20", "--", *burner(5, 1))
    first.wait(timeout=20)
    t.assertEqual(code, 0, err)
    t.assertGreater(time.time() - t0, 1.2, "the second model must not have started while the first was running")


@case("F", "releasing the caller stops the model")
def _():
    p = subprocess.Popen([GOV, "run", "--app", "t", "--name", "held", "--est-mb", "10", "--hold-stdin", "--", *burner(5, 60)],
                         stdin=subprocess.PIPE, env=env(), creationflags=NOWIN)
    time.sleep(1.5)
    t.assertIsNone(p.poll())
    p.stdin.close()
    t.assertEqual(p.wait(timeout=10), 0)
    run = [e for e in events() if e["type"] == "model.run" and e["data"]["name"] == "held"][-1]
    t.assertEqual(run["data"]["end"], "released")


@case("F", "the stop command ends the running model")
def _():
    p = subprocess.Popen([GOV, "run", "--app", "t", "--name", "stopme", "--est-mb", "10", "--", *burner(5, 60)], env=env(), creationflags=NOWIN)
    time.sleep(1.5)
    t.assertTrue(json.loads(gov("kill")[1])["evicted"])
    p.wait(timeout=10)
    t.assertEqual(json.loads(gov("status")[1])["leases"], [])


@case("F", "stopping when nothing runs is harmless")
def _():
    t.assertFalse(json.loads(gov("kill")[1])["evicted"])


@case("F", "a model that runs too long is stopped")
def _():
    t0 = time.time()
    code, _, _ = gov("run", "--app", "t", "--name", "slow", "--est-mb", "10", "--timeout", "2", "--", *burner(5, 60))
    t.assertEqual(code, 124)
    t.assertLess(time.time() - t0, 15)
    t.assertEqual([e for e in events() if e["type"] == "model.run" and e["data"]["name"] == "slow"][-1]["data"]["end"], "timeout")


@case("F", "each model is capped at its own measured need, not the ceiling")
def _():
    out = py("import json; from mitra_workers import models; a = models.governed('t', 's', 160, ['x']); b = models.governed('t', 'b', 950, ['x']); "
             "print(json.dumps([a[a.index('--budget-mb') + 1], b[b.index('--budget-mb') + 1]]))")
    t.assertEqual(out, ["186", "1024"])
    rc, _, err = gov("run", "--app", "t", "--name", "creeper", "--est-mb", "60", "--budget-mb", "76", "--", *burner(260, 30))
    t.assertEqual(rc, 137, err)


@case("F", "the optimizer removes only what is old and clears a lock left by a crash")
def _():
    tmp = HOME / "tmp"
    tmp.mkdir(exist_ok=True)
    old, new = tmp / "old.bin", tmp / "new.bin"
    old.write_bytes(b"x" * 4096); new.write_bytes(b"x")
    past = time.time() - 3 * 86400
    os.utime(old, (past, past))
    (HOME / "run" / "model.lock").write_text('{"governor_pid": 999999, "name": "ghost", "app": "t"}', "utf-8")
    code, out = cli("optimize")
    t.assertEqual(code, 0, out)
    t.assertFalse(old.exists())
    t.assertTrue(new.exists())
    t.assertFalse((HOME / "run" / "model.lock").exists())
    t.assertTrue(any(e["type"] == "optimizer.run" for e in events()))


# ============================================================================================
# G. TwinMind pipeline (the parts that need no model)
# ============================================================================================
TURNS = ["Morning everyone, quick standup today.", "The export job is done for PDF but CSV still fails on large invoices.", "Okay.",
         "The release stays on the twentieth, with the twenty-fourth as the fallback date.",
         "The staging database is at ninety percent disk and old snapshots must be cleared."]
SRC = "CSV fails on invoices with more than two hundred line items. The release stays on the twentieth. Sam, please fix it by Thursday."


@case("G", "the gist is the same every time and costs no model")
def _():
    d = py(f"import json; from mitra_workers import gist; t = {TURNS!r}; a, b = gist.extract(t), gist.extract(t); print(json.dumps([a, a == b]))")
    t.assertTrue(d[0] and d[1])
    S["gist"] = d[0]


@case("G", "every gist sentence is quoted word for word")
def _():
    for item in S["gist"]:
        t.assertTrue(any(item["text"] in turn for turn in TURNS), item)
    t.assertNotIn("Okay.", [i["text"] for i in S["gist"]], "filler is never the gist")


@case("G", "numbers spoken as words are understood")
def _():
    d = py("import json; from mitra_workers import grounding; print(json.dumps(sorted(grounding.spoken_numbers('two hundred and five items on the twenty-fourth, ninety percent'))))")
    t.assertEqual(d, ["205", "24", "90"])


@case("G", "a note with an invented number is removed")
def _():
    d = py(f"import json; from mitra_workers import grounding; print(json.dumps(grounding.guard_bullets(['CSV fails above 200 line items.', 'Release is on the 20th.', 'Revenue grew 45 percent.'], {SRC!r})))")
    t.assertEqual(d[0], ["CSV fails above 200 line items.", "Release is on the 20th."])
    t.assertEqual(len(d[1]), 1)


@case("G", "an owner or date never heard with the task is removed")
def _():
    acts = [{"owner": "Sam", "task": "fix the CSV timeout on invoices", "due": "Thursday"}, {"owner": "Rahul", "task": "fix the release line items", "due": "Friday"},
            {"owner": "Sam", "task": "book flights to Singapore tomorrow", "due": None}]
    d = py(f"import json; from mitra_workers import grounding; print(json.dumps(grounding.guard_actions({acts!r}, {SRC!r})))".replace("None", "None"))
    t.assertEqual([a["owner"] for a in d[0]], ["Sam", ""])
    t.assertEqual(d[0][1]["due"], None)
    t.assertTrue(d[1])


@case("G", "the model's notes are parsed into topic, points, decisions and questions")
def _():
    d = py(r"import json; from mitra_workers import meeting; print(json.dumps(meeting.parse_notes('Topic: Export\nPoints:\n- one\n- two\nDecisions:\n- None\nOpen questions:\n- who owns it?')))")
    t.assertEqual((d["topic"], d["points"], d["decisions"], d["open_questions"]), ("Export", ["one", "two"], [], ["who owns it?"]))


@case("G", "an action list that is not valid JSON is treated as no actions")
def _():
    d = py("import json; from mitra_workers import meeting; print(json.dumps([meeting.parse_actions('{\"actions\": [{\"owner\": \"A\"'), meeting.parse_actions('{\"actions\": [{\"owner\": \"A\", \"task\": \"x\", \"due\": null}]}')]))")
    t.assertEqual(d[0], [[], False])
    t.assertTrue(d[1][1] and d[1][0][0]["owner"] == "A")


@case("G", "a long meeting is cut into sections of about 420 words")
def _():
    t.assertEqual(py("import json; from mitra_workers import meeting; print(json.dumps(len(meeting.chunk(['word ' * 200] * 5))))"), 2)


@case("G", "merged notes drop near-duplicates and say which section each came from")
def _():
    code = ("import json; from mitra_workers import meeting; r = lambda i, p: {'index': i, 'notes': {'topic': 'T%d' % i, 'points': p, 'decisions': [], 'open_questions': []}, 'actions': [], 'title': 'A title', 'flags': []}; "
            "print(json.dumps(meeting.merge([r(0, ['The export fails on large invoices']), r(1, ['The export fails on large invoices.', 'Disk is nearly full'])])))")
    d = py(code)
    t.assertEqual([[p["text"], p["section"]] for p in d["points"]], [["The export fails on large invoices", 1], ["Disk is nearly full", 2]])
    t.assertEqual(d["topics"], ["T0", "T1"])


@case("G", "speaker turns are read in seconds or in samples")
def _():
    code = ("import json; from mitra_workers import models; print(json.dumps([models.parse_turns({'speaker_turns': [{'start_s': 0.0, 'end_s': 4.0, 'speaker_id': 3}, {'start_s': 4.0, 'end_s': 9.0, 'speaker_id': 0}]}), "
            "models.parse_turns({'speaker_turns': [{'start_sample': 16000, 'end_sample': 48000, 'speaker_id': 1}]})]))")
    d = py(code)
    t.assertEqual([x["speaker"] for x in d[0]], ["Speaker 1", "Speaker 2"], "speakers are numbered in the order they first speak")
    t.assertEqual((d[1][0]["start"], d[1][0]["end"]), (1.0, 3.0))


@case("G", "each transcript line takes the speaker who overlaps it most")
def _():
    code = ("import json; from mitra_workers import models; t = models.parse_turns({'speaker_turns': [{'start_s': 0.0, 'end_s': 4.0, 'speaker_id': 3}, {'start_s': 4.0, 'end_s': 9.0, 'speaker_id': 0}]}); "
            "s = [{'start': 0.5, 'end': 3.0, 'text': 'a'}, {'start': 4.2, 'end': 8.0, 'text': 'b'}, {'start': 3.5, 'end': 4.4, 'text': 'c'}]; models.assign_speakers(s, t); print(json.dumps([x.get('speaker') for x in s]))")
    t.assertEqual(py(code), ["Speaker 1", "Speaker 2", "Speaker 1"])


def _job(base, body, wait=240):
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", body, base=base)
    t.assertEqual(s, 200, r)
    for _ in range(wait):
        job = http("GET", "/api/jobs/" + r["id"], base=base)[1]
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(1)
    t.fail(f"job did not finish in {wait} s")


@case("G", "with no model available the memo is still written, and says what was skipped")
def _():
    home = TMP / "home-nomodel"
    write_config(home, 7487, model_budget_mb=100)
    base = re.search(r"http://[\d.:]+", cli("open", "twinmind", home=home)[1]).group(0)
    S["nm_home"], S["nm_base"] = home, base
    job = _job(base, {"path": str(DOCS / "standup.txt"), "title": "No model standup", "attendees": "Priya, Sam, Dana"})
    t.assertEqual(job["status"], "done", job)
    t.assertEqual([s["stage"] for s in job["steps"] if s["status"] == "skipped"], ["transcribe", "diarize", "understand"])
    S["nm_memo"] = Path(job["result"]["path"]).read_text("utf-8")
    t.assertTrue(job["result"]["path"].startswith(str(TMP / "dropbox")), "the memo goes to the app's Dropbox folder")


@case("G", "the memo follows your MeetingNoter layout")
def _():
    memo = S["nm_memo"]
    order = [memo.index(h) for h in ("# No model standup", "**Attendees:** Priya, Sam, Dana", "Meeting Core Focus", "Key Discussion Points", "Action Items", "Follow-up Needed", "Appendix: Transcript")]
    t.assertEqual(order, sorted(order), "sections must be in the MeetingNoter order")
    t.assertIn("layout: meetingnoter", memo)


@case("G", "the memo records every stage, including the ones that did not run")
def _():
    memo = S["nm_memo"]
    for line in ("transcribe: skipped: input was already text", "diarize: skipped", "understand: skipped", "gist: "):
        t.assertIn(line, memo)
    t.assertIn("notes model did not run", memo)


@case("G", "commitments and decisions are quoted from the transcript even without a model")
def _():
    memo = S["nm_memo"]
    heard = memo.split("### Commitments heard")[1].split("## ")[0]
    t.assertIn("Sam, please fix the CSV timeout by Thursday", heard)
    t.assertIn("I will clear snapshots", heard)
    t.assertIn("twentieth", memo.split("### Decisions stated in the transcript")[1].split("## ")[0])
    quoted = [l[2:] for l in memo.split("Meeting Core Focus")[1].split("Key Discussion Points")[0].splitlines() if l.startswith("> ")]
    t.assertTrue(quoted)
    for line in quoted:
        t.assertIn(line, TRANSCRIPT)


@case("G", "the transcript is kept whole at the end of the memo")
def _():
    body = S["nm_memo"].split("Appendix: Transcript")[1]
    for line in TRANSCRIPT.strip().splitlines():
        t.assertIn(line, body)


@case("G", "saved meetings are listed with their gist and found by search")
def _():
    base = S["nm_base"]
    listed = http("GET", "/api/apps/twinmind/meetings", base=base)[1]
    t.assertEqual(len(listed), 1)
    t.assertTrue(listed[0]["gist"])
    hits = http("GET", "/api/apps/twinmind/search?q=snapshots", base=base)[1]
    t.assertTrue(any("snapshots" in h["text"].lower() for h in hits))
    t.assertEqual(len({(h["meeting"], h["text"]) for h in hits}), len(hits), "the same sentence is not listed twice")


@case("G", "TwinMind reads Word, RTF and OpenDocument transcripts")
def _():
    base = S["nm_base"]
    (DOCS / "talk.rtf").write_bytes(rb"{\rtf1 Priya: Sam, please send the report by Friday.\par Sam: I will send it tomorrow.\par}")
    job = _job(base, {"path": str(DOCS / "talk.rtf"), "title": "RTF talk"})
    t.assertEqual(job["status"], "done", job)
    t.assertIn("please send the report by Friday", Path(job["result"]["path"]).read_text("utf-8").split("### Commitments heard")[1])


@case("G", "an empty transcript fails with a clear message")
def _():
    job = _job(S["nm_base"], {"path": str(DOCS / "empty.txt")})
    t.assertEqual(job["status"], "failed")
    t.assertIn("empty", job["error"].lower())
    cli("stop", home=S["nm_home"])


@case("G", "a job that has not written anything yet reads as starting")
def _():
    job = http("GET", "/api/jobs/abc123", base=app("twinmind"))[1]
    t.assertEqual(job["status"], "starting")


# ============================================================================================
# H. memory log: everything, from every app, in one place
# ============================================================================================
@case("H", "an app's events are appended to the log")
def _():
    base = app("markdown-reader")
    for _ in range(3):
        http("POST", "/api/log", {"app": "markdown-reader", "session": "s1", "type": "app.open", "data": {}}, base=base)
    http("POST", "/api/log", {"app": "markdown-reader", "session": "s1", "type": "file.open", "data": {"path": str(DOCS / "note.md")}}, base=base)
    http("POST", "/api/log", {"app": "markdown-reader", "session": "s1", "type": "app.close", "data": {"active_ms": 120000}}, base=base)
    logged = [e for e in events() if e["app"] == "markdown-reader"]
    t.assertGreaterEqual(len([e for e in logged if e["type"] == "app.open"]), 3)
    t.assertTrue(all(e.get("session") == "s1" for e in logged if e["type"] == "file.open"))


@case("H", "a malformed event is refused")
def _():
    t.assertEqual(http("POST", "/api/log", {"app": "x"}, base=app("markdown-reader"))[0], 400)


@case("H", "separate app processes write to one shared log")
def _():
    apps_seen = {e["app"] for e in events()}
    t.assertTrue({"markdown-reader", "to-markdown", "pdf-reader", "twinmind", "shell"} <= apps_seen, apps_seen)
    t.assertEqual(len(list((HOME / "memory" / "events").glob("*.jsonl"))), 1, "one file per day, not one per app")


@case("H", "every app start and stop is in the log with how long it lived")
def _():
    ev = events()
    t.assertGreaterEqual(len([e for e in ev if e["type"] == "app.spawn"]), 5)
    exits = [e["data"] for e in ev if e["type"] == "app.exit"]
    t.assertTrue(exits)
    for e in exits:
        t.assertIn(e["reason"], ("stopped", "window closed", "idle"))
        t.assertIn("lived_s", e)
        t.assertIn("mb", e)


@case("H", "the report counts opens and active time per app")
def _():
    r = http("GET", "/api/memory/report?days=7")[1]
    st = r["report"]["apps"]["markdown-reader"]
    t.assertGreaterEqual(st["opens"], 3)
    t.assertGreaterEqual(st["active_min"], 2.0)
    t.assertIn("## Usage by app", r["markdown"])


@case("H", "a report can be saved as a file")
def _():
    r = http("GET", "/api/memory/report?days=7&save=1")[1]
    t.assertTrue(Path(r["saved"]).exists())
    t.assertTrue(str(r["saved"]).startswith(str(HOME)))


@case("H", "the memory report command prints and saves the report")
def _():
    code, out = cli("memory", "report", "weekly")
    t.assertEqual(code, 0, out)
    t.assertIn("Saved to", out)


@case("H", "recently opened files are remembered per app")
def _():
    t.assertIn(str(DOCS / "note.md"), http("GET", "/api/recent?app_id=markdown-reader", base=app("markdown-reader"))[1])


@case("H", "the launcher offers the last files to pick up again")
def _():
    rec = http("GET", "/api/recent/all")[1]
    t.assertTrue(any(r["path"] == str(DOCS / "note.md") and r["app"] == "markdown-reader" for r in rec))


@case("H", "the most used app comes first")
def _():
    t.assertEqual(http("GET", "/api/apps")[1][0]["id"], "markdown-reader")


@case("H", "pruning rolls old days into counts and archives the raw lines")
def _():
    old = (date.today() - timedelta(days=200)).isoformat()
    ev = HOME / "memory" / "events"
    (ev / f"{old}.jsonl").write_text('{"ts":"x","app":"pdf-reader","type":"app.open"}\n' * 5, "utf-8")
    r = http("POST", "/api/memory/prune", {"keep_days": 90})[1]
    t.assertEqual(r["days_rolled"], 1)
    t.assertFalse((ev / f"{old}.jsonl").exists())
    t.assertEqual(json.loads((HOME / "memory" / "rollups" / f"{old}.json").read_text())["pdf-reader|app.open"], 5)
    t.assertTrue((HOME / "memory" / "archive" / f"{old}.jsonl.gz").exists())


@case("H", "pruning never touches recent days")
def _():
    t.assertTrue((HOME / "memory" / "events" / f"{date.today().isoformat()}.jsonl").exists())


@case("H", "each app's own output is kept in its own log file")
def _():
    logs = {f.name for f in (HOME / "logs").glob("*.log")}
    t.assertTrue({"markdown-reader.log", "twinmind.log", "pdf-reader.log"} <= logs, logs)


# ============================================================================================
# I. moving between systems
# ============================================================================================
OTHER_ROOT, OTHER_HOME = TMP / "system-b", TMP / "home-b"


@case("I", "push packs a versioned zip with its checksum")
def _():
    write_config(OTHER_HOME, 7497)
    (HOME / "apps" / "travel-app").mkdir(parents=True, exist_ok=True)
    (HOME / "apps" / "travel-app" / "mitra.app.json").write_text('{"id": "travel-app", "name": "Travel App"}', "utf-8")
    S["had_release"] = (ROOT / "release.json").read_bytes() if (ROOT / "release.json").exists() else None
    code, out = cli("push")
    t.assertEqual(code, 0, out)
    zips = sorted(RELEASES.glob("mitra-marketplace-*.zip"))
    t.assertEqual(len(zips), 1)
    t.assertTrue(Path(str(zips[0]) + ".sha256").exists())
    S["zip"] = zips[0]


@case("I", "the release folder carries the installers for a new system")
def _():
    t.assertTrue((RELEASES / "install.sh").exists() and (RELEASES / "install.ps1").exists())


@case("I", "the zip carries code, not models or build output")
def _():
    with zipfile.ZipFile(S["zip"]) as z:
        names = z.namelist()
    t.assertFalse([n for n in names if n.startswith(("models/", "runtimes/")) or "/target/" in n or n.endswith((".gguf", ".bin"))][:3])
    t.assertLess(S["zip"].stat().st_size, 60 << 20, "an update must stay small enough to sync quickly")
    for must in ("gateway/apps.go", "web/index.html", "apps/twinmind/worker.py", "workers/mitra_workers/bundle.py"):
        t.assertIn(must, names)


@case("I", "update --check reports without installing")
def _():
    OTHER_ROOT.mkdir(exist_ok=True)
    code, out = cli("update", "--check", home=OTHER_HOME, root=OTHER_ROOT)
    t.assertIn("Available", out)
    t.assertFalse((OTHER_ROOT / "web").exists())


@case("I", "update installs the release on the other system")
def _():
    code, out = cli("update", home=OTHER_HOME, root=OTHER_ROOT)
    t.assertEqual(code, 0, out)
    for f in ("web/index.html", "workers/mitra_workers/dispatch.py", "apps/twinmind/worker.py", "catalog.json", "release.json", f"bin/mitra-marketplace{EXE}"):
        t.assertTrue((OTHER_ROOT / f).exists(), f"missing after update: {f}")


@case("I", "the apps you created travel with the release")
def _():
    t.assertTrue((OTHER_HOME / "apps" / "travel-app" / "mitra.app.json").exists())


@case("I", "a second update says it is up to date")
def _():
    t.assertIn("Up to date", cli("update", home=OTHER_HOME, root=OTHER_ROOT)[1])


@case("I", "an update removes files the new release no longer ships")
def _():
    stale = OTHER_ROOT / "web" / "stale-file.txt"
    stale.write_text("left over from an old version", "utf-8")
    time.sleep(1.1)
    t.assertEqual(cli("push")[0], 0)
    code, out = cli("update", home=OTHER_HOME, root=OTHER_ROOT)
    t.assertEqual(code, 0, out)
    t.assertFalse(stale.exists())


@case("I", "a zip that was changed after it was packed is refused")
def _():
    time.sleep(1.1)
    t.assertEqual(cli("push")[0], 0)
    newest = sorted(RELEASES.glob("mitra-marketplace-*.zip"))[-1]
    with open(newest, "ab") as f:
        f.write(b"tampered")
    code, out = cli("update", home=OTHER_HOME, root=OTHER_ROOT)
    t.assertNotEqual(code, 0)
    t.assertIn("checksum", out.lower())


@case("I", "old releases can be pruned")
def _():
    code, out = cli("releases", "prune", "1")
    t.assertEqual(len(list(RELEASES.glob("mitra-marketplace-*.zip"))), 1, out)
    if S.get("had_release") is None:
        (ROOT / "release.json").unlink(missing_ok=True)
    else:
        (ROOT / "release.json").write_bytes(S["had_release"])


@case("I", "one app can be packed on its own")
def _():
    a = HOME / "apps" / "zip-app"
    (a / "ui").mkdir(parents=True, exist_ok=True)
    (a / "mitra.app.json").write_text('{"id": "zip-app", "name": "Zip App"}', "utf-8")
    (a / "ui" / "index.html").write_text("<p>zip app</p>", "utf-8")
    code, out = cli("pack", "zip-app")
    t.assertEqual(code, 0, out)
    t.assertTrue((RELEASES / "apps" / "zip-app.mitra-app.zip").exists())


@case("I", "install finds an app zip on the system and installs it")
def _():
    other = TMP / "home-c"
    write_config(other, 7496)
    code, out = cli("install", "zip-app", home=other, timeout=400)
    t.assertEqual(code, 0, out)
    t.assertIn("Installed app zip-app", out)
    t.assertEqual((other / "apps" / "zip-app" / "ui" / "index.html").read_text("utf-8"), "<p>zip app</p>")


@case("I", "a zip cannot write outside the app's folder")
def _():
    other = TMP / "home-c"
    evil = RELEASES / "apps" / "evil.mitra-app.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("mitra.app.json", '{"id": "evil", "name": "Evil"}')
        z.writestr("../../escaped.txt", "x")
    code, out = cli("install", str(evil), home=other)
    t.assertNotEqual(code, 0)
    t.assertFalse((other / "escaped.txt").exists() or (TMP / "escaped.txt").exists())


@case("I", "an installed app appears as an icon and runs as its own process")
def _():
    listed = [a["id"] for a in http("GET", "/api/apps")[1]]
    t.assertIn("zip-app", listed)
    base = app("zip-app")
    t.assertEqual(http("GET", "/apps/zip-app/", raw=True, base=base)[1], b"<p>zip app</p>")
    http("POST", "/api/stop/zip-app")


# ============================================================================================
# J. security
# ============================================================================================
@case("J", "the launcher refuses a request addressed to another host name")
def _():
    t.assertEqual(http("GET", "/api/ping", headers={"Host": "evil.example"})[0], 403)


@case("J", "an app's process refuses a request addressed to another host name")
def _():
    t.assertEqual(http("GET", "/api/ping", headers={"Host": "evil.example"}, base=app("pdf-reader"))[0], 403)


@case("J", "localhost is accepted as well as 127.0.0.1")
def _():
    t.assertEqual(http("GET", "/api/ping", headers={"Host": f"localhost:{PORT}"})[0], 200)


@case("J", "the launcher refuses a post from another website")
def _():
    t.assertEqual(http("POST", "/api/log", {"app": "x", "type": "y"}, headers={"Origin": "http://evil.example"})[0], 403)


@case("J", "an app refuses a post from another website")
def _():
    t.assertEqual(http("POST", "/api/log", {"app": "x", "type": "y"}, headers={"Origin": "http://evil.example"}, base=app("pdf-reader"))[0], 403)


@case("J", "another website cannot launch or stop apps")
def _():
    http("POST", "/api/stop/assistant")
    t.assertEqual(http("POST", "/api/launch/assistant", {}, headers={"Origin": "http://evil.example"})[0], 403)
    t.assertEqual(http("POST", "/api/stop/twinmind", {}, headers={"Origin": "http://evil.example"})[0], 403)
    t.assertNotIn("assistant", [r["id"] for r in http("GET", "/api/running")[1]])


@case("J", "one app's page may call another only with a local origin")
def _():
    s, r, _ = http("POST", "/api/log", {"app": "x", "type": "y"}, headers={"Origin": f"http://127.0.0.1:{PORT}"}, base=app("pdf-reader"))
    t.assertEqual(s, 200, r)


@case("J", "an app's files cannot be reached from outside its folder")
def _():
    base = app("markdown-reader")
    for path in ("/apps/markdown-reader/..%2F..%2Fmitra.app.json", "/apps/markdown-reader/../../catalog.json", "/apps/markdown-reader/..%5C..%5Ccatalog.json"):
        s, body, _ = http("GET", path, raw=True, base=base)
        t.assertNotEqual(s, 200, path)


@case("J", "static files cannot be reached from outside the static folder")
def _():
    for path in ("/static/..%2Findex.html", "/static/..%2F..%2Fcatalog.json", "/static/%2e%2e/%2e%2e/catalog.json"):
        s, body, _ = http("GET", path, raw=True)
        t.assertFalse(s == 200 and b"capabilities" in body.lower() and b"candidates" in body, path)
        t.assertNotIn(b'"candidates"', body, path)


@case("J", "an app id cannot be a path")
def _():
    for bad in ("a.b", "..", "x%5Cy"):
        t.assertNotEqual(http("POST", f"/api/launch/{bad}", follow=False)[0], 200, bad)   # no body: a path the router rejects is closed unread
    t.assertEqual(len(http("GET", "/api/running")[1]), len(list((HOME / "run" / "apps").glob("*.json"))), "nothing odd was started")
    t.assertEqual(cli("app", "../apps/pdf-reader")[0], 2)


@case("J", "a job id cannot be a path")
def _():
    t.assertEqual(http("GET", "/api/jobs/a.b", base=app("twinmind"))[0], 400)


@case("J", "the query passed to a launched app cannot change which page opens")
def _():
    r = launch("pdf-reader", query="path=x.pdf&y=1#frag/../../evil?z")
    u = urllib.parse.urlparse(r["url"])
    t.assertEqual((u.hostname, u.path, u.fragment), ("127.0.0.1", "/apps/pdf-reader/", ""))
    t.assertEqual(urllib.parse.parse_qs(u.query)["path"], ["x.pdf"])


@case("J", "an uploaded file's name cannot place it outside the temp folder")
def _():
    s, up, _ = http("POST", "/api/upload?name=..%2F..%2Fevil.txt", b"x", headers={"Content-Type": "application/octet-stream"}, base=app("to-markdown"))
    t.assertEqual(s, 200)
    t.assertEqual(Path(up["path"]).parent, HOME / "tmp")


@case("J", "answers carry the headers that stop other sites reading them")
def _():
    for base in (BASE, app("pdf-reader")):
        h = {k.lower(): v for k, v in http("GET", "/api/ping", base=base)[2].items()}
        t.assertEqual(h["x-content-type-options"], "nosniff")
        t.assertEqual(h["cross-origin-resource-policy"], "same-origin")


@case("J", "apps listen on this device only")
def _():
    import socket
    port = launch("pdf-reader")["port"]
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        pass                                   # reachable from this device
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))   # no packet is sent; this only asks which address faces the network
        lan = probe.getsockname()[0]
    except OSError:
        lan = "127.0.0.1"
    finally:
        probe.close()
    if lan.startswith("127."):
        skip("this device has no network address to test from")
    for p in (port, PORT):
        with t.assertRaises(OSError, msg=f"port {p} answers on the network address {lan}"):
            socket.create_connection((lan, p), timeout=2).close()


# ============================================================================================
# K. resources and the package
# ============================================================================================
@case("K", "ordinary requests are cheap and their cost is logged")
def _():
    http("GET", "/api/apps"); http("GET", "/api/models"); http("GET", "/api/memory/report?days=1")
    http("GET", "/api/apps/twinmind/status", base=app("twinmind"))
    calls = [e["data"] for e in events() if e["type"] == "api.call" and "worker_mb" in e["data"]]
    t.assertGreaterEqual(len(calls), 5)
    worst = max(calls, key=lambda c: c["worker_mb"])
    t.assertGreater(worst["worker_mb"], 0)
    t.assertLessEqual(worst["worker_mb"], 80, f"a worker used {worst['worker_mb']} MB for {worst['path']}")
    t.assertLess(min(c["ms"] for c in calls if c["path"] == "apps"), 1500)


@case("K", "no model is in memory when nothing asked for one")
def _():
    t.assertEqual(http("GET", "/api/system")[1]["leases"], [])


@case("K", "all running app processes together stay small")
def _():
    run = http("GET", "/api/running")[1]
    t.assertGreaterEqual(len(run), 3)
    t.assertLessEqual(sum(r["mb"] for r in run), 40 * len(run))
    S["sum_mb"] = sum(r["mb"] for r in run)


@case("K", "the choice of model for every capability respects the budget")
def _():
    m = http("GET", "/api/models")[1]
    for c in m["capabilities"]:
        if c.get("model"):
            t.assertLessEqual(c["est_mb"], m["budget_mb"], c["capability"])


@case("K", "the whole package is inside the 2 GB limit")
def _():
    s = json.loads(subprocess.run([sys.executable, "-m", "mitra_workers.bundle", "size", "--json"], capture_output=True, text=True, env=env(), creationflags=NOWIN).stdout)
    S["size"] = s
    t.assertGreater(s["package_mb"], 5)
    t.assertLess(s["total_mb"], 2048, f"Mitra uses {s['total_mb']} MB on disk")


@case("K", "the size command prints the breakdown")
def _():
    code, out = cli("size")
    t.assertEqual(code, 0, out)
    for part in ("launcher and governor", "models in the package", "Everything Mitra uses"):
        t.assertIn(part, out)


@case("K", "the models command shows one model per capability and who uses it")
def _():
    code, out = cli("models")
    t.assertEqual(code, 0, out)
    for part in ("assistant", "transcription", "diarization", "meeting-notes", "used by twinmind"):
        t.assertIn(part, out)


@case("K", "the models the apps use are inside the package")
def _():
    if not (ROOT / "models").is_dir():
        skip("models have not been copied in; run: mitra-marketplace models sync")
    rows = json.loads(subprocess.run([sys.executable, "-m", "mitra_workers.bundle", "models", "--json"], capture_output=True, text=True, env=env(), creationflags=NOWIN).stdout)
    for r in rows:
        t.assertTrue(r["in_package"], f"{r['capability']} is read from {r['file']}")


@case("K", "every capability is ready with the model library unplugged")
def _():
    if not (ROOT / "models").is_dir():
        skip("models have not been copied in; run: mitra-marketplace models sync")
    home = TMP / "home-unplugged"
    write_config(home, 7486, models_dir=str(TMP / "no-such-drive"), llama_server="")
    d = py("import json; from mitra_workers import models; print(json.dumps({c: models.pick(c) for c in ('assistant', 'meeting-notes', 'transcription', 'diarization')}))", home=home)
    for cap, p in d.items():
        t.assertTrue(p["ready"], f"{cap}: {p.get('hint')}")
        t.assertTrue(p["file"].startswith(str(ROOT / "models")), p["file"])


@case("K", "the llama runtime in the package is the CPU build only")
def _():
    d = ROOT / "runtimes" / "llama"
    if not d.is_dir():
        skip("the llama runtime has not been copied in; run: mitra-marketplace models sync")
    t.assertLess(sum(f.stat().st_size for f in d.rglob("*") if f.is_file()), 120 << 20)
    t.assertFalse([f.name for f in d.rglob("*") if "cuda" in f.name.lower() or "rocm" in f.name.lower()])


# ============================================================================================
# L. real models (skipped with --quick)
# ============================================================================================
def _ready(capability):
    if QUICK:
        skip("--quick")
    cap = next(c for c in http("GET", "/api/models")[1]["capabilities"] if c["capability"] == capability)
    if not cap["ready"]:
        skip(f"{capability} not available on this device: " + cap.get("hint", ""))
    return cap


@case("L", "the assistant answers inside its limit and is unloaded straight after")
def _():
    _ready("assistant")
    s, r, _ = http("POST", "/api/ask", {"app_id": "assistant", "prompt": "What is the capital of France? Answer in one word."}, base=app("assistant"))
    t.assertEqual(s, 200, r)
    t.assertIn("paris", r["text"].lower())
    run = [e for e in events() if e["type"] == "model.run" and e["app"] == "assistant"][-1]["data"]
    t.assertLessEqual(run["budget_mb"], http("GET", "/api/models")[1]["budget_mb"])
    t.assertLessEqual(run["peak_mb"], run["budget_mb"])
    t.assertEqual(run["end"], "released")
    t.assertEqual(json.loads(gov("status")[1])["leases"], [])


@case("L", "the assistant's model is loaded from inside the package")
def _():
    _ready("assistant")
    if not (ROOT / "models").is_dir():
        skip("models have not been copied in")
    cap = next(c for c in http("GET", "/api/models")[1]["capabilities"] if c["capability"] == "assistant")
    t.assertTrue(cap["file"].startswith(str(ROOT / "models")), cap["file"])
    t.assertTrue(cap["runtime_path"].startswith(str(ROOT / "runtimes")), cap["runtime_path"])


@case("L", "the assistant keeps the thread of a conversation")
def _():
    _ready("assistant")
    hist = [{"role": "user", "content": "My project is called Kestrel."}, {"role": "assistant", "content": "Understood, the project is Kestrel."}]
    s, r, _ = http("POST", "/api/ask", {"app_id": "assistant", "prompt": "What is my project called? One word.", "history": hist}, base=app("assistant"))
    t.assertEqual(s, 200, r)
    t.assertIn("kestrel", r["text"].lower())


@case("L", "meeting notes from a transcript, in the MeetingNoter layout")
def _():
    _ready("meeting-notes")
    base = app("twinmind")
    job = _job(base, {"path": str(DOCS / "standup.txt"), "title": "Test standup", "attendees": "Priya, Sam, Dana"})
    t.assertEqual(job["status"], "done", job)
    notes = Path(job["result"]["path"]).read_text("utf-8")
    S["memo"] = notes
    order = [notes.index(h) for h in ("Meeting Core Focus", "Key Discussion Points", "Action Items", "Follow-up Needed", "Appendix: Transcript")]
    t.assertEqual(order, sorted(order))
    t.assertIn("diarize: skipped", notes)
    t.assertIn("**Decisions made:**", notes)
    t.assertEqual(json.loads(gov("status")[1])["leases"], [])


@case("L", "the memo's gist, commitments and decision come from the transcript")
def _():
    _ready("meeting-notes")
    head = S["memo"].split("Appendix: Transcript")[0]
    quoted = [l[2:] for l in head.split("Meeting Core Focus")[1].split("Key Discussion Points")[0].splitlines() if l.startswith("> ")]
    t.assertTrue(quoted)
    for line in quoted:
        t.assertIn(line, TRANSCRIPT)
    heard = head.split("### Commitments heard")[1].split("## ")[0]
    t.assertIn("Sam, please fix the CSV timeout by Thursday", heard)
    t.assertIn("I will clear snapshots", heard)
    t.assertIn("twentieth", head.split("Key Discussion Points")[1].split("Action Items")[0], "the stated decision must be recorded")


@case("L", "an action item's date is shown only where the transcript ties it to the task")
def _():
    _ready("meeting-notes")
    actions = S["memo"].split("Action Items")[1].split("### Commitments heard")[0]
    t.assertIn("CSV", actions, "the CSV fix must be captured as an action item")
    for line in [l for l in actions.splitlines() if "(due " in l]:
        due = line.split("(due ")[1].rstrip(")").lower()
        words = re.findall(r"[a-z]{4,}", line.split("**:")[1].split("(due")[0].lower())
        t.assertTrue(any(due in tl.lower() and any(w in tl.lower() for w in words) for tl in TRANSCRIPT.splitlines()), line)


@case("L", "two apps asking for a model take turns; never two models at once")
def _():
    _ready("assistant")
    a_base, t_base = app("assistant"), app("twinmind")
    out, most = {}, [0]
    def ask():
        out["ask"] = http("POST", "/api/ask", {"app_id": "assistant", "prompt": "Name three colours.", "max_tokens": 40}, base=a_base)
    def meeting():
        out["job"] = _job(t_base, {"path": str(DOCS / "standup.txt"), "title": "Turns"})
    threads = [threading.Thread(target=meeting), threading.Thread(target=ask)]
    threads[0].start(); time.sleep(2); threads[1].start()
    while any(th.is_alive() for th in threads):
        most[0] = max(most[0], len(json.loads(gov("status")[1])["leases"]))
        time.sleep(0.25)
    t.assertLessEqual(most[0], 1, "two models were in memory at once")
    t.assertEqual(out["job"]["status"], "done", out["job"])
    t.assertEqual(out["ask"][0], 200, out["ask"][1])
    used = {e["app"] for e in events() if e["type"] == "model.run" and e["app"] in ("assistant", "twinmind")}
    t.assertEqual(used, {"assistant", "twinmind"})


@case("L", "a recording is transcribed, with speakers, each model under its own cap")
def _():
    _ready("transcription")
    if os.name != "nt":
        skip("needs Windows speech synthesis to make the recording")
    wav = DOCS / "spoken.wav"
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }); "
          f"$s.SetOutputToWaveFile('{wav}'); $s.SelectVoice($v[0]); "
          "$s.Speak('Please fix the export by Thursday. The release stays on the twentieth.'); "
          "if ($v.Count -gt 1) { $s.SelectVoice($v[1]) }; "
          "$s.Speak('I will. The staging database is at ninety percent disk, so I will clear old snapshots this afternoon.'); "
          "$s.Dispose(); Write-Output $v.Count")
    voices = int(subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, text=True, creationflags=NOWIN).stdout.strip().splitlines()[-1])
    job = _job(app("twinmind"), {"path": str(wav), "title": "Spoken test"})
    t.assertEqual(job["status"], "done", job)
    memo = Path(job["result"]["path"]).read_text("utf-8")
    t.assertIn("thursday", memo.lower())
    t.assertRegex(memo.lower(), r"\[00:00:\d\d\]")
    diar = next(c for c in http("GET", "/api/models")[1]["capabilities"] if c["capability"] == "diarization")
    if diar["ready"] and voices > 1:
        body = memo.split("Appendix: Transcript")[1]
        t.assertIn("Speaker 1:", next(l for l in body.splitlines() if "thursday" in l.lower()))
        t.assertIn("Speaker 2:", next(l for l in body.splitlines() if "snapshots" in l.lower()))
        t.assertRegex(memo, r"diarize: .*2 speakers")
        d = [e for e in events() if e["type"] == "model.run" and "diarization" in e["data"]["name"]][-1]["data"]
        t.assertLessEqual(d["peak_mb"], d["budget_mb"], f"{d['name']} peaked at {d['peak_mb']} MB")
        t.assertLessEqual(d["budget_mb"], 250)
        t.assertEqual(d["end"], "exit")
    runs = [e["data"] for e in events() if e["type"] == "model.run" and e["data"]["name"].startswith("whisper")]
    S["whisper_peaks"] = [r["peak_mb"] for r in runs]
    ceiling = http("GET", "/api/models")[1]["budget_mb"]
    for run in runs:
        t.assertLessEqual(run["budget_mb"], ceiling)
        t.assertLessEqual(run["peak_mb"], run["budget_mb"], f"{run['name']} peaked at {run['peak_mb']} MB; all runs: {S['whisper_peaks']}")


@case("L", "the three TwinMind models ran one after another, never together")
def _():
    _ready("transcription")
    runs = [e for e in events() if e["type"] == "model.run" and e["app"] == "twinmind"]
    names = {r["data"]["name"].split("-")[0] for r in runs}
    if len(names) < 2:
        skip("the recording test did not run every stage")
    spans = sorted((datetime.fromisoformat(r["ts"]) - timedelta(milliseconds=r["data"].get("ms", 0)), datetime.fromisoformat(r["ts"])) for r in runs)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        t.assertLessEqual(e1, s2 + timedelta(seconds=1), "two model runs overlapped")


# ---- last: nothing is left behind -----------------------------------------------------------
# ============================================================================================
# M. files: Windows "Open with", drop to open, and the document's own structure kept
#    (added in 0.7.0 at the end, so the numbers of the earlier cases did not move)
# ============================================================================================
def _zip(p, files):
    with zipfile.ZipFile(p, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


def make_docx_rich(p):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    r = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    pstyle = lambda style: '<w:pStyle w:val="%s"/>' % style if style else ""
    para = lambda style, body, num="": f'<w:p><w:pPr>{pstyle(style)}{num}</w:pPr>{body}</w:p>'
    run = lambda text, props="": f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'
    num = lambda nid, lvl: f'<w:numPr><w:ilvl w:val="{lvl}"/><w:numId w:val="{nid}"/></w:numPr>'
    cell = lambda body, span="": f'<w:tc><w:tcPr>{span}</w:tcPr>{body}</w:tc>'
    doc = (f'<w:document {w} {r}><w:body>'
           + para("Titel", run("Project Charter"))
           + para("Kop1", run("Scope", "<w:b/>"))
           + para("", run("The ") + run("dead", "<w:b/>") + run("line", "<w:b/>") + run(" is ") + run("firm", "<w:i/>") + run(", see ")
                  + f'<w:hyperlink r:id="rId5">{run("the site")}</w:hyperlink>' + run(" and it is ") + run("not", '<w:b w:val="0"/>') + run(" bold."))
           + para("", run("Design"), num(1, 0)) + para("", run("Wireframes"), num(1, 1)) + para("", run("Build"), num(1, 0))
           + para("", run("Plan"), num(2, 0)) + para("", run("Ship"), num(2, 0))
           + para("Kop2", run("Owners"))
           + '<w:tbl><w:tr>' + cell(para("", run("Owner"))) + cell(para("", run("Notes"))) + '</w:tr><w:tr>'
           + cell(para("", run("Sam"))) + cell(para("", run("First line")) + para("", run("Second line"))) + '</w:tr><w:tr>'
           + cell(para("", run("Everyone")), '<w:gridSpan w:val="2"/>') + '</w:tr></w:tbl>'
           + '<w:sdt><w:sdtContent>' + para("", run("Inside a content control.")) + '</w:sdtContent></w:sdt>'
           + '</w:body></w:document>')
    style = lambda sid, name, extra="": f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>{extra}</w:style>'
    lvl = lambda i, fmt: f'<w:lvl w:ilvl="{i}"><w:numFmt w:val="{fmt}"/></w:lvl>'
    _zip(p, {
        "word/document.xml": doc,
        # the style ids are not English, as in a Word installed in another language: only the names say what they are
        "word/styles.xml": f'<w:styles {w}>' + style("Titel", "Title") + style("Kop1", "heading 1") + style("Kop2", "Sub", '<w:basedOn w:val="Basis2"/>')
                           + style("Basis2", "Section label", '<w:pPr><w:outlineLvl w:val="1"/></w:pPr>') + '</w:styles>',
        "word/numbering.xml": f'<w:numbering {w}><w:abstractNum w:abstractNumId="0">{lvl(0, "bullet")}{lvl(1, "bullet")}</w:abstractNum>'
                              f'<w:abstractNum w:abstractNumId="1">{lvl(0, "decimal")}</w:abstractNum>'
                              '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>',
        "word/_rels/document.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                        '<Relationship Id="rId5" Target="https://example.org/site" TargetMode="External"/></Relationships>',
    })


def make_pptx_rich(p):
    ns = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
    shape = lambda role, paras: (f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="{role}"/></p:nvPr></p:nvSpPr><p:txBody>'
                                 + "".join(f'<a:p><a:pPr lvl="{l}"/><a:r><a:t>{t}</a:t></a:r></a:p>' for l, t in paras) + '</p:txBody></p:sp>')
    tc = lambda t: f'<a:tc><a:txBody><a:p><a:r><a:t>{t}</a:t></a:r></a:p></a:txBody></a:tc>'
    table = ('<p:graphicFrame><a:graphic><a:graphicData><a:tbl>'
             f'<a:tr>{tc("Quarter")}{tc("Goal")}</a:tr><a:tr>{tc("Q1")}{tc("Launch")}</a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>')
    slide = (f'<p:sld {ns}><p:cSld><p:spTree>' + shape("body", [(0, "Phase one"), (1, "Design review"), (0, "Phase two")])
             + shape("title", [(0, "Roadmap 2027")]) + shape("sldNum", [(0, "7")]) + table + '</p:spTree></p:cSld></p:sld>')
    _zip(p, {"ppt/slides/slide1.xml": slide})


def make_pdf_rich(p):
    """Three pages set the way a report is: a running header and footer, a title, section headings in a
    larger size, one heading in bold at body size, wrapped paragraphs, lists, and an address block."""
    def page(n, items):
        ops = [f"BT /F1 9 Tf 60 800 Td (Acme Quarterly Report) Tj ET"]
        ops += [f"BT /{font} {size} Tf 60 {y} Td ({text}) Tj ET" for font, size, y, text in items]
        ops.append(f"BT /F1 9 Tf 280 30 Td (Page {n} of 3) Tj ET")
        return "\n".join(ops).encode("latin-1")
    body = lambda y, text: ("F1", 11, y, text)
    pages = [
        page(1, [("F1", 22, 750, "Annual Review"), ("F1", 16, 715, "Revenue"),
                 body(690, "Revenue grew steadily through the year, helped by the new export"),
                 body(676, "feature and by two large renewals that closed in the third quar-"),
                 body(662, "ter of the year."),
                 body(634, "Costs stayed flat. The hosting bill fell after the move to the new"),
                 body(620, "region, and the saving paid for the two contractors we brought in."),
                 body(592, "- First point about costs"), body(578, "- Second point about hiring"),
                 body(550, "1. Renew the contract"), body(536, "2. Hire two engineers"),
                 ("F2", 11, 508, "Risks"),
                 body(486, "The largest risk is the renewal of the main supplier agreement in"),
                 body(472, "the spring, which is not yet")]),
        page(2, [body(770, "signed and may slip."),
                 body(742, "Acme Ltd"), body(728, "12 Hill Road"), body(714, "Pune 411001"),
                 body(686, "Hiring went to plan, with both engineering roles filled by the end"),
                 body(672, "of the second quarter and the design role filled in the autumn.")]),
        page(3, [("F1", 16, 750, "Outlook"),
                 body(725, "Next year the plan is to grow the export product into two further"),
                 body(711, "markets and to keep the team at its present size until midyear.")]),
    ]
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", None,
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>"]
    kids = []
    for stream in pages:
        kids.append(len(objs) + 1)
        objs.append(b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents %d 0 R/Resources<</Font<</F1 3 0 R/F2 4 0 R>>>>>>" % (len(objs) + 2))
        objs.append(b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream")
    objs[1] = b"<</Type/Pages/Kids[" + b" ".join(b"%d 0 R" % k for k in kids) + b"]/Count %d>>" % len(kids)
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj" % i + o + b"endobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, x)
    Path(p).write_bytes(bytes(out))


def make_odt_rich(p):
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
          'xmlns:xlink="http://www.w3.org/1999/xlink"')
    item = lambda inner: f"<text:list-item>{inner}</text:list-item>"
    xml = (f'<office:document-content {ns}><office:automatic-styles><style:style style:name="T1"><style:text-properties fo:font-weight="bold"/></style:style>'
           '</office:automatic-styles><office:body><office:text><text:h text:outline-level="1">Minutes</text:h>'
           '<text:p>The vote was <text:span text:style-name="T1">unanimous</text:span>, see <text:a xlink:href="https://example.org/vote">the record</text:a>.</text:p>'
           '<text:list>' + item('<text:p>Budget</text:p><text:list>' + item('<text:p>Travel</text:p>') + '</text:list>') + item('<text:p>Hiring</text:p>') + '</text:list>'
           '</office:text></office:body></office:document-content>')
    _zip(p, {"content.xml": xml})


def make_epub_spine(p):
    _zip(p, {
        "META-INF/container.xml": '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        "OEBPS/a_second.xhtml": "<html><body><h1>Chapter Two</h1><p>Then it rained.</p></body></html>",
        "OEBPS/z_first.xhtml": "<html><body><h1>Chapter One</h1><p>It began on a Tuesday.</p></body></html>",
        "OEBPS/content.opf": '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="c1" href="z_first.xhtml"/><item id="c2" href="a_second.xhtml"/></manifest>'
                             '<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>',
    })


def fixtures_rich():
    make_docx_rich(DOCS / "charter.docx"); make_pptx_rich(DOCS / "roadmap.pptx"); make_pdf_rich(DOCS / "report.pdf")
    make_odt_rich(DOCS / "minutes.odt"); make_epub_spine(DOCS / "novel.epub")
    (DOCS / "handbook.html").write_text(
        "<html><head><title>Team handbook</title></head><body><nav>Menu</nav><h2>People</h2>"
        "<table><tr><th>Name</th><th>Role</th></tr><tr><td>Priya</td><td><b>Lead</b></td></tr><tr><td colspan='2'>Both offices</td></tr></table>"
        "<ol><li>First</li><li>Second<ul><li>Inner</li></ul></li><li>Third</li></ol>"
        "<blockquote><p>Quoted line</p></blockquote><p>Some <b> spaced </b> words<br>next line</p><hr><p>End</p></body></html>", "utf-8")
    (DOCS / "budget.rtf").write_bytes(
        rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}{\stylesheet{\s1 heading 1;}{\s2 heading 2;}}"
        rb"\pard\s1 Budget\par\pard\s2 Fixed costs\par\pard Rent is \i due\i0  monthly.\par"
        rb"\pard{\listtext\'b7\tab}Rent\par\pard{\listtext\'b7\tab}Power\par\pard{\listtext 1.\tab}Signed\par"
        rb"\trowd\cellx1000\cellx2000\pard\intbl Item\cell Cost\cell\row\pard\intbl Desk\cell 300\cell\row\pard After the table.\par}")


def rich(name):
    if not (DOCS / "report.pdf").exists():
        fixtures_rich()
    s, r, _ = conv(name)
    t.assertEqual(s, 200, f"{name}: {r}")
    return r["markdown"]


def has(md, *needles, absent=()):
    for n in needles:
        t.assertIn(n, md)
    for n in absent:
        t.assertNotIn(n, md)


# ---- the document's own structure ------------------------------------------------------------
@case("M", "Word: the title and headings keep their levels, found by style name not style id")
def _():
    has(rich("charter.docx"), "# Project Charter", "\n## Scope", "\n### Owners", absent=["**Scope**"])


@case("M", "Word: bold, italic and links survive, and split runs are joined")
def _():
    has(rich("charter.docx"), "The **deadline** is *firm*, see [the site](https://example.org/site) and it is not bold.")


@case("M", "Word: bulleted lists keep their nesting")
def _():
    has(rich("charter.docx"), "- Design\n    - Wireframes\n- Build")


@case("M", "Word: numbered lists are numbered, bulleted lists are not")
def _():
    has(rich("charter.docx"), "1. Plan\n2. Ship", absent=["1. Design", "- Plan"])


def make_docx_unstyled(p):
    """A document with no styles at all, as other tools export them: headings are only larger or bold type."""
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    par = lambda text, size, bold=False: (f'<w:p><w:r><w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/></w:rPr><w:t>{text}</w:t></w:r></w:p>')
    body = "Sales rose in every region this quarter, led by the two new accounts signed in March."
    _zip(p, {"word/document.xml": f'<w:document {w}><w:body>' + par("Launch memo", 44) + par("Background", 28) + par(body, 22) + par(body, 22)
             + par("Next steps", 22, True) + par("# of seats sold is the number to watch.", 22) + par(body, 22) + par("Appendix", 28) + par(body, 22)
             + '</w:body></w:document>'})


@case("M", "Word with no styles: headings are read from larger type, then from bold lines")
def _():
    make_docx_unstyled(DOCS / "memo.docx")
    has(rich("memo.docx"), "# Launch memo", "\n## Background\n", "\n## Appendix\n", "\n### Next steps\n", absent=["**Next steps**"])


@case("M", "running text that begins with a # is kept as text, in the file and in the reader")
def _():
    make_docx_unstyled(DOCS / "memo.docx")
    has(rich("memo.docx"), "\n\\# of seats sold is the number to watch.")
    t.assertIn("not markup", http("GET", "/static/sdk.js", raw=True)[1].decode())


@case("M", "Word: a table keeps merged cells in place and two paragraphs in one cell")
def _():
    has(rich("charter.docx"), "| Owner | Notes |\n|---|---|", "| Sam | First line<br>Second line |", "| Everyone |  |", "Inside a content control.")


@case("M", "PDF: headings come from the type size, the title first")
def _():
    has(rich("report.pdf"), "# Annual Review", "\n## Revenue", "\n## Outlook", absent=["## Page", "# report"])


@case("M", "PDF: a short line set in bold is a heading one level below the sized ones")
def _():
    has(rich("report.pdf"), "\n### Risks\n")


@case("M", "PDF: wrapped lines become one paragraph and a word split by a hyphen is rejoined")
def _():
    has(rich("report.pdf"), "Revenue grew steadily through the year, helped by the new export feature and by two large renewals that closed in the third quarter of the year.")


@case("M", "PDF: a paragraph that runs over a page break is one paragraph")
def _():
    has(rich("report.pdf"), "in the spring, which is not yet signed and may slip.")


@case("M", "PDF: bulleted and numbered lists are lists")
def _():
    has(rich("report.pdf"), "- First point about costs\n- Second point about hiring", "1. Renew the contract\n2. Hire two engineers")


@case("M", "PDF: short lines such as an address keep their line breaks")
def _():
    has(rich("report.pdf"), "\n\nAcme Ltd  \n12 Hill Road  \nPune 411001\n\nHiring went to plan")


@case("M", "PDF: a wider gap between lines starts a new paragraph")
def _():
    has(rich("report.pdf"), "third quarter of the year.\n\nCosts stayed flat.", "we brought in.\n\n- First point", "may slip.\n\nAcme Ltd")


@case("M", "PDF: the running header, footer and page numbers are left out")
def _():
    has(rich("report.pdf"), "Costs stayed flat.", absent=["Acme Quarterly Report", "Page 1 of 3", "Page 2 of 3"])


@case("M", "PowerPoint: the title is the title placeholder, wherever it sits on the slide")
def _():
    has(rich("roadmap.pptx"), "## Slide 1: Roadmap 2027")


@case("M", "PowerPoint: bullet levels, tables kept; the slide number left out")
def _():
    has(rich("roadmap.pptx"), "- Phase one\n    - Design review\n- Phase two", "| Quarter | Goal |\n|---|---|\n| Q1 | Launch |", absent=["- 7", "- Roadmap 2027"])


@case("M", "HTML: tables become real Markdown tables, with formatting inside cells")
def _():
    has(rich("handbook.html"), "| Name | Role |\n|---|---|\n| Priya | **Lead** |\n| Both offices |  |")


@case("M", "HTML: numbered and nested lists, quotes, rules and line breaks")
def _():
    has(rich("handbook.html"), "1. First\n2. Second\n    - Inner\n3. Third", "> Quoted line", "\n---\n", "Some **spaced** words  \nnext line")


@case("M", "HTML: the page title becomes the heading when the page has none at the top level")
def _():
    md = rich("handbook.html")
    t.assertTrue(md.startswith("# Team handbook\n\n## People"), md[:80])
    t.assertNotIn("Menu", md)


@case("M", "RTF: headings from the style sheet, italic, bullets and numbers")
def _():
    has(rich("budget.rtf"), "# Budget", "\n## Fixed costs", "Rent is *due* monthly.", "- Rent\n- Power\n\n1. Signed", absent=["heading 1", "·"])


@case("M", "RTF: table rows become a Markdown table")
def _():
    has(rich("budget.rtf"), "| Item | Cost |\n|---|---|\n| Desk | 300 |", "After the table.")


@case("M", "OpenDocument: bold, links and nested lists")
def _():
    has(rich("minutes.odt"), "# Minutes", "The vote was **unanimous**, see [the record](https://example.org/vote).", "- Budget\n    - Travel\n- Hiring")


@case("M", "EPUB: chapters come in reading order, not file order")
def _():
    md = rich("novel.epub")
    t.assertLess(md.index("Chapter One"), md.index("Chapter Two"))


@case("M", "the reader shows a line break inside a table cell")
def _():
    sdk = http("GET", "/static/sdk.js", raw=True)[1].decode()
    t.assertIn("&lt;br", sdk)
    t.assertIn("'<br>'", sdk)


# ---- which app opens what ----------------------------------------------------------------------
@case("M", "each manifest says what its app opens, and the launcher answers from them")
def _():
    s, m, _ = http("GET", "/api/opens")
    t.assertEqual(s, 200)
    t.assertEqual((m[".pdf"], m[".md"], m[".docx"], m["*"]), (["pdf-reader"], ["markdown-reader"], ["to-markdown"], ["to-markdown"]))
    t.assertIn("twinmind", m[".wav"])


@case("M", "an app's own process gives the same answer")
def _():
    t.assertEqual(http("GET", "/api/opens", base=app("pdf-reader"))[1], http("GET", "/api/opens")[1])


@case("M", "every type an app says it opens is one the converter or TwinMind really reads")
def _():
    supported = set(http("GET", "/api/convert/formats", base=app("to-markdown"))[1])
    audio = set(http("GET", "/api/apps/twinmind/status", base=app("twinmind"))[1]["audio_exts"])
    for ext, ids in http("GET", "/api/opens")[1].items():
        if ext != "*":
            t.assertTrue(ext in supported or ext in audio, f"{ext} ({ids}) is not readable")


# ---- drop to open -------------------------------------------------------------------------------
BIN = {"Content-Type": "application/octet-stream"}


@case("M", "a file dropped on the launcher starts the app that opens it, on that file")
def _():
    cli("close", "pdf-reader")
    data = (DOCS / "invoice.pdf").read_bytes()
    s, r, _ = http("POST", "/api/drop/pdf-reader?name=invoice.pdf&open=0", data, headers=BIN)
    t.assertEqual(s, 200, r)
    t.assertTrue(r["launched"])
    t.assertEqual(Path(r["path"]).read_bytes(), data)
    t.assertEqual(r["name"], "invoice.pdf")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(r["url"]).query)
    t.assertEqual((query["path"], query["name"]), ([r["path"]], ["invoice.pdf"]))
    t.assertIn("pdf-reader", [a["id"] for a in http("GET", "/api/running")[1]])


@case("M", "the launcher still converts nothing: it only hands the file over")
def _():
    t.assertEqual(http("POST", "/api/upload?name=a.txt", b"x", headers=BIN)[0], 409)
    t.assertEqual(http("GET", "/api/convert?path=" + q(DOCS / "note.md"))[0], 409)


@case("M", "a file dropped on the app that opens it is given to that window, with no second launch")
def _():
    base = app("markdown-reader")
    s, r, _ = http("POST", "/api/drop/markdown-reader?name=dropped.md", b"# Dropped\n\nbody", headers=BIN, base=base)
    t.assertEqual((s, r["launched"], r["name"]), (200, False, "dropped.md"))
    t.assertEqual(http("GET", "/api/convert?path=" + q(r["path"]), base=base)[1]["markdown"], "# Dropped\n\nbody")


@case("M", "a file dropped on the wrong app's window goes to the right app")
def _():
    cli("close", "to-markdown")
    s, r, _ = http("POST", "/api/drop/to-markdown?name=plan.docx&open=0", (DOCS / "plan.docx").read_bytes(), headers=BIN, base=app("markdown-reader"))
    t.assertEqual((s, r["launched"], r["app"]), (200, True, "to-markdown"))
    t.assertIn("# Quarterly plan", http("GET", "/api/convert?path=" + q(r["path"]), base=app("to-markdown"))[1]["markdown"])


@case("M", "TwinMind takes a dropped transcript although it has no upload route")
def _():
    base = app("twinmind")
    t.assertEqual(http("POST", "/api/upload?name=a.txt", b"x", headers=BIN, base=base)[0], 403)
    s, r, _ = http("POST", "/api/drop/twinmind?name=talk.txt", TRANSCRIPT.encode(), headers=BIN, base=base)
    t.assertEqual((s, r["launched"]), (200, False))
    t.assertEqual(Path(r["path"]).read_text("utf-8"), TRANSCRIPT)


@case("M", "a drop for an app that does not exist is refused and nothing is kept")
def _():
    before = len(list((HOME / "tmp").iterdir()))
    t.assertEqual(http("POST", "/api/drop/nope?name=a.md", b"x", headers=BIN)[0], 404)
    t.assertEqual(len(list((HOME / "tmp").iterdir())), before)


@case("M", "a dropped file's name cannot place it outside the temporary folder")
def _():
    s, r, _ = http("POST", "/api/drop/markdown-reader?name=..%2F..%5C..%2Fevil.md&open=0", b"x", headers=BIN)
    t.assertEqual(s, 200, r)
    t.assertEqual(Path(r["path"]).parent, HOME / "tmp")
    t.assertEqual(r["name"], "evil.md")


@case("M", "another site cannot drop a file into Mitra")
def _():
    s, _, _ = http("POST", "/api/drop/markdown-reader?name=a.md&open=0", b"x", headers={**BIN, "Origin": "https://evil.example"})
    t.assertEqual(s, 403)


@case("M", "a drop is written to the memory log with its type and where it went")
def _():
    http("POST", "/api/drop/pdf-reader?name=logged.pdf&open=0", (DOCS / "invoice.pdf").read_bytes(), headers=BIN)
    drops = [e for e in events() if e["type"] == "file.drop"]
    t.assertTrue(any(e["data"]["ext"] == ".pdf" and e["data"]["to"] == "pdf-reader" and e["app"] == "shell" for e in drops), drops[-3:])


@case("M", "every window listens for dropped files, through the one shared handler")
def _():
    sdk = http("GET", "/static/sdk.js", raw=True)[1].decode()
    for needle in ("addEventListener('drop'", "addEventListener('dragenter'", "M.openFile", "'/api/drop/'", "dropveil"):
        t.assertIn(needle, sdk)
    t.assertIn(".dropveil", http("GET", "/static/mitra.css", raw=True)[1].decode())


case("M", "Markdown Reader says what it accepts and shows a dropped file under its own name")(_page("markdown-reader", "M.accept = { exts: ['.md', '.markdown', '.txt'], open }", "M.param('name')", "drop one anywhere"))
case("M", "Mitra PDF accepts a dropped PDF, and its page surrounds the viewer so the drop is seen")(_page("pdf-reader", "M.accept = { exts: ['.pdf'], open }", "margin: 0 10px 10px", "drop one anywhere"))
case("M", "Anything to MD accepts any dropped file, anywhere in its window")(_page("to-markdown", "M.accept = { exts: null, open: convertPath }", "Drop a file anywhere in this window"))
case("M", "TwinMind accepts a dropped recording or transcript")(_page("twinmind", "M.accept = { exts, open: pick }", "or drop one here"))


@case("M", "the launcher says files can be dropped on it and refreshes when one starts an app")
def _():
    page = http("GET", "/", raw=True)[1].decode()
    t.assertIn("drop a file here to open it", page)
    t.assertIn("addEventListener('mitra-drop', loadRunning)", page)


# ---- Windows: Open with, Default apps, Start menu -----------------------------------------------
def reg_plan():
    code, out = cli("register", "--print")
    t.assertEqual(code, 0, out)
    return out


@case("M", "register --print shows what would be written and writes nothing")
def _():
    out = reg_plan()
    t.assertIn("Windows Registry Editor Version 5.00", out)
    t.assertFalse((HOME / "handlers").exists(), "a preview must not create the handlers")


@case("M", "each app that opens files gets its own entry, and Ask Mitra, which opens none, gets none")
def _():
    out = reg_plan()
    for progid in ("Mitra.pdf-reader", "Mitra.markdown-reader", "Mitra.to-markdown", "Mitra.twinmind"):
        t.assertIn("\\Software\\Classes\\" + progid + "]", out)
    t.assertNotIn("Mitra.assistant", out)


@case("M", "file types are offered under Open with, taken from the manifests")
def _():
    out = reg_plan()
    for ext, progid in ((".pdf", "Mitra.pdf-reader"), (".md", "Mitra.markdown-reader"), (".txt", "Mitra.markdown-reader"), (".docx", "Mitra.to-markdown"), (".wav", "Mitra.twinmind")):
        t.assertIn(f"\\Software\\Classes\\{ext}\\OpenWithProgids]\n\"{progid}\"=hex(0):", out.replace("\r\n", "\n"))
        t.assertIn(f'"{ext}"="{progid}"', out)
    t.assertNotIn('"*"', out)


@case("M", "the apps are listed for Settings > Default apps, by their own names")
def _():
    out = reg_plan().replace("\r\n", "\n")
    t.assertIn('[HKEY_CURRENT_USER\\Software\\RegisteredApplications]\n"Mitra PDF"="Software\\\\Mitra\\\\Capabilities\\\\pdf-reader"', out)
    t.assertIn('"ApplicationName"="Anything to MD"', out)
    t.assertIn('"FriendlyAppName"="Markdown Reader"', out)


@case("M", "opening a file runs that app on that file, through the windowless handler")
def _():
    out = reg_plan()
    line = next(l for l in out.splitlines() if "Mitra.pdf-reader\\shell\\open\\command" in l)
    cmd = out.splitlines()[out.splitlines().index(line) + 1]
    t.assertIn('Mitra PDF.exe\\"', cmd)
    t.assertIn('open pdf-reader \\"%1\\"', cmd)
    t.assertIn("mitra-marketplace", cmd)


@case("M", "registering never makes itself the default and touches only this user's settings")
def _():
    out = reg_plan()
    t.assertNotIn("UserChoice", out)
    t.assertNotIn("HKEY_LOCAL_MACHINE", out)
    keys = [l for l in out.splitlines() if l.startswith("[")]
    t.assertTrue(keys and all(k.startswith("[HKEY_CURRENT_USER\\Software\\") for k in keys), keys[:3])


@case("M", "every app, and Mitra itself, gets a Start menu entry")
def _():
    out = reg_plan()
    for name in ("Mitra.lnk", "Mitra PDF.lnk", "Markdown Reader.lnk", "Anything to MD.lnk", "TwinMind.lnk", "Ask Mitra.lnk"):
        t.assertIn("Programs\\Mitra\\" + name, out)
    t.assertNotIn("Desktop\\Mitra PDF.lnk", out)      # (this install itself may live on the Desktop)
    t.assertIn("Desktop\\Mitra PDF.lnk", cli("register", "--print", "--desktop")[1])


@case("M", "the windowless handler passes its command on, spaces and all")
def _():
    stub = ROOT / "bin" / f"mitra-open{EXE}"
    if os.name != "nt":
        skip("Windows only")
    t.assertTrue(stub.exists(), "build.ps1 copies mitra-open.exe into bin")
    t.assertLess(stub.stat().st_size, 1 << 20)
    marker = TMP / "handler out" / "ran here.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(stub), sys.executable, "-c", "import sys; open(sys.argv[1], 'w').write(sys.argv[2])", str(marker), "a b"], timeout=30, creationflags=NOWIN)
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    t.assertEqual(marker.read_text(), "a b")


@case("M", "a file opened from Explorer reaches the app: open APP FILE works on a path with spaces")
def _():
    code, out = cli("open", "markdown-reader", str(DOCS / "sp ace" / "résumé notes.md"))
    t.assertEqual(code, 0, out)
    url = next(w for w in out.split() if w.startswith("http"))
    t.assertEqual(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["path"], [str(DOCS / "sp ace" / "résumé notes.md")])


# ============================================================================================
# N. TwinMind on real speech (added in 0.8.0 after a real 4-minute call failed: the audio models
#    were stopped by caps sized on 40-second clips, and the tiny English model could not follow
#    a call that moves between Hindi and English). Placed at the end so earlier numbers hold.
# ============================================================================================
def _words(spec):
    """'0.0-0.4 Hello,|0.5-0.9 hi' -> timed words"""
    out = []
    for part in spec.split("|"):
        span, text = part.strip().split(" ", 1)
        a, z = span.split("-")
        out.append({"start": float(a), "end": float(z), "text": text})
    return out


def _lines(words, turns=None):
    return py(f"import json; from mitra_workers import models; print(json.dumps(models.words_to_lines({words!r}, {turns!r})))")


A, B = "Speaker 1", "Speaker 2"


@case("N", "each sentence goes to the speaker who was talking for most of it")
def _():
    words = _words("0.0-0.3 Hello,|0.4-0.6 hi|0.7-1.1 Dilip.|2.0-2.3 Hi,|2.4-2.8 good|2.9-3.4 evening.|4.0-4.3 Yeah,|4.4-4.7 tell|4.8-5.0 me.")
    turns = [{"start": 0.0, "end": 1.3, "speaker": A}, {"start": 1.9, "end": 3.9, "speaker": B}, {"start": 4.2, "end": 5.2, "speaker": A}]
    d = _lines(words, turns)
    t.assertEqual([(x["speaker"], x["text"]) for x in d], [(A, "Hello, hi Dilip."), (B, "Hi, good evening."), (A, "Yeah, tell me.")])


@case("N", "a short opening word stays with its own sentence, not the previous speaker's line")
def _():
    # "No," is timed inside the other person's turn (word timings are approximate); the sentence decides
    words = _words("0.0-0.5 Is|0.6-0.9 it|1.0-1.5 ready?|1.6-1.8 No,|2.2-2.5 I|2.6-2.9 have|3.0-3.2 to|3.3-3.8 change|3.9-4.2 it.")
    turns = [{"start": 0.0, "end": 2.0, "speaker": A}, {"start": 2.1, "end": 4.4, "speaker": B}]
    d = _lines(words, turns)
    t.assertEqual([(x["speaker"], x["text"]) for x in d], [(A, "Is it ready?"), (B, "No, I have to change it.")])


@case("N", "one speaker's consecutive sentences are one line; a change of speaker starts a new one")
def _():
    words = _words("0.0-0.5 One.|0.6-1.0 Two.|1.1-1.5 Three.|2.0-2.5 Four.")
    turns = [{"start": 0.0, "end": 1.6, "speaker": A}, {"start": 1.9, "end": 2.6, "speaker": B}]
    t.assertEqual([x["text"] for x in _lines(words, turns)], ["One. Two. Three.", "Four."])


@case("N", "a word the model repeats over and over is cut to two")
def _():
    words = _words("|".join(f"{i * 0.3:.1f}-{i * 0.3 + 0.2:.1f} then," for i in range(40)) + "|12.5-13.0 so|13.1-13.5 actually.")
    d = _lines(words)
    t.assertEqual(" ".join(x["text"] for x in d).count("then"), 2)
    t.assertIn("so actually.", d[-1]["text"])


@case("N", "the same line three times running is kept twice at most")
def _():
    words = _words("|".join(f"{i * 6}.0-{i * 6}.5 Thank|{i * 6}.6-{i * 6 + 1}.0 you." for i in range(5)))
    turns = [{"start": i * 6.0, "end": i * 6.0 + 1.2, "speaker": (A, B)[i % 2]} for i in range(5)]
    t.assertLessEqual(len(_lines(words, turns)), 2)


@case("N", "without speaker turns the transcript is plain sentences with no speaker")
def _():
    d = _lines(_words("0.0-0.5 The|0.6-1.0 release|1.1-1.5 stays.|1.8-2.2 Good.|8.0-8.5 Disk|8.6-9.0 is|9.1-9.5 full."))
    t.assertEqual([x["text"] for x in d], ["The release stays. Good.", "Disk is full."], "short sentences share a line; a long pause starts a new one")
    t.assertTrue(all("speaker" not in x for x in d))


@case("N", "noise tags and bracketed asides never reach the transcript")
def _():
    code = ("import json; from mitra_workers import models; "
            "print(json.dumps([models._NOISE.sub(' ', s).strip() for s in ['[BLANK_AUDIO]', '(speaking in foreign language)', '[laughs]', '[inaudible]', 'Fine (I think) then']]))")
    t.assertEqual(py(code), ["", "", "", "", "Fine (I think) then"])


def _link(before, local, o0, o1):
    return py(f"import json; from mitra_workers import models; print(json.dumps(models.link_windows({before!r}, {local!r}, {o0}, {o1})))")


def _t(a, z, s):
    return {"start": a, "end": z, "speaker": s}


@case("N", "a long recording's windows: speakers numbered differently in the next window are matched by the overlap")
def _():
    before = [_t(0, 100, A), _t(100, 200, B), _t(255, 275, B), _t(275, 300, A)]
    local = [_t(255, 275, A), _t(275, 300, B), _t(300, 400, A), _t(400, 500, B)]     # the same two voices, numbers swapped
    d = _link(before, local, 255, 300)
    who = {(x["start"], x["end"]): x["speaker"] for x in d}
    t.assertEqual(who[(300, 400)], B)
    t.assertEqual(who[(400, 500)], A)
    t.assertEqual({x["speaker"] for x in d}, {A, B})


@case("N", "a voice silent in the overlap is matched by elimination when only one is left")
def _():
    before = [_t(0, 120, A), _t(120, 250, B), _t(255, 300, A)]
    local = [_t(255, 300, B), _t(300, 380, B), _t(380, 450, A)]      # local B = earlier A; local A did not speak in the overlap
    d = _link(before, local, 255, 300)
    t.assertEqual({x["speaker"] for x in d}, {A, B})
    t.assertEqual(next(x["speaker"] for x in d if x["start"] == 380), B)


@case("N", "two voices that cannot be told apart at a join get new numbers, never someone else's name")
def _():
    before = [_t(0, 100, A), _t(100, 180, B), _t(180, 250, "Speaker 3"), _t(255, 300, A)]
    local = [_t(255, 300, "Speaker 1"), _t(300, 350, "Speaker 2"), _t(350, 400, "Speaker 3")]
    d = _link(before, local, 255, 300)
    later = {x["speaker"] for x in d if x["start"] >= 300}
    t.assertEqual(later, {"Speaker 4", "Speaker 5"}, "guessing between two unmatched voices would mislabel one of them")


@case("N", "joined windows cover each moment once, cut in the middle of the overlap")
def _():
    before = [_t(0, 200, A), _t(200, 300, B)]
    local = [_t(255, 330, A), _t(330, 500, B)]
    d = _link(before, local, 255, 300)
    spans = sorted((x["start"], x["end"]) for x in d)
    for (a1, z1), (a2, z2) in zip(spans, spans[1:]):
        t.assertLessEqual(z1, a2 + 1e-6, "two turns overlap after the join")
    t.assertIn(277.5, [z for _, z in spans])


@case("N", "a recording of any length is heard in windows of five minutes that overlap")
def _():
    d = py("import json; from mitra_workers import models; print(json.dumps({str(n): models.diar_windows(n) for n in (42, 359, 361, 950, 3600)}))")
    t.assertEqual(d["42"], [[0.0, 42]])
    t.assertEqual(len(d["359"]), 1, "a recording just over five minutes is one window, not a window and a stub")
    for total in ("361", "950", "3600"):
        w = d[total]
        t.assertEqual(w[0][0], 0.0)
        t.assertEqual(w[-1][1], float(total))
        t.assertTrue(all(abs((z - a) - 300.0) < 1e-6 for a, z in w), "every window is a full five minutes: longer needs more memory, "
                     "and a short stub at the end was measured to hear two voices as one")
        t.assertTrue(all(w[i][1] - w[i + 1][0] >= 44.9 for i in range(len(w) - 1)), "windows must overlap so speakers can be matched")
    t.assertEqual(len(d["3600"]), 14)


@case("N", "a long recording is cut for transcription in a pause, not in the middle of a word")
def _():
    code = (
        "import json, wave, math, struct; from pathlib import Path; from mitra_workers import models, paths\n"
        "p = paths.HOME / 'tmp' / 'quiet.wav'; p.parent.mkdir(parents=True, exist_ok=True)\n"
        "rate = 16000\n"
        "def tone(sec): return b''.join(struct.pack('<h', int(9000 * math.sin(i * 0.2))) for i in range(int(sec * rate)))\n"
        "with wave.open(str(p), 'wb') as w:\n"
        "    w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)\n"
        "    w.writeframes(tone(8.6) + b'\\x00\\x00' * int(0.8 * rate) + tone(6))\n"
        "with wave.open(str(p), 'rb') as src:\n"
        "    at = models._quiet_point(src, 10.0)\n"
        "    models._write_piece(src, 0.0, at, p.with_name('piece.wav'))\n"
        "print(json.dumps([at, models.wav_seconds(p.with_name('piece.wav'))]))")
    at, piece = py(code)
    t.assertTrue(8.6 <= at <= 9.4, f"cut at {at} s; the silence is from 8.6 to 9.4")
    t.assertAlmostEqual(piece, at, delta=0.01)


@case("N", "language: English by default whatever is spoken, original language or a set language on request")
def _():
    code = ("import json; from mitra_workers import models, paths\n"
            "multi, en = {'file': 'x/ggml-small-q5_1.bin'}, {'file': 'x/ggml-tiny.en-q5_1.bin'}\n"
            "out = [models.transcribe_plan(multi)[0], models.transcribe_plan(en)[0]]\n"
            "real = paths.config\n"
            "for want in ('original', 'hi'):\n"
            "    paths.config = lambda want=want: {**real(), 'transcribe_language': want}\n"
            "    out.append(models.transcribe_plan(multi)[0])\n"
            "print(json.dumps(out))")
    t.assertEqual(py(code), [["-l", "auto", "-tr"], [], ["-l", "auto"], ["-l", "hi"]])


def _nm_home():
    """The home whose ceiling is 100 MB, so no model fits (made by an earlier case, or here when cases are run by number)."""
    if "nm_home" not in S:
        S["nm_home"] = TMP / "home-nomodel"
        write_config(S["nm_home"], 7487, model_budget_mb=100)
    return S["nm_home"]


def _run_capped(est, burn_mb, home):
    code = ("import json; from mitra_workers import models\n"
            f"p = {{'model': 'cap-test', 'est_mb': {est}}}\n"
            "try:\n"
            f"    models._run_model('twinmind', p, {burner(burn_mb, 3)!r}); print(json.dumps('ran'))\n"
            "except models.MemoryDenied as e:\n    print(json.dumps('denied: ' + str(e)))")
    return py(code, home=home)


@case("N", "a model stopped at its own cap is run once more up to the ceiling, and that is logged")
def _():
    before = len([e for e in events() if e["type"] == "model.cap_raised"])
    t.assertEqual(_run_capped(40, 150, HOME), "ran", "150 MB is over this model's own 54 MB cap but far under the ceiling")
    raised = [e for e in events() if e["type"] == "model.cap_raised"][before:]
    t.assertEqual(len(raised), 1)
    t.assertEqual(raised[0]["data"]["own_cap_mb"], 54)
    runs = [e["data"] for e in events() if e["type"] == "model.run" and e["data"]["name"] == "cap-test"][-2:]
    t.assertEqual([r["end"] for r in runs][0], "over budget")
    t.assertEqual(runs[1]["exit"], 0)


@case("N", "the ceiling itself is never exceeded: over it, the model is stopped and the reason given")
def _():
    out = _run_capped(40, 220, _nm_home())      # that home's ceiling is 100 MB
    t.assertTrue(out.startswith("denied"), out)
    t.assertIn("budget", out)
    t.assertEqual(json.loads(gov("status", home=_nm_home())[1])["leases"], [])


@case("N", "the speech and speaker models' allowances are the ones measured on a real call")
def _():
    cat = json.loads((ROOT / "catalog.json").read_text("utf-8"))
    tr = {c["id"]: c for c in cat["transcription"]["candidates"]}
    t.assertEqual([c["id"] for c in cat["transcription"]["candidates"][:2]], ["whisper-medium-q5_0-cpp", "whisper-small-q5_1-cpp"],
                  "the most accurate model that fits comes first, with the smaller one to step down to")
    t.assertEqual(tr["whisper-medium-q5_0-cpp"]["args"], ["-bs", "1", "-bo", "1"], "medium fits the ceiling only with greedy decoding")
    t.assertGreaterEqual(tr["whisper-medium-q5_0-cpp"]["est_mb"], 950)
    t.assertGreaterEqual(tr["whisper-small-q5_1-cpp"]["est_mb"], 620)
    t.assertGreaterEqual(tr["whisper-tiny-en-cpp"]["est_mb"], 290, "a real 4-minute call needed 283 MB; 180 stopped it")
    t.assertGreaterEqual(cat["diarization"]["candidates"][0]["est_mb"], 190)
    for c in list(tr.values()) + cat["diarization"]["candidates"]:
        t.assertLessEqual(min(1024, int(c["est_mb"] * 1.1) + 10), 1024)
        t.assertLessEqual(c["est_mb"], 1000, c["id"])
        t.assertIn("Measured", c["why"].replace("measured", "Measured"), c["id"])


@case("N", "a title or topic is plain words: no asterisks, quotes or repeated 'Title:'")
def _():
    raw = ['**"Meeting on Wednesday, 18th"**', 'AI Stack and Use Case Transcript Title: "AI Stack and Use Case', "Title: Budget review", "Meeting on Proposal for COE Design", "", "Export fix\nsecond line",
           "Speaker 2: The Elephant in the Room", "Speaker 1's Discussion on Tech and Leadership", "<tech strategy and internal processes>"]
    d = py(f"import json; from mitra_workers import meeting; print(json.dumps([meeting.tidy(x) for x in {raw!r}]))")
    t.assertEqual(d, ["Wednesday, 18th", "AI Stack and Use Case", "Budget review", "Proposal for COE Design", "", "Export fix",
                      "The Elephant in the Room", "Tech and Leadership", "Tech strategy and internal processes"])
    said = py("import json; from mitra_workers import meeting; s = 'we talked about the proposal and the design for the client'; "
              "print(json.dumps([meeting.said_in('Design Proposal for the Client', s), meeting.said_in('Designing for the Future: A Call to Action', s)]))")
    t.assertEqual(said, [True, False], "a title is kept only if most of its words were said")


SPOKEN = ("[00:00:05] Speaker 2: So, the problem will come. I have to recreate the design. I would require it until at least Wednesday, if it's okay.\n"
          "[00:00:20] Speaker 1: Correct.\n[00:00:22] Speaker 2: You tell the client, we will be sharing it by Wednesday.\n[00:00:30] Speaker 1: Thank you.")


@case("N", "a note that says nothing, copies a line, or echoes the format is removed")
def _():
    bullets = ["Correct.", "Thank you.", "I have to recreate the design.", "... (write - None if there are none)",
               "The design will be recreated and shared with the client by Wednesday."]
    d = py(f"import json; from mitra_workers import grounding; print(json.dumps(grounding.guard_bullets({bullets!r}, {SPOKEN!r})))")
    t.assertEqual(d[0], ["The design will be recreated and shared with the client by Wednesday."])
    t.assertEqual(len(d[1]), 3, "the placeholder is dropped silently; the other three are reported")


@case("N", "a note that begins with a transcript label loses the label")
def _():
    d = py(r"import json; from mitra_workers import meeting; print(json.dumps(meeting.parse_notes('Topic: **Design**\nPoints:\n- Speaker 2: The design is recreated by Wednesday.\n- [00:01:02] Speaker 1: The client is told.\nDecisions:\n- None')))")
    t.assertEqual(d["points"], ["The design is recreated by Wednesday.", "The client is told."])


@case("N", "an action item that is only 'Correct', or a pasted transcript line, is removed")
def _():
    acts = [{"owner": "Speaker 1", "task": "Speaker 1: Correct.", "due": None}, {"owner": "Speaker 1", "task": "Thank you", "due": None},
            {"owner": "Speaker 2", "task": "Speaker 2: You tell the client, we will be sharing it by Wednesday.", "due": None},
            {"owner": "Speaker 2", "task": "So, the problem will come.", "due": None},     # a whole sentence as spoken, third person
            {"owner": "Speaker 2", "task": "recreate the design", "due": "Wednesday"}]
    d = py(f"import json; from mitra_workers import grounding; print(json.dumps(grounding.guard_actions({acts!r}, {SPOKEN!r})))")
    t.assertEqual([(a["owner"], a["task"], a["due"]) for a in d[0]], [("Speaker 2", "recreate the design", "Wednesday")])
    t.assertEqual(len(d[1]), 4)


@case("N", "an action list cut off by the length cap keeps the items that were finished")
def _():
    cut = '{"actions": [{"owner": "Sam", "task": "fix the export", "due": "Thursday"}, {"owner": "Dana", "task": "clear the sn'
    d = py(f"import json; from mitra_workers import meeting; print(json.dumps(meeting.parse_actions({cut!r})))")
    t.assertEqual(d, [[{"owner": "Sam", "task": "fix the export", "due": "Thursday"}], True])


def _nm_base():
    return re.search(r"http://[\d.:]+", cli("open", "twinmind", home=_nm_home())[1]).group(0)


@case("N", "commitments are quoted one sentence each; 'the problem will come' is not a commitment")
def _():
    src = DOCS / "spoken-call.txt"
    src.write_text(SPOKEN + "\n[00:00:40] Speaker 1: Sam will send the notes tomorrow. Wednesday will be fine.\n", "utf-8")
    base = _nm_base()
    job = _job(base, {"path": str(src), "title": "Spoken call"})
    t.assertEqual(job["status"], "done", job)
    S["call_memo"] = job["result"]["path"]
    heard = Path(S["call_memo"]).read_text("utf-8").split("### Commitments heard")[1].split("## ")[0]
    lines = [l[2:] for l in heard.splitlines() if l.startswith("- ")]
    t.assertIn("[00:00:05] Speaker 2: I have to recreate the design.", lines)
    t.assertIn("[00:00:05] Speaker 2: I would require it until at least Wednesday, if it's okay.", lines)
    t.assertIn("[00:00:22] Speaker 2: You tell the client, we will be sharing it by Wednesday.", lines)
    t.assertIn("[00:00:40] Speaker 1: Sam will send the notes tomorrow.", lines)
    t.assertFalse(any("problem will come" in l or "Wednesday will be fine" in l for l in lines), lines)


@case("N", "who is who: the memo's speakers are listed with a line to recognise each by")
def _():
    s, d, _ = http("GET", "/api/apps/twinmind/speakers?path=" + q(S["call_memo"]), base=_nm_base())
    t.assertEqual(s, 200, d)
    t.assertEqual([(x["speaker"], x["lines"]) for x in d], [("Speaker 2", 2), ("Speaker 1", 3)])
    t.assertIn("recreate the design", d[0]["sample"])


@case("N", "naming a speaker rewrites the memo everywhere, and fills in who attended")
def _():
    base = _nm_base()
    s, d, _ = http("POST", "/api/apps/twinmind/speakers", {"path": S["call_memo"], "names": {"Speaker 1": "Anirudh", "Speaker 2": "Dilip", "Speaker 9": "Nobody"}}, base=base)
    t.assertEqual(s, 200, d)
    memo = Path(S["call_memo"]).read_text("utf-8")
    t.assertNotRegex(memo, r"Speaker [12]\b")
    t.assertIn("[00:00:22] Dilip: You tell the client", memo)
    t.assertIn("- [00:00:05] Dilip: I have to recreate the design.", memo)
    t.assertIn("**Attendees:** Anirudh, Dilip", memo)
    t.assertNotIn("Nobody", memo)
    t.assertEqual(http("GET", "/api/apps/twinmind/speakers?path=" + q(S["call_memo"]), base=base)[1][0]["speaker"], "Dilip")
    t.assertTrue(any(e["type"] == "action.speakers_named" for e in events(_nm_home())))


@case("N", "naming speakers is refused for a file that is not a memo in the TwinMind folder")
def _():
    base = _nm_base()
    outside = DOCS / "standup.txt"
    before = outside.read_text("utf-8")
    for path in (str(outside), str(Path(S["call_memo"]).parent / ".." / ".." / "docs" / "standup.txt"), str(ROOT / "README.md")):
        s, d, _ = http("POST", "/api/apps/twinmind/speakers", {"path": path, "names": {"Priya": "X"}}, base=base)
        t.assertGreaterEqual(s, 400, d)
    t.assertEqual(outside.read_text("utf-8"), before)
    t.assertGreaterEqual(http("GET", "/api/apps/twinmind/speakers?path=" + q(ROOT / "README.md"), base=base)[0], 400)


@case("N", "the TwinMind page asks who is who once a memo is written")
def _():
    page = (ROOT / "apps" / "twinmind" / "ui" / "index.html").read_text("utf-8")
    for part in ("askNames(job.result.path)", "api('speakers'", "Who is who?", "Use these names"):
        t.assertIn(part, page)


def _two_voice_wav(wav, rounds):
    """Two installed voices taking turns for `rounds` exchanges; returns how many voices there were."""
    a = "Round {n}. Please fix the export before the release. The export fails on large invoices and the client is waiting."
    b = "Understood, round {n}. The staging database is nearly full, so I will clear old snapshots this afternoon and report back."
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }); "
          f"$s.SetOutputToWaveFile('{wav}'); "
          f"for ($n = 1; $n -le {rounds}; $n++) {{ $s.SelectVoice($v[0]); $s.Speak('{a}'.Replace('{{n}}', $n)); "
          f"if ($v.Count -gt 1) {{ $s.SelectVoice($v[1]) }}; $s.Speak('{b}'.Replace('{{n}}', $n)) }}; "
          "$s.Dispose(); Write-Output $v.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, text=True, creationflags=NOWIN).stdout
    return int(out.strip().splitlines()[-1])


@case("N", "a recording longer than one window is heard to the end, and a join never changes who a voice is")
def _():
    _ready("transcription")
    if os.name != "nt":
        skip("needs Windows speech synthesis to make the recording")
    diar = next(c for c in http("GET", "/api/models")[1]["capabilities"] if c["capability"] == "diarization")
    if not diar["ready"]:
        skip("diarization not available on this device")
    wav = DOCS / "long-spoken.wav"
    voices = _two_voice_wav(wav, 30)
    secs = py(f"import json; from mitra_workers import models; from pathlib import Path; print(json.dumps(models.wav_seconds(Path({str(wav)!r}))))")
    t.assertGreater(secs, 362, "the recording must be long enough to need two windows")
    S["long_secs"] = secs
    mark = len(events())
    job = _job(app("twinmind"), {"path": str(wav), "title": "Long spoken test"}, wait=900)
    t.assertEqual(job["status"], "done", job)
    S["long_events"] = events()[mark:]
    memo = Path(job["result"]["path"]).read_text("utf-8")
    S["long_memo"] = memo
    body = [l for l in memo.split("Appendix: Transcript")[1].splitlines() if l.startswith("[")]
    t.assertRegex(body[-1], r"^\[00:0[6-9]:", "the transcript must reach the end of the recording")
    if voices < 2:
        skip("only one voice is installed, so there is one speaker to find")
    label = lambda l: (re.match(r"\[[\d:]+\] ([^:]+):", l) or [None, None])[1]
    labels = [label(l) for l in body]
    t.assertLessEqual(len(set(labels) - {None}), 2, f"two voices must never become three at a join: {sorted(set(labels) - {None})}")
    # The speaker model hears these two synthesized voices as one person for the first five minutes
    # (measured in both of its modes, logs/scripts/debug_long_speakers.py), so the two are only told
    # apart from the second window on. From where they are, each voice must keep its label to the end,
    # across the join into the last window.
    first_two = next((i for i, x in enumerate(labels) if x and x != labels[0]), None)
    if first_two is None:
        skip("the speaker model heard the two synthesized voices as one throughout")
    later = body[max(0, first_two - 1):]
    asks = [label(l) for l in later if "export" in l.lower() and "snapshots" not in l.lower()]
    answers = [label(l) for l in later if "snapshots" in l.lower() and "export" not in l.lower()]
    t.assertGreater(len(asks) + len(answers), 10, "too little of the recording had the two voices apart to judge")
    top = lambda xs: max(set(xs), key=xs.count)
    t.assertGreaterEqual(asks.count(top(asks)) / len(asks), 0.9, f"the first voice's lines are split between speakers: {asks}")
    t.assertGreaterEqual(answers.count(top(answers)) / len(answers), 0.9, f"the second voice's lines are split between speakers: {answers}")
    t.assertNotEqual(top(asks), top(answers))


@case("N", "on that long recording every model stayed under its cap and none was run twice for memory")
def _():
    if "long_events" not in S:
        skip("the long recording test did not run")
    runs = [e["data"] for e in S["long_events"] if e["type"] == "model.run"]
    t.assertGreaterEqual(len([r for r in runs if "diarization" in r["name"]]), 2, "one run per window")
    t.assertGreaterEqual(len([r for r in runs if r["name"].startswith("whisper")]), 2, "one run per piece")
    for r in runs:
        t.assertLessEqual(r["peak_mb"], r["budget_mb"], f"{r['name']} peaked at {r['peak_mb']} MB")
        t.assertLessEqual(r["budget_mb"], 1024)
    t.assertEqual([e for e in S["long_events"] if e["type"] in ("model.cap_raised", "governor.evict")], [])
    longest = max(r["peak_mb"] for r in runs if "diarization" in r["name"])
    t.assertLessEqual(longest, 215, "the speaker model's memory must not grow with the length of the recording")


@case("N", "the long recording's models ran one at a time")
def _():
    if "long_events" not in S:
        skip("the long recording test did not run")
    runs = [e for e in S["long_events"] if e["type"] == "model.run"]
    spans = sorted((datetime.fromisoformat(r["ts"]) - timedelta(milliseconds=r["data"].get("ms", 0)), datetime.fromisoformat(r["ts"])) for r in runs)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        t.assertLessEqual(e1, s2 + timedelta(seconds=1), "two model runs overlapped")


# ============================================================================================
# O. taking turns: the line for the model, saved pieces and resume, the line of recordings (0.9.0)
# ============================================================================================
def _hold(name, seconds, *extra):
    return subprocess.Popen([GOV, "run", "--app", "holder", "--name", name, "--est-mb", "10", *extra, "--", *burner(5, seconds)], env=env(), creationflags=NOWIN)


def _status(home=HOME):
    return json.loads(gov("status", home=home)[1])


def _until(test, within=10.0, every=0.25):
    end = time.time() + within
    while time.time() < end:
        v = test()
        if v:
            return v
        time.sleep(every)
    return test()


@case("O", "nobody is turned away for waiting: with no limit given a second model waits its turn and runs")
def _():
    first = _hold("line-first", 4)
    time.sleep(1.2)
    t0 = time.time()
    code, _, err = gov("run", "--app", "app-two", "--name", "line-second", "--est-mb", "10", "--", *burner(5, 1))
    first.wait(timeout=20)
    t.assertEqual(code, 0, err)
    t.assertGreater(time.time() - t0, 2.0, "it must have waited for the first")
    load = [e for e in events() if e["type"] == "model.load" and e["data"]["name"] == "line-second"][-1]
    t.assertGreaterEqual(load["data"]["waited_s"], 1)
    t.assertEqual(_status()["line"], [])


@case("O", "a question goes ahead of a long job that was already waiting")
def _():
    first = _hold("order-first", 5)
    time.sleep(1.2)
    bg = subprocess.Popen([GOV, "run", "--app", "twinmind", "--name", "order-job", "--est-mb", "10", "--what", "piece 2 of 9", "--", *burner(5, 1)], env=env(), creationflags=NOWIN)
    time.sleep(0.8)
    ask = subprocess.Popen([GOV, "run", "--app", "assistant", "--name", "order-question", "--est-mb", "10", "--priority", "interactive", "--what", "a question",
                            "--", *burner(5, 1)], env=env(), creationflags=NOWIN)
    line = _until(lambda: (lambda l: l if len(l) == 2 else None)(_status()["line"]), 5)
    t.assertEqual([x["name"] for x in line], ["order-question", "order-job"], "the question is first in line though it came second")
    t.assertEqual(line[0]["priority"], "interactive")
    t.assertEqual(line[1]["what"], "piece 2 of 9")
    t.assertEqual(line[1]["app"], "twinmind")
    t.assertGreaterEqual(line[1]["waited_s"], 0)
    for p in (first, ask, bg):
        t.assertEqual(p.wait(timeout=30), 0)
    loads = [e["data"]["name"] for e in events() if e["type"] == "model.load" and e["data"]["name"].startswith("order-")][-3:]
    t.assertEqual(loads, ["order-first", "order-question", "order-job"])
    t.assertEqual(_status()["line"], [])


@case("O", "two long jobs get the model in the order they asked")
def _():
    first = _hold("fifo-first", 3)
    time.sleep(1.0)
    a = subprocess.Popen([GOV, "run", "--app", "x", "--name", "fifo-a", "--est-mb", "10", "--", *burner(5, 1)], env=env(), creationflags=NOWIN)
    time.sleep(0.6)
    b = subprocess.Popen([GOV, "run", "--app", "y", "--name", "fifo-b", "--est-mb", "10", "--", *burner(5, 1)], env=env(), creationflags=NOWIN)
    for p in (first, a, b):
        t.assertEqual(p.wait(timeout=30), 0)
    loads = [e["data"]["name"] for e in events() if e["type"] == "model.load" and e["data"]["name"].startswith("fifo-")][-3:]
    t.assertEqual(loads, ["fifo-first", "fifo-a", "fifo-b"])


@case("O", "the running model says what it is doing and for whom")
def _():
    p = _hold("doing", 3, "--what", "what was said, piece 7 of 24")
    lease = _until(lambda: (_status()["leases"] or [None])[0], 5)
    t.assertEqual(lease["what"], "what was said, piece 7 of 24")
    t.assertEqual(lease["apps"], ["holder"])
    p.wait(timeout=20)


def _parent_of(gov_args):
    """A Python process that starts a governor and waits for it: the governor's caller."""
    code = f"import subprocess, sys; subprocess.run({[GOV, *gov_args]!r}, creationflags={NOWIN})"
    return subprocess.Popen([sys.executable, "-c", code], env=env(), creationflags=NOWIN)


@case("O", "a waiter whose caller has gone leaves the line and never runs")
def _():
    first = _hold("gone-first", 7)
    time.sleep(1.2)
    parent = _parent_of(["run", "--app", "assistant", "--name", "gone-waiter", "--est-mb", "10", "--priority", "interactive", "--", *burner(5, 1)])
    t.assertTrue(_until(lambda: len(_status()["line"]) == 1, 5), "the waiter should be in line")
    kill_pid(parent.pid)
    t.assertTrue(_until(lambda: _status()["line"] == [], 6), "the line should empty once the caller is gone")
    first.wait(timeout=20)
    time.sleep(0.5)
    t.assertEqual([e for e in events() if e["type"] == "model.load" and e["data"]["name"] == "gone-waiter"], [])
    t.assertTrue([e for e in events() if e["type"] == "model.wait_left" and e["data"]["name"] == "gone-waiter"])


@case("O", "a waiter that is released while waiting leaves the line")
def _():
    first = _hold("rel-first", 5)
    time.sleep(1.2)
    w = subprocess.Popen([GOV, "run", "--app", "assistant", "--name", "rel-waiter", "--est-mb", "10", "--hold-stdin", "--", *burner(5, 30)],
                         stdin=subprocess.PIPE, env=env(), creationflags=NOWIN)
    t.assertTrue(_until(lambda: len(_status()["line"]) == 1, 5))
    w.stdin.close()
    t.assertEqual(w.wait(timeout=6), 0)
    t.assertEqual(_status()["line"], [])
    first.wait(timeout=20)


@case("O", "a running model whose caller has gone is stopped")
def _():
    parent = _parent_of(["run", "--app", "twinmind", "--name", "orphan", "--est-mb", "10", "--", *burner(5, 60)])
    t.assertTrue(_until(lambda: _status()["leases"], 6), "the model should be running")
    kill_pid(parent.pid)
    t.assertTrue(_until(lambda: _status()["leases"] == [], 8), "the model should stop once its caller is gone")
    run = _until(lambda: [e for e in events() if e["type"] == "model.run" and e["data"]["name"] == "orphan"], 4)[-1]
    t.assertEqual(run["data"]["end"], "its caller is gone")


@case("O", "a ticket left behind by a crash does not block the line")
def _():
    d = HOME / "run" / "line"
    d.mkdir(parents=True, exist_ok=True)
    (d / "000000000000001-999999.json").write_text(json.dumps({"pid": 999999, "app": "ghost", "name": "ghost", "priority": "interactive"}), "utf-8")
    code, _, err = gov("run", "--app", "x", "--name", "after-ghost", "--est-mb", "10", "--", *burner(5, 1))
    t.assertEqual(code, 0, err)
    t.assertEqual(list(d.glob("*.json")), [])


# ---- saved pieces --------------------------------------------------------------------------
_FAKE = r'''
import json, sys, wave, time
from pathlib import Path
from mitra_workers import models, work
calls = []
def silent(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        for _ in range(int(seconds // 10)):
            w.writeframes(bytes(16000 * 2 * 10))
def fake_run(app, p, cmd, what=""):
    calls.append((p["model"], what))
    if HOOK:
        HOOK(len(calls), p)
    if "-of" in cmd:
        Path(cmd[cmd.index("-of") + 1] + ".json").write_text(json.dumps({"result": {"language": "en"},
            "transcription": [{"text": " piece", "offsets": {"from": 0, "to": 400}}, {"text": " %d." % len(calls), "offsets": {"from": 500, "to": 900}}]}), "utf-8")
    if "--turns-out" in cmd:
        Path(cmd[cmd.index("--turns-out") + 1]).write_text(json.dumps([{"start": 1.0, "end": 200.0, "speaker": "a"}, {"start": 201.0, "end": 290.0, "speaker": "b"}]), "utf-8")
HOOK = None
models._run_model = fake_run
CANDS = [{"ready": True, "model": "big", "file": "big.bin", "est_mb": 900, "runtime_path": "x", "args": []},
         {"ready": True, "model": "small", "file": "small.bin", "est_mb": 500, "runtime_path": "x", "args": []}]
def fake_pick(capability, exclude=()):
    if capability == "diarization":
        return {"ready": True, "model": "diar", "file": "d.gguf", "est_mb": 200, "runtime_path": "x"}
    return next((c for c in CANDS if c["model"] not in exclude), {"ready": False, "hint": "none left"})
models.pick = fake_pick
'''


def _fake(body, home=HOME):
    wav = DOCS / "silent-16min.wav"
    return py(_FAKE + f"wav = Path({str(wav)!r})\nif not wav.exists(): silent(wav, 960)\n" + body, home=home)


@case("O", "every finished piece of speech is saved, and a second run does none of them again")
def _():
    d = _fake("w = work.Work(wav, 'accurate', 'english'); work.recycle(w.dir); w = work.Work(wav, 'accurate', 'english')\n"
              "a = models.transcribe('twinmind', wav, wav_ready=True, work=w); n1 = len(calls)\n"
              "saved = sorted(f.name for f in w.dir.glob('words-*.json'))\n"
              "w2 = work.Work(wav, 'accurate', 'english'); b = models.transcribe('twinmind', wav, wav_ready=True, work=w2); n2 = len(calls) - n1\n"
              "(w2.dir / 'words-0001.json').unlink(); c = models.transcribe('twinmind', wav, wav_ready=True, work=w2); n3 = len(calls) - n1 - n2\n"
              "print(json.dumps({'n1': n1, 'n2': n2, 'n3': n3, 'saved': saved, 'same': a == b, 'resumed': w2.resumed, 'progress': w2.meta['progress'],\n"
              "                  'what': calls[0][1], 'texts': [x['text'] for x in a]}))")
    t.assertEqual(d["n1"], 3, "16 minutes is three pieces")
    t.assertEqual(d["saved"], ["words-0000.json", "words-0001.json", "words-0002.json"])
    t.assertEqual(d["n2"], 0, "nothing is heard twice")
    t.assertEqual(d["n3"], 1, "only the missing piece is redone")
    t.assertTrue(d["same"])
    t.assertTrue(d["resumed"])
    t.assertEqual(d["progress"]["transcribe"], [3, 3])
    t.assertEqual(d["what"], "what was said, piece 1 of 3")


@case("O", "every finished speaker window is saved, and a second run hears none of them again")
def _():
    d = _fake("w = work.Work(wav, 'd'); work.recycle(w.dir); w = work.Work(wav, 'd')\n"
              "a = models.diarize('twinmind', wav, work=w); n1 = len(calls)\n"
              "b = models.diarize('twinmind', wav, work=work.Work(wav, 'd')); n2 = len(calls) - n1\n"
              "print(json.dumps({'n1': n1, 'n2': n2, 'windows': len(models.diar_windows(960)), 'same': a == b, 'speakers': sorted({t['speaker'] for t in a})}))")
    t.assertEqual(d["n1"], d["windows"])
    t.assertGreaterEqual(d["windows"], 4)
    t.assertEqual(d["n2"], 0)
    t.assertTrue(d["same"])
    t.assertEqual(d["speakers"], ["Speaker 1", "Speaker 2"])


@case("O", "pause stops after the piece in hand; resume does only what was left")
def _():
    d = _fake("w = work.Work(wav, 'p'); work.recycle(w.dir); w = work.Work(wav, 'p')\n"
              "def hook(n, p):\n    if n == 1: (w.dir / 'pause').write_text('')\n"
              "HOOK = hook\n"
              "try:\n    models.transcribe('twinmind', wav, wav_ready=True, work=w); paused = False\n"
              "except work.Paused:\n    paused = True\n"
              "n1 = len(calls); HOOK = None; (w.dir / 'pause').unlink()\n"
              "out = models.transcribe('twinmind', wav, wav_ready=True, work=work.Work(wav, 'p'))\n"
              "print(json.dumps({'paused': paused, 'n1': n1, 'n2': len(calls) - n1, 'lines': len(out)}))")
    t.assertEqual(d, {"paused": True, "n1": 1, "n2": 2, "lines": d["lines"]})
    t.assertGreaterEqual(d["lines"], 1)


@case("O", "a speech model refused memory is replaced from that piece on, not from the start")
def _():
    d = _fake("w = work.Work(wav, 'm'); work.recycle(w.dir); w = work.Work(wav, 'm')\n"
              "def hook(n, p):\n    if n == 2 and p['model'] == 'big': raise models.MemoryDenied('no room')\n"
              "HOOK = hook; info = {}\n"
              "models.transcribe('twinmind', wav, wav_ready=True, work=w, info=info)\n"
              "print(json.dumps({'calls': [c[0] for c in calls], 'pieces': [w.load('words-%04d' % i)['model'] for i in range(3)], 'info': info}))")
    t.assertEqual(d["calls"], ["big", "big", "small", "small"])
    t.assertEqual(d["pieces"], ["big", "small", "small"])
    t.assertEqual(d["info"]["stepped_down_from"], "big")
    t.assertEqual(d["info"]["model"], "big then small")
    t.assertTrue([e for e in events() if e["type"] == "model.fallback" and e["data"].get("piece") == 2])


@case("O", "fast speed uses the next speech model down; accurate uses the first")
def _():
    d = _fake("print(json.dumps([models.transcription_choice('accurate')['model'], models.transcription_choice('fast')['model'],\n"
              "                  models.transcription_choice('fast', ('big',))['model']]))")
    t.assertEqual(d, ["big", "small", "small"])


@case("O", "saved pieces belong to one recording at one speed: a changed file or another speed starts afresh")
def _():
    d = py("import json, os, time; from pathlib import Path; from mitra_workers import work\n"
           f"f = Path({str(DOCS / 'fp.txt')!r}); f.write_text('one', 'utf-8')\n"
           "a = work.fingerprint(f, 'accurate'); b = work.fingerprint(f, 'fast'); a2 = work.fingerprint(f, 'accurate')\n"
           "f.write_text('one two', 'utf-8'); c = work.fingerprint(f, 'accurate')\n"
           "print(json.dumps([a == a2, a != b, a != c]))")
    t.assertEqual(d, [True, True, True])


@case("O", "the length of a recording is read without converting it")
def _():
    wav = DOCS / "silent-16min.wav"
    d = py(f"import json; from pathlib import Path; from mitra_workers import models; print(json.dumps(models.audio_seconds(Path({str(wav)!r}))))")
    t.assertAlmostEqual(d, 960, delta=1)


# ---- the line of recordings, through the app ---------------------------------------------------
def _tm(method, name, body=None, base=None):
    s, d, _ = http(method, "/api/apps/twinmind/" + name, body, base=base or _nm_base())
    t.assertEqual(s, 200, d)
    return d


@case("O", "before anything runs the page is told how long a recording will take at each speed")
def _():
    wav = DOCS / "silent-16min.wav"
    d = _tm("GET", "estimate?path=" + q(wav))
    t.assertTrue(d["audio"])
    t.assertAlmostEqual(d["seconds"], 960, delta=1)
    for speed in ("accurate", "fast"):
        t.assertEqual(d[speed]["pieces"], 3)
        t.assertGreaterEqual(d[speed]["windows"], 4)
        t.assertGreater(d[speed]["seconds"], 60)
    t.assertFalse(_tm("GET", "estimate?path=" + q(DOCS / "standup.txt"))["audio"])


@case("O", "while a recording is being worked on, another one joins the line instead of starting")
def _():
    base, home = _nm_base(), _nm_home()
    (home / "run").mkdir(parents=True, exist_ok=True)
    (home / "run" / "twinmind-line.json").unlink(missing_ok=True)
    (home / "run" / "twinmind-runner.json").write_text(json.dumps({"pid": os.getpid(), "job": "busy"}), "utf-8")   # this test process stands in for a job at work
    for n, name in enumerate(("q1.txt", "q2.txt", "q3.txt")):
        (DOCS / name).write_text(TRANSCRIPT, "utf-8")
        job = _job(base, {"path": str(DOCS / name), "title": f"Queued {n + 1}", "speed": "fast" if n == 1 else "accurate"})
        t.assertEqual(job["status"], "done", job)
        t.assertEqual(job["result"], {"queued": True, "position": n + 1})
    st = _tm("GET", "state", base=base)
    t.assertEqual(st["running"]["job"], "busy")
    t.assertEqual([i["title"] for i in st["line"]], ["Queued 1", "Queued 2", "Queued 3"])
    t.assertEqual([i["speed"] for i in st["line"]], ["accurate", "fast", "accurate"])
    t.assertEqual(len([e for e in events(home) if e["type"] == "job.queued"]), 3)


@case("O", "the line can be reordered and a recording removed from it")
def _():
    base = _nm_base()
    _tm("POST", "line", {"order": [1, 0]}, base=base)      # second first, third removed
    t.assertEqual([i["title"] for i in _tm("GET", "state", base=base)["line"]], ["Queued 2", "Queued 1"])


@case("O", "when a recording is done the next in line is written by itself, each as its own job")
def _():
    base, home = _nm_base(), _nm_home()
    (home / "run" / "twinmind-runner.json").unlink()          # the stand-in job is over
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", {"path": str(DOCS / "standup.txt"), "title": "Head of line"}, base=base)
    titles, jid = [], r["id"]
    for _ in range(3):
        job = _until(lambda: (lambda j: j if j["status"] in ("done", "failed") else None)(http("GET", "/api/jobs/" + jid, base=base)[1]), 60, 0.5)
        t.assertEqual(job["status"], "done", job)
        titles.append(job["result"]["title"])
        jid = job.get("next")
        if not jid:
            break
    t.assertEqual(titles, ["Head of line", "Queued 2", "Queued 1"])
    st = _tm("GET", "state", base=base)
    t.assertEqual((st["running"], st["line"]), (None, []))
    for title in titles:
        t.assertTrue(list((TMP / "dropbox").rglob(f"* {title}.md")), title)


@case("O", "a job that stopped is listed with what was kept, and discarding it removes the pieces")
def _():
    base, home = _nm_base(), _nm_home()
    src = DOCS / "standup.txt"
    key = py(f"import json; from pathlib import Path; from mitra_workers import work\n"
             f"w = work.Work(Path({str(src)!r}), 'accurate', 'english'); w.save('words-0000', {{'words': []}})\n"
             "w.note(state='running', stage='transcribe', item={'path': w.meta['source'], 'name': 'standup.txt', 'speed': 'accurate', 'title': '', 'attendees': ''}, pid=999999)\n"
             "w.meta['progress'] = {'diarize': [29, 29], 'transcribe': [16, 24]}; w.save('job', w.meta); print(json.dumps(w.key))", home=home)
    u = [x for x in _tm("GET", "state", base=base)["unfinished"] if x["key"] == key]
    t.assertEqual(len(u), 1)
    t.assertEqual(u[0]["progress"]["transcribe"], [16, 24])
    t.assertEqual(u[0]["stage"], "transcribe")
    t.assertEqual(u[0]["name"], "standup.txt")
    t.assertFalse(u[0]["source_missing"])
    d = _tm("POST", "discard", {"key": key}, base=base)
    t.assertTrue(d["discarded"])
    t.assertFalse((home / "run" / "work" / key).exists())
    t.assertEqual([x for x in _tm("GET", "state", base=base)["unfinished"] if x["key"] == key], [])
    t.assertFalse(_tm("POST", "discard", {"key": "../../config"}, base=base)["discarded"], "only a job's own folder can be discarded")


@case("O", "a finished job leaves no saved pieces behind")
def _():
    base, home = _nm_base(), _nm_home()
    job = _job(base, {"path": str(DOCS / "standup.txt"), "title": "Leaves nothing"})
    t.assertEqual(job["status"], "done", job)
    t.assertFalse(job["result"]["resumed"])
    key = py(f"import json; from pathlib import Path; from mitra_workers import work; print(json.dumps(work.fingerprint(Path({str(DOCS / 'standup.txt')!r}), 'accurate', 'english')))", home=home)
    t.assertFalse((home / "run" / "work" / key).exists(), "the pieces of a finished job must be gone (a failed job's are kept)")


@case("O", "pause and stop are harmless when nothing is running")
def _():
    base = _nm_base()
    t.assertFalse(_tm("POST", "pause", {}, base=base)["paused"])
    t.assertFalse(_tm("POST", "stop", {}, base=base)["stopped"])


@case("O", "the memory report counts waits, queued recordings and resumed jobs")
def _():
    rep = http("GET", "/api/memory/report?days=1")[1]
    t.assertGreaterEqual(rep["report"]["turns"]["waited_for_model"], 3)
    t.assertIn("## Taking turns", rep["markdown"])


@case("O", "the screens show the line: TwinMind, Ask Mitra and the launcher")
def _():
    tm = (ROOT / "apps" / "twinmind" / "ui" / "index.html").read_text("utf-8")
    for part in ("Add to the line", "api('pause'", "api('stop'", "api('discard'", "Resume", "Start over", "Next up", 'value="fast"', "left`", "did not finish"):
        t.assertIn(part, tm)
    ask = (ROOT / "apps" / "assistant" / "ui" / "index.html").read_text("utf-8")
    for part in ("Waiting for a turn", "Cancel question", "ctl.abort()"):
        t.assertIn(part, ask)
    home_page = (ROOT / "web" / "index.html").read_text("utf-8")
    for part in ("Waiting for the model", 'id="busy"', "goes next"):
        t.assertIn(part, home_page)


# ---- with real models ------------------------------------------------------------------------
@case("O", "a question asked while another model is held waits for its turn and is then answered")
def _():
    _ready("assistant")
    first = _hold("ask-blocker", 8)
    time.sleep(1.5)
    t0 = time.time()
    s, d, _ = http("POST", "/api/ask", {"app_id": "assistant", "prompt": "Reply with the single word: ready."}, base=app("assistant"), timeout=240)
    first.wait(timeout=20)
    t.assertEqual(s, 200, d)
    t.assertGreater(time.time() - t0, 5, "it must have waited for the model that was held")
    t.assertGreater(d["waited_ms"], 3000)
    t.assertTrue(d["text"])
    waits = [e for e in events() if e["type"] == "model.wait" and e["app"] == "assistant"]
    t.assertEqual(waits[-1]["data"]["priority"], "interactive")


@case("O", "a question cancelled while waiting leaves the line and loads nothing")
def _():
    _ready("assistant")
    base = app("assistant")
    first = _hold("cancel-blocker", 9)
    time.sleep(1.5)
    before = len([e for e in events() if e["type"] == "model.load" and e["app"] == "assistant"])
    try:
        http("POST", "/api/ask", {"app_id": "assistant", "prompt": "Never answered."}, base=base, timeout=3)
        t.fail("the question should still have been waiting")
    except (TimeoutError, urllib.error.URLError, OSError):
        pass                                                   # the page gave up, as Cancel question does
    t.assertTrue(_until(lambda: _status()["line"] == [], 8), "the cancelled question should leave the line")
    first.wait(timeout=20)
    time.sleep(1)
    t.assertEqual(len([e for e in events() if e["type"] == "model.load" and e["app"] == "assistant"]), before)
    t.assertEqual(_status()["leases"], [])


LONG_TALK = "\n".join(f"[00:{m:02d}:{s:02d}] {who}: {line}" for (m, s, who, line) in [
    (i // 2, 30 * (i % 2), ("Priya", "Sam", "Dana")[i % 3],
     (f"On item {i + 1}, the export job fails when an invoice has more than {200 + i} lines, so the client cannot close the month. "
      f"Sam will send the fix for item {i + 1} by Thursday and Dana will check it on the staging database before it ships. "
      "We agreed the release waits until that check has passed, and Priya will tell the client about the new date today."))
    for i in range(30)])


@case("O", "the notes model steps aside between sections for a question, and the memo is still complete")
def _():
    _ready("meeting-notes")
    _ready("assistant")
    src = DOCS / "long-talk.txt"
    src.write_text(LONG_TALK, "utf-8")
    tm, am = app("twinmind"), app("assistant")
    mark = len(events())
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", {"path": str(src), "title": "Stepping aside"}, base=tm)
    t.assertEqual(s, 200, r)
    job = _until(lambda: (lambda j: j if (j.get("progress") or {}).get("understand", [0])[0] >= 1 or j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 240, 1)
    t.assertEqual(job["status"], "running", job)
    total = job["progress"]["understand"][1]
    t.assertGreaterEqual(total, 3, "the transcript must be long enough for several sections")
    s, d, _ = http("POST", "/api/ask", {"app_id": "assistant", "prompt": "Reply with the single word: ready."}, base=am, timeout=300)
    t.assertEqual(s, 200, d)
    mid = http("GET", "/api/jobs/" + r["id"], base=tm)[1]
    t.assertEqual(mid["status"], "running", "the question was answered while the notes were still being written")
    job = _until(lambda: (lambda j: j if j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 900, 2)
    t.assertEqual(job["status"], "done", job)
    t.assertGreaterEqual(job["result"]["yields"], 1)
    new = events()[mark:]
    t.assertTrue([e for e in new if e["type"] == "model.yield"])
    t.assertEqual(job["progress"]["understand"], [total, total])
    memo = Path(job["result"]["path"]).read_text("utf-8")
    t.assertIn("stepped aside for another app", memo)
    runs = sorted((datetime.fromisoformat(e["ts"]) - timedelta(milliseconds=e["data"].get("ms", 0)), datetime.fromisoformat(e["ts"])) for e in new if e["type"] == "model.run")
    for (s1, e1), (s2, e2) in zip(runs, runs[1:]):
        t.assertLessEqual(e1, s2 + timedelta(seconds=1), "two models overlapped")
    for e in new:
        if e["type"] == "model.run":
            t.assertLessEqual(e["data"]["peak_mb"], 1024)


@case("O", "a job stopped part way keeps its pieces, shows as unfinished, and resumes without redoing them")
def _():
    _ready("transcription")
    wav = DOCS / "long-spoken.wav"
    if not wav.exists():
        skip("the long recording was not made")
    tm = app("twinmind")
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", {"path": str(wav), "title": "Stopped and resumed", "speed": "fast"}, base=tm)
    job = _until(lambda: (lambda j: j if (j.get("progress") or {}).get("diarize", [0])[0] >= 1 or j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 400, 1)
    t.assertEqual(job["status"], "running", job)
    t.assertTrue(_tm("POST", "stop", {}, base=tm)["stopped"])
    t.assertEqual(http("GET", "/api/jobs/" + r["id"], base=tm)[1]["status"], "stopped")
    t.assertTrue(_until(lambda: _status()["leases"] == [] and _status()["line"] == [], 10), "the model must stop with the job")
    u = [x for x in _tm("GET", "state", base=tm)["unfinished"] if x["name"] == wav.name]
    t.assertEqual(len(u), 1)
    kept = u[0]["progress"]["diarize"][0]
    t.assertGreaterEqual(kept, 1)
    t.assertEqual(u[0]["state"], "stopped")
    mark = len(events())
    job = _job(tm, {**u[0]["item"]}, wait=900)
    t.assertEqual(job["status"], "done", job)
    t.assertTrue(job["result"]["resumed"])
    new = events()[mark:]
    t.assertTrue([e for e in new if e["type"] == "job.resumed"])
    windows = job["progress"]["diarize"][1]
    heard = len([e for e in new if e["type"] == "model.run" and "diarization" in e["data"]["name"]])
    t.assertEqual(heard, windows - kept, "saved windows must not be heard again")
    memo = Path(job["result"]["path"]).read_text("utf-8")
    t.assertIn("picked up from saved pieces after a stop", memo)
    t.assertIn("fast speed was chosen", memo)
    body = [l for l in memo.split("Appendix: Transcript")[1].splitlines() if l.startswith("[")]
    t.assertRegex(body[-1], r"^\[00:0[6-9]:", "the transcript must reach the end of the recording")
    t.assertEqual([x for x in _tm("GET", "state", base=tm)["unfinished"] if x["name"] == wav.name], [])


@case("O", "a model stopped by hand ends with its own outcome, not as a failure")
def _():
    p = subprocess.Popen([GOV, "run", "--app", "t", "--name", "by-hand", "--est-mb", "10", "--", *burner(5, 60)], env=env(), creationflags=NOWIN)
    t.assertTrue(_until(lambda: _status()["leases"], 6))
    t.assertTrue(json.loads(gov("kill")[1])["evicted"])
    t.assertEqual(p.wait(timeout=10), 143)
    run = [e for e in events() if e["type"] == "model.run" and e["data"]["name"] == "by-hand"][-1]
    t.assertEqual(run["data"]["end"], "stopped by hand")
    out = py("import json; from mitra_workers import models\n"
             "try:\n    models._raise_for(143, ''); print(json.dumps('no'))\nexcept models.Stopped as e:\n    print(json.dumps('stopped'))")
    t.assertEqual(out, "stopped")


def _notes_job_at_work(title):
    """A TwinMind job on a long transcript, returned once its notes model has finished a section."""
    src = DOCS / "long-talk.txt"
    src.write_text(LONG_TALK + f"\n[00:16:00] Priya: That is all for {title}.\n", "utf-8")
    tm = app("twinmind")
    s, r, _ = http("POST", "/api/apps/twinmind/job/run", {"path": str(src), "title": title}, base=tm)
    t.assertEqual(s, 200, r)
    job = _until(lambda: (lambda j: j if (j.get("progress") or {}).get("understand", [0])[0] >= 1 or j["status"] not in ("running", "starting") else None)(http("GET", "/api/jobs/" + r["id"], base=tm)[1]), 240, 1)
    t.assertEqual(job["status"], "running", job)
    return tm, r["id"], src


@case("O", "stopping the model by hand stops the job and keeps its pieces; the job does not carry on without them")
def _():
    _ready("meeting-notes")
    tm, jid, src = _notes_job_at_work("Stopped by hand")
    time.sleep(2)                                              # into the next section
    t.assertTrue(http("POST", "/api/system/evict", {}, base=tm)[1]["evicted"])
    job = _until(lambda: (lambda j: j if j["status"] != "running" else None)(http("GET", "/api/jobs/" + jid, base=tm)[1]), 30, 0.5)
    t.assertEqual(job["status"], "stopped", job)
    t.assertFalse(list((TMP / "dropbox").rglob("* Stopped by hand.md")), "no memo may be written from a job that was stopped")
    u = [x for x in _tm("GET", "state", base=tm)["unfinished"] if x["name"] == src.name]
    t.assertEqual(len(u), 1)
    t.assertEqual(u[0]["state"], "stopped")
    t.assertGreaterEqual(u[0]["progress"]["understand"][0], 1)
    t.assertEqual(_status()["leases"], [])
    job = _job(tm, {**u[0]["item"]}, wait=600)
    t.assertEqual(job["status"], "done", job)
    t.assertTrue(job["result"]["resumed"])
    t.assertTrue(list((TMP / "dropbox").rglob("* Stopped by hand.md")))


@case("O", "closing an app stops its job with it: no worker or model is left running, and the job can be resumed")
def _():
    _ready("meeting-notes")
    tm, jid, src = _notes_job_at_work("Closed with the app")
    s, d, _ = http("POST", "/api/stop/twinmind", {})
    t.assertEqual(s, 200, d)
    t.assertTrue(gone(tm), "the app should have ended")
    left = lambda: [p[:160] for p in mitra_processes() if "mitra_workers" in p or "llama-server" in p or "mitra-governor" in p]   # noqa: E731
    _until(lambda: not left(), 12)
    t.assertEqual(left(), [], "the job's worker and its model must end with the app")
    t.assertEqual(json.loads((HOME / "run" / "jobs" / f"{jid}.json").read_text("utf-8"))["status"], "stopped")
    t.assertFalse(list((TMP / "dropbox").rglob("* Closed with the app.md")))
    tm = app("twinmind")
    st = _tm("GET", "state", base=tm)
    t.assertIsNone(st["running"])
    u = [x for x in st["unfinished"] if x["name"] == src.name]
    t.assertEqual(len(u), 1)
    t.assertGreaterEqual(u[0]["progress"]["understand"][0], 1)
    t.assertTrue(_tm("POST", "discard", {"key": u[0]["key"]}, base=tm)["discarded"])


# ============================================================================================
# P. the meeting library: old and new meetings, tags and projects, names (0.10.0)
# ============================================================================================
def _lib_home():
    """A home with a small meeting archive: three transcripts with front matter, in year and month folders."""
    if "lib_home" in S:
        return S["lib_home"]
    home, arch = TMP / "home-lib", TMP / "archive" / "normalized"
    write_config(home, 7486, model_budget_mb=100, meeting_archive=str(arch))
    (home / "twinmind").mkdir(parents=True, exist_ok=True)
    (home / "twinmind" / "project_names.json").write_text(json.dumps({"acme": "Acme"}), "utf-8")
    def rec(folder, name, date, client, people, body):
        d = arch / folder
        d.mkdir(parents=True, exist_ok=True)
        sp = "".join(f'  - label: "{p}"\n    resolved_to: {p}\n    confidence: high\n' for p in people)
        (d / name).write_text(f'---\ntype: transcript\ndate: {date}\nstart: "10:00"\nend: "12:30"\ntitle: "{name[:-3]}"\nsource: twinmind\n'
                              f"speakers:\n{sp}client: {client}\nlines: {len(body.splitlines())}\n---\n\n{body}\n", "utf-8")
    rec("2026/March", "260312 — Acme Cloud Program Staffing Review.md", "2026-03-12", "ACME", ["Anirudh", "Priya"],
        "10:00 Priya: Anurag, we need two trainers for the cloud program by Friday.\n10:01 Anirudh: I will send the staffing plan tomorrow.\n10:02 Priya: The budget stays at forty lakh.")
    rec("2026/April", "260402 — Acme Cloud Program Pricing.md", "2026-04-02", "Acme", ["Anirudh", "Dev"],
        "10:00 Dev: The pricing for the labs is still open.\n10:01 Anirudh: Please share the lab costs by Monday.")
    rec("2026/April", "260410 — Northwind Delivery Negotiation.md", "2026-04-10", "Northwind", ["Anirudh", "Sam"],
        "10:00 Sam: We can start delivery in May.\n10:01 Anirudh: Understood.")
    S["lib_home"], S["lib_arch"] = home, arch
    return home


def _lib(method, name, body=None):
    base = re.search(r"http://[\d.:]+", cli("open", "twinmind", home=_lib_home())[1]).group(0)
    s, d, _ = http(method, "/api/apps/twinmind/" + name, body, base=base)
    t.assertEqual(s, 200, d)
    return d


@case("P", "old meetings from the archive are listed with their date, project and people, newest first")
def _():
    d = _lib("GET", "library")
    t.assertEqual(d["total"], 3)
    t.assertEqual([r["title"] for r in d["rows"]], ["Northwind Delivery Negotiation", "Acme Cloud Program Pricing", "Acme Cloud Program Staffing Review"])
    t.assertEqual([r["date"] for r in d["rows"]], ["2026-04-10", "2026-04-02", "2026-03-12"])
    t.assertEqual(d["rows"][2]["speakers"], ["Anirudh", "Priya"])
    t.assertEqual(d["rows"][0]["minutes"], 150)
    t.assertEqual(dict(d["facets"]["projects"]), {"Acme": 2, "Northwind": 1}, "ACME and Acme are one project")
    t.assertFalse(any(r["has_summary"] for r in d["rows"]))


@case("P", "meetings are filtered by project, by year, and by words in the title or the people")
def _():
    t.assertEqual(_lib("GET", "library?project=Acme")["total"], 2)
    t.assertEqual(_lib("GET", "library?q=dev")["total"], 1)
    t.assertEqual(_lib("GET", "library?q=cloud%20staffing")["rows"][0]["date"], "2026-03-12")
    t.assertEqual(_lib("GET", "library?year=2025")["total"], 0)


@case("P", "one meeting opens with its transcript exactly as recorded, and what was promised quoted")
def _():
    row = _lib("GET", "library?q=staffing")["rows"][0]
    S["lib_id"] = row["id"]
    m = _lib("GET", "meeting?id=" + row["id"])
    t.assertIsNone(m["summary"])
    t.assertEqual(m["transcript_lines"], 3)
    t.assertTrue(m["transcript"].startswith("10:00 Priya: Anurag, we need two trainers"), "the archive's words are shown as they are")
    t.assertNotIn("type: transcript", m["transcript"])
    t.assertIn("10:01 Anirudh: I will send the staffing plan tomorrow.", m["commitments"])
    t.assertEqual(m["project"], "Acme")


@case("P", "tags and a project are saved outside the archive; the archive file is not changed")
def _():
    f = S["lib_arch"] / "2026" / "March" / "260312 — Acme Cloud Program Staffing Review.md"
    before = (f.read_bytes(), f.stat().st_mtime_ns)
    _lib("POST", "meta", {"id": S["lib_id"], "tags": ["staffing", "urgent", "staffing"], "project": "Acme Cloud"})
    row = _lib("GET", "library?q=staffing")["rows"][0]
    t.assertEqual((row["tags"], row["project"]), (["staffing", "urgent"], "Acme Cloud"))
    t.assertEqual(_lib("GET", "library?project=Acme%20Cloud")["total"], 1)
    t.assertEqual((f.read_bytes(), f.stat().st_mtime_ns), before)
    t.assertTrue((_lib_home() / "twinmind" / "meta.json").is_file())
    written = [p for p in (TMP / "archive").rglob("*") if p.is_file() and p.suffix != ".md"]
    t.assertEqual(written, [], "nothing may be written inside the archive")


@case("P", "search inside finds what was said in any transcript, quoted exactly")
def _():
    hits = _lib("GET", "inside?q=forty%20lakh")
    t.assertEqual(len(hits), 1)
    t.assertEqual(hits[0]["text"], "10:02 Priya: The budget stays at forty lakh.")
    t.assertEqual(_lib("GET", "inside?q=zebra%20crossing"), [])


@case("P", "a summary written for an old meeting appears under that meeting, and across its project")
def _():
    m = _lib("GET", "meeting?id=" + S["lib_id"])
    base = re.search(r"http://[\d.:]+", cli("open", "twinmind", home=_lib_home())[1]).group(0)
    job = _job(base, {"path": m["path"], "title": m["title"]})
    t.assertEqual(job["status"], "done", job)
    memo = Path(job["result"]["path"])
    t.assertNotIn(str(TMP / "archive"), str(memo), "the summary is saved in Mitra's own folder")
    t.assertNotIn("type: transcript", memo.read_text("utf-8").split("Appendix: Transcript")[1], "front matter is not speech")
    d = _lib("GET", "library")
    t.assertEqual(d["total"], 3, "the summary is shown under its meeting, not as a fourth meeting")
    t.assertTrue(next(r for r in d["rows"] if r["id"] == S["lib_id"])["has_summary"])
    m = _lib("GET", "meeting?id=" + S["lib_id"])
    t.assertIn("Commitments heard", m["summary"])
    a = _lib("GET", "across?project=Acme%20Cloud")
    t.assertEqual((a["meetings"], a["with_summary"]), (1, 1))
    t.assertEqual(dict(a["people"]), {"Anirudh": 1, "Priya": 1})


@case("P", "a name on the people list is put right wherever a wrong spelling of it appears")
def _():
    _lib("POST", "people", {"people": [{"name": "Anirudh", "aliases": ["Anurag", "Anirud"]}, {"name": "", "aliases": ["x"]}]})
    p = _lib("GET", "people")
    t.assertEqual(p["people"], [{"name": "Anirudh", "aliases": ["Anurag", "Anirud"]}])
    t.assertEqual(p["heard"][0], "Anirudh")
    t.assertIn("Priya", p["heard"])
    out = py("import json; from mitra_workers import library; print(json.dumps(library.fix_names(\"Anurag said so. anurag's plan. Anurags is another word.\")))", home=_lib_home())
    t.assertEqual(out, ["Anirudh said so. Anirudh's plan. Anurags is another word.", 2])
    # and in a memo written after that: the transcript says "Anurag", the memo must say "Anirudh"
    base = re.search(r"http://[\d.:]+", cli("open", "twinmind", home=_lib_home())[1]).group(0)
    src = DOCS / "names.txt"
    src.write_text("[00:00:05] Priya: Anurag, please send the plan by Friday.\n[00:00:09] Speaker 2: I will send it tomorrow.\n", "utf-8")
    job = _job(base, {"path": str(src), "title": "Names"})
    memo = Path(job["result"]["path"]).read_text("utf-8")
    t.assertIn("Priya: Anirudh, please send the plan by Friday.", memo)
    t.assertNotIn("Anurag", memo)


@case("P", "the people list reaches the speech model as the names to expect")
def _():
    code = (_FAKE + "seen = []\n"
            "def fake_run(app, p, cmd, what=''):\n"
            "    seen.append(cmd[cmd.index('--prompt') + 1] if '--prompt' in cmd else None)\n"
            "    Path(cmd[cmd.index('-of') + 1] + '.json').write_text(json.dumps({'result': {'language': 'en'}, 'transcription': []}), 'utf-8')\n"
            "models._run_model = fake_run\n"
            f"wav = Path({str(DOCS / 'silent-16min.wav')!r})\n"
            "if not wav.exists(): silent(wav, 960)\n"
            "models.transcribe('twinmind', wav, wav_ready=True, names=['Anirudh', 'Priya'])\n"
            "print(json.dumps(seen[0]))")
    t.assertEqual(py(code), "People in this meeting or mentioned in it: Anirudh, Priya.")


@case("P", "the TwinMind page has the library: meetings, one meeting as summary and transcript, across meetings, people")
def _():
    page = (ROOT / "apps" / "twinmind" / "ui" / "index.html").read_text("utf-8")
    for part in ('data-tab="lib"', 'data-tab="across"', 'data-tab="people"', "Search inside transcripts", "Write the summary", "Save tags",
                 'data-m="tr"', "From your archive (read only)", "api('people'", "api('across?"):
        t.assertIn(part, page)


# ============================================================================================
# Q. live meetings: noticing one, recording two tracks, the transcript as it grows (0.10.0)
# ============================================================================================
EAR = str(ROOT / "bin" / f"mitra-ear{EXE}")


def _ear(*args, timeout=30):
    if not Path(EAR).is_file():
        skip("the recorder is not built on this system")
    r = subprocess.run([EAR, *args], capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    return r.returncode, r.stdout, r.stderr


def _tone(path, seconds, level=6000, rate=16000):
    """A WAV of a steady tone (or silence at level 0): stands in for speech where only loudness matters."""
    import math
    import wave as _wave
    from array import array as _array
    with _wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(_array("h", (int(level * math.sin(i * 0.05)) for i in range(int(seconds * rate)))).tobytes())


@case("Q", "the recorder says which programs are recording from a microphone, as JSON")
def _():
    code, out, err = _ear("who")
    t.assertEqual(code, 0, err)
    t.assertIsInstance(json.loads(out)["using"], list)
    code, out, err = _ear("devices")
    t.assertEqual(code, 0, err)
    t.assertIn("microphone", json.loads(out))


@case("Q", "only an app that declares the meetings service may ask who is using the microphone")
def _():
    s, d, _ = http("GET", "/api/mic", base=app("assistant"))
    t.assertEqual(s, 403, d)
    s, d, _ = http("GET", "/api/mic")
    t.assertEqual(s, 403, "the launcher has no business asking either")
    s, d, _ = http("GET", "/api/mic", base=app("twinmind"))
    t.assertEqual(s, 200, d)
    t.assertEqual(sorted(d), ["meeting", "using"])


@case("Q", "a call app recording from the microphone is noticed as a meeting; when it stops, it is no longer")
def _():
    if os.name != "nt":
        skip("meeting detection is built for Windows only")
    _ear("who")
    fake, d = TMP / "zoom-meeting-test.exe", TMP / "fake-meeting"
    shutil.copyfile(EAR, fake)
    p = subprocess.Popen([str(fake), "record", "--dir", str(d), "--no-system"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    try:
        time.sleep(2.5)
        if p.poll() is not None:
            skip("this machine has no microphone to record from: " + p.stderr.read().decode(errors="replace")[:120])
        tm = app("twinmind")
        seen = _until(lambda: (lambda m: m if m["meeting"] else None)(http("GET", "/api/mic", base=tm)[1]), 8)
        t.assertEqual(seen["meeting"], "Zoom", seen)
        t.assertTrue(any(u["name"] == "zoom-meeting-test.exe" and u["meeting"] for u in seen["using"]))
    finally:
        p.stdin.close()
        p.wait(timeout=10)
    t.assertTrue(_until(lambda: http("GET", "/api/mic", base=app("twinmind"))[1]["meeting"] == "", 8))


@case("Q", "the recorder writes both tracks in pieces of the same length and ends cleanly when told to")
def _():
    if os.name != "nt":
        skip("the recorder has been run on Windows only")
    _ear("who")
    d = TMP / "ear-run"
    p = subprocess.Popen([EAR, "record", "--dir", str(d), "--segment", "5"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    time.sleep(7.5)
    if p.poll() is not None:
        skip("this machine has no sound device to record from: " + p.stderr.read().decode(errors="replace")[:120])
    st = json.loads((d / "status.json").read_text("utf-8"))
    t.assertEqual(st["state"], "recording")
    t.assertEqual(st["pieces_done"], 1)
    (d / "stop").write_text("", "utf-8")
    t.assertEqual(p.wait(timeout=10), 0)
    t.assertEqual(json.loads((d / "status.json").read_text("utf-8"))["state"], "ended")
    t.assertEqual(list(d.glob("*.part")), [], "no half-written piece is left")
    names = [x["name"] for x in st["tracks"]]
    import wave as _wave
    for name in names:
        with _wave.open(str(d / f"{name}-0001.wav")) as w:
            t.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (16000, 1, 2))
            t.assertAlmostEqual(w.getnframes() / 16000, 5.0, delta=0.05, msg=f"{name}: every piece but the last is exactly one segment long")
        t.assertTrue((d / f"{name}-0002.wav").is_file())


_LIVE = r'''
import json, sys, wave
from pathlib import Path
from mitra_workers import live, models, library
SEGS = []
def fake_run(app, p, cmd, what=""):
    Path(cmd[cmd.index("-of") + 1] + ".json").write_text(json.dumps({"transcription": [{"text": t, "offsets": {"from": int(a * 1000), "to": int(b * 1000)}} for a, b, t in SEGS]}), "utf-8")
models._run_model = fake_run
models.transcribe_plan = lambda p: ([], "")
P = {"runtime_path": "x", "file": "f.bin", "model": "fake", "args": []}
'''


@case("Q", "a line that runs into the end of a piece is held back and heard whole with the next piece")
def _():
    a, b = DOCS / "lp-0001.wav", DOCS / "lp-0002.wav"
    _tone(a, 30); _tone(b, 30)
    d = py(_LIVE + f"a, b = Path({str(a)!r}), Path({str(b)!r})\n"
           "SEGS[:] = [(0.0, 20.0, ' First sentence.'), (27.5, 30.0, ' Second sentence starts')]\n"
           "one, held = live.hear_piece('t', P, a)\n"
           "SEGS[:] = [(0.0, 6.0, ' Second sentence starts and ends here.'), (8.0, 12.0, ' Third.')]\n"
           "two, held2 = live.hear_piece('t', P, b, a, held)\n"
           "SEGS[:] = [(0.0, 20.0, ' Alone.'), (27.5, 30.0, ' The very end.')]\n"
           "last, held3 = live.hear_piece('t', P, a, last=True)\n"
           "print(json.dumps({'one': [l['text'] for l in one], 'held': held, 'two': [(round(l['start'], 1), l['text']) for l in two], 'held2': held2,\n"
           "                  'last': len(last), 'held3': held3, 'left': [f.name for f in a.parent.glob('lp-*lead*')]}))")
    t.assertEqual(d["one"], ["First sentence."])
    t.assertAlmostEqual(d["held"], 2.5, delta=0.01)
    t.assertEqual(d["two"], [[-2.5, "Second sentence starts and ends here."], [5.5, "Third."]], "times are from the piece's own start")
    t.assertEqual((d["last"], d["held3"]), (2, 0.0), "the last piece of a recording keeps its last line")
    t.assertEqual(d["left"], [], "the temporary joined file is removed")


@case("Q", "a stock phrase heard on a near-silent piece is dropped; the same words on a spoken piece are kept")
def _():
    faint, clear = DOCS / "faint.wav", DOCS / "clear.wav"
    _tone(faint, 10, level=60); _tone(clear, 10, level=6000)
    d = py(_LIVE + f"faint, clear = Path({str(faint)!r}), Path({str(clear)!r})\n"
           "SEGS[:] = [(1.0, 2.0, ' Thank you.'), (3.0, 6.0, ' The budget is forty lakh.')]\n"
           "print(json.dumps({'faint_loud': live.loud(faint), 'clear_loud': live.loud(clear),\n"
           "                  'faint': [l['text'] for l in live.hear_piece('t', P, faint, last=True)[0]], 'clear': [l['text'] for l in live.hear_piece('t', P, clear, last=True)[0]]}))")
    t.assertLess(d["faint_loud"], 150)
    t.assertGreater(d["clear_loud"], 1000)
    t.assertEqual(d["faint"], ["The budget is forty lakh."])
    t.assertEqual(d["clear"], ["Thank you.", "The budget is forty lakh."])


@case("Q", "the pieces are put together into one recording per track and a mix, all the same length")
def _():
    home = _nm_home()
    d = home / "run" / "live" / "20260101-100000"
    d.mkdir(parents=True, exist_ok=True)
    (d / "meeting.json").write_text(json.dumps({"stamp": "2026-01-01 1000", "title": "Assembled"}), "utf-8")
    _tone(d / "mic-0001.wav", 30, 3000); _tone(d / "sys-0001.wav", 30, 0)
    _tone(d / "mic-0002.wav", 12, 0); _tone(d / "sys-0002.wav", 12.5, 5000)
    out = py("import json, wave; from pathlib import Path; from mitra_workers import live\n"
             f"f = live.assemble(Path({str(d)!r}), 'Assembled')\n"
             "n = {k: wave.open(f[k]).getnframes() for k in ('mic', 'sys', 'mix')}\n"
             "print(json.dumps({'n': n, 'name': Path(f['mix']).name, 'you': live.owner_speaker([{'start': 0, 'end': 29, 'speaker': 'Speaker 1'}, {'start': 31, 'end': 42, 'speaker': 'Speaker 2'}], Path(f['mic']), Path(f['sys']))}))", home=home)
    t.assertEqual(len(set(out["n"].values())), 1, out)
    t.assertEqual(out["n"]["mix"], int(42.5 * 16000))
    t.assertEqual(out["name"], "2026-01-01 1000 Assembled.mix.wav")
    t.assertEqual(out["you"], "Speaker 1", "the voice that is loud on the microphone track is the person at this computer")
    t.assertTrue((d / "assembled").is_file())


@case("Q", "TwinMind reports whether it can record, the live model, and recordings left without a memo")
def _():
    home = _nm_home()
    d = home / "run" / "live" / "20260102-090000"
    d.mkdir(parents=True, exist_ok=True)
    (d / "meeting.json").write_text(json.dumps({"title": "Left behind", "started": 1767340800}), "utf-8")
    _tone(d / "mic-0001.wav", 5, 0); _tone(d / "sys-0001.wav", 5, 4000)
    st = http("GET", "/api/apps/twinmind/live", base=_nm_base())[1]
    t.assertIsNone(st["recording"])
    t.assertEqual(st["recorder"], Path(EAR).is_file())
    t.assertIn("Left behind", [r["title"] for r in st["leftover"]])
    t.assertNotIn("Assembled", [r["title"] for r in st["leftover"]], "a recording already put together is not offered again")
    t.assertFalse(http("POST", "/api/apps/twinmind/live/stop", {}, base=_nm_base())[1]["stopped"])


@case("Q", "the TwinMind page has the Live tab: the offer to record, levels, the growing transcript, your notes")
def _():
    page = (ROOT / "apps" / "twinmind" / "ui" / "index.html").read_text("utf-8")
    for part in ('data-tab="live"', "Do you want me to record it?", "Not this one", "Start recording", "Stop and write the memo", 'id="liveLines"',
                 'id="liveNotes"', "M.api('/api/mic')", "api('job/live'", "Write its memo", "only while TwinMind is open"):
        t.assertIn(part, page)


@case("K", "stopping everything leaves no app, worker or model process behind")
def _():
    code, out = cli("stop")
    t.assertIn("Stopped", out)
    t.assertIn("No app is running", cli("apps")[1])
    # an app stops its job workers before it exits; on a busy machine that takes a few seconds
    _until(lambda: not mitra_processes(), 15)
    left = mitra_processes()
    t.assertFalse(left, "a worker, governor or model process outlived its app: " + " | ".join(c[:14] + c[-60:] for c in left) + f" (started before the suite: {sorted(_BEFORE)})")
    t.assertEqual(list((HOME / "run" / "apps").glob("*.json")), [])


def main():
    if "--list" in sys.argv:
        for i, (area, name, _) in enumerate(CASES, 1):
            print(f"T{i:03d}  {area}  {name}")
        print(f"\n{len(CASES)} cases")
        return
    if not Path(CLI).exists() or not Path(GOV).exists():
        sys.exit(f"Binaries not found in {ROOT / 'bin'}. Build first.")
    write_config(HOME, PORT)
    fixtures()
    server = subprocess.Popen([CLI, "serve"], env=env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NOWIN)
    for _ in range(50):
        if alive(BASE):
            break
        time.sleep(0.2)
    else:
        sys.exit("The test launcher did not start.")

    t0, rows = time.time(), []
    for i, (area, name, fn) in enumerate(CASES, 1):
        num = f"T{i:03d}"
        if ONLY and num not in ONLY:
            continue
        ts, state, detail = time.time(), "pass", ""
        try:
            fn()
        except unittest.SkipTest as e:
            state, detail = "skip", str(e)
        except AssertionError as e:
            state, detail = "FAIL", (str(e).strip().splitlines() or ["assertion failed"])[-1][:240]
            why = re.search(r"'error': (['\"])(.{0,400}?)\1[,}]", str(e), re.S)     # a failed job: keep its own error, which the cut above loses
            if why:
                detail += " | job error: " + why.group(2).replace("\\n", " ")
        except Exception as e:
            state, detail = "ERROR", f"{type(e).__name__}: {e}"[:240]
        rows.append((num, area, name, state, round(time.time() - ts, 1), detail))
        print(f"  {state:<5} {num} {area}  {name}  ({rows[-1][4]} s)" + (f"\n         {detail}" if detail else ""), flush=True)

    for home in [HOME] + [p for p in TMP.glob("home-*")]:
        try:
            cli("stop", home=home, timeout=30)
        except Exception:
            pass
    try:
        server.wait(timeout=5)
    except Exception:
        server.kill()
    counts = {s: sum(1 for r in rows if r[3] == s) for s in ("pass", "FAIL", "ERROR", "skip")}
    summary = f"{counts['pass']} passed, {counts['FAIL'] + counts['ERROR']} failed, {counts['skip']} skipped of {len(rows)} in {time.time() - t0:.0f} s"
    print("\n" + summary)
    out = ROOT / "logs" / "tests" / "results"
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{datetime.now():%Y-%m-%d-%H%M%S}.md"
    areas = {"A": "launcher and command", "B": "each app is its own process", "C": "products kept separate", "D": "each app's screen", "E": "conversion",
             "F": "governor", "G": "TwinMind pipeline", "H": "memory log", "I": "moving between systems", "J": "security", "K": "resources and package", "L": "real models",
             "M": "files: Open with, drop to open, structure kept", "N": "TwinMind on real speech"}
    lines = [f"# Mitra test run {datetime.now():%Y-%m-%d %H:%M}", "", summary + (" (quick: model tests skipped)" if QUICK else ""), "",
             f"Platform: {sys.platform}, Python {sys.version.split()[0]}", "", "| Area | Cases | Passed | Failed | Skipped |", "|---|---|---|---|---|"]
    for k, label in areas.items():
        mine = [r for r in rows if r[1] == k]
        if mine:
            lines.append(f"| {k}. {label} | {len(mine)} | {sum(r[3] == 'pass' for r in mine)} | {sum(r[3] in ('FAIL', 'ERROR') for r in mine)} | {sum(r[3] == 'skip' for r in mine)} |")
    lines += ["", "| Case | Area | What it checks | Result | Seconds | Note |", "|---|---|---|---|---|---|"]
    lines += [f"| {n} | {a} | {name} | {s} | {sec} | {d.replace('|', '/')} |" for n, a, name, s, sec, d in rows]
    report.write_text("\n".join(lines) + "\n", "utf-8")
    print("Report:", report)
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if counts["FAIL"] + counts["ERROR"] else 0)


if __name__ == "__main__":
    main()

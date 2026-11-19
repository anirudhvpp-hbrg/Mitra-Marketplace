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
            "models.transcribe('twinmind', wav, wav_ready=True, names=['Anirudh', 'Priya'])\n"
            "print(json.dumps(seen[0]))")
    t.assertEqual(py(code), "People in this meeting or mentioned in it: Anirudh, Priya.")


@case("P", "the TwinMind page has the library: meetings, one meeting as summary and transcript, across meetings, people")
def _():
    page = (ROOT / "apps" / "twinmind" / "ui" / "index.html").read_text("utf-8")
    for part in ('data-tab="lib"', 'data-tab="across"', 'data-tab="people"', "Search inside transcripts", "Write the summary", "Save tags",
                 'data-m="tr"', "From your archive (read only)", "api('people'", "api('across?"):
        t.assertIn(part, page)



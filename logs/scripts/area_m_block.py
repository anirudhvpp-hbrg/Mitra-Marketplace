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
    has(rich("report.pdf"), "Acme Ltd  \n12 Hill Road  \nPune 411001")


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
    has(rich("budget.rtf"), "# Budget", "\n## Fixed costs", "Rent is *due* monthly.", "- Rent\n- Power\n1. Signed", absent=["heading 1", "·"])


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
    t.assertNotIn("Desktop\\", out)
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



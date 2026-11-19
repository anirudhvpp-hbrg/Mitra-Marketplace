"""Any file to Markdown, using the standard library (plus pure-Python pypdf for PDFs).

The aim is the source document's own structure, not just its words: headings at their levels,
nested and numbered lists, tables, bold and italic, links. Where a format does not record
structure (a PDF only records where each piece of text sits and in what font), it is worked
out from what is recorded, and where that is not possible the text is left as it was laid out.

If the optional `markitdown` package is installed it is used for formats not covered here.
"""
import csv
import io
import json
import math
import posixpath
import re
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CODE = {".py", ".js", ".ts", ".tsx", ".jsx", ".ps1", ".sh", ".bat", ".sql", ".yaml", ".yml", ".toml", ".ini", ".xml",
        ".css", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".rb", ".php", ".kt", ".swift", ".r", ".log"}
SUPPORTED = sorted({".md", ".markdown", ".txt", ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv", ".tsv",
                    ".json", ".ipynb", ".epub", ".rtf", ".odt", ".vtt", ".srt"} | CODE)


# ---- shared: every converter builds the same blocks and they are written out one way -------------

def _cell(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _table(rows: list[list]) -> str:
    rows = [r for r in rows if any(str(c or "").strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [list(r) + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(_cell(c) for c in rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _inline(runs) -> str:
    """Runs of (text, bold, italic[, link]) as Markdown. Neighbouring runs with the same
    formatting are joined first, and the markers hug the words, so the result reads cleanly."""
    merged = []
    for run in runs:
        text, b, i = run[0], bool(run[1]), bool(run[2])
        href = run[3] if len(run) > 3 else None
        if not text:
            continue
        if merged and merged[-1][1:] == [b, i, href]:
            merged[-1][0] += text
        else:
            merged.append([text, b, i, href])
    out = []
    for text, b, i, href in merged:
        text = re.sub(r"[ \t\u00a0]+", " ", text)
        core = text.strip()
        lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
        if core:
            mark = "***" if b and i else "**" if b else "*" if i else ""
            if mark:
                core = "\n".join(mark + part.strip() + mark if part.strip() else part for part in core.split("\n"))
            if href:
                core = f"[{core}]({href})"
        out.append(lead + core + trail if core else text)
    return "".join(out)


def _plain(runs) -> str:
    return " ".join("".join(r[0] for r in runs).split())


def _render(blocks) -> str:
    """Blocks to Markdown. A block is ("h", level, text), ("p", text), ("li", depth, ordered, text),
    ("quote", text) or ("raw", markdown). List items stay together and numbered items count up."""
    out, prev, prev_ordered, counters = [], None, None, {}
    for b in blocks:
        kind = b[0]
        if kind == "h":
            s = "#" * max(1, min(6, b[1])) + " " + " ".join(b[2].split())
        elif kind == "li":
            depth, ordered, text = b[1], b[2], " ".join(b[3].split())
            if not text:
                continue
            for d in [d for d in counters if d > depth]:
                del counters[d]
            if ordered:
                counters[depth] = counters.get(depth, 0) + 1
            else:
                counters.pop(depth, None)
            s = "    " * depth + (f"{counters[depth]}. " if ordered else "- ") + text
        elif kind == "quote":
            s = "\n".join("> " + l for l in b[1].strip().split("\n"))
        elif kind == "p":
            s = re.sub(r" *\n *", "  \n", b[1].strip())     # a line break inside a paragraph stays a line break
            s = re.sub(r"^(#{1,6}\s)", r"\\\1", s, flags=re.M)   # running text that starts with "# " is not a heading
        else:
            s = b[1]
        if not s.strip():
            continue
        if kind != "li":
            counters = {}
        # items of one list sit on consecutive lines; a bulleted list followed by a numbered one are two lists
        same_list = kind == "li" and prev == "li" and not (b[1] == 0 and b[2] != prev_ordered)
        out.append(("\n" if same_list else "\n\n") + s)
        prev = kind
        if kind == "li" and b[1] == 0:
            prev_ordered = b[2]
    return "".join(out).strip()


# ---- PDF ------------------------------------------------------------------------------------------
# A PDF has no headings or paragraphs, only pieces of text with a position and a font. Headings are
# the lines set larger than the body text (or short lines set wholly in bold); a paragraph is a run
# of lines that each fill the width; a line that stops short keeps its line break.

_BULLET = re.compile(r"^(?:[\u2022\u25e6\u25aa\u25a0\u25cf\u25cb\u00b7\u2023\u2043\u2219\uf0b7\uf0a7\u27a2\u2713]|[-\u2013\u2014*](?=\s))\s*")
_NUMBER = re.compile(r"^(\d{1,3})[.)]\s+(?=\S)")
_LETTER = re.compile(r"^(\(?[a-zA-Z]\)|\([ivx]+\))\s+(?=\S)")
_PAGE_NO = re.compile(r"^(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?$", re.I)
_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi", re.I)


def _pdf_lines(reader) -> list[list[dict]]:
    """Per page, the lines of text with the font size most of the line is set in, how much of it
    is bold, and where it sits."""
    pages = []
    for page in reader.pages:
        lines, cur = [], [None]

        def flush():
            if cur[0] and cur[0]["text"].strip():
                c = cur[0]
                c["size"] = c["sizes"].most_common(1)[0][0] if c["sizes"] else 0
                c["text"] = " ".join(c["text"].split())
                lines.append(c)
            cur[0] = None

        def visit(text, cm, tm, font, size):
            if not text:
                return
            try:
                scale = math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3]) or 1
                fs = round(abs(float(size)) * scale * 2) / 2
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            except Exception:
                fs, x, y = 0, None, None
            bold = bool(font and _BOLD_FONT.search(str(font.get("/BaseFont", ""))))
            for k, part in enumerate(text.split("\n")):
                if k:
                    flush()
                    y = None        # the position is only known for the first line of a piece
                if not part:
                    continue
                if cur[0] is None:
                    cur[0] = {"text": "", "sizes": Counter(), "bold": 0, "n": 0, "x": x, "y": y}
                c, n = cur[0], len(part.strip())
                c["text"] += part
                if n:
                    c["sizes"][fs] += n
                    c["n"] += n
                    c["bold"] += n if bold else 0

        page.extract_text(visitor_text=visit)
        flush()
        pages.append(lines)
    return pages


def _drop_running_lines(pages):
    """Removes what repeats on every page (running headers and footers) and bare page numbers."""
    if len(pages) < 2:
        return
    norm = lambda l: re.sub(r"\d+", "#", l["text"].lower())
    seen = Counter()
    for lines in pages:
        for key in {norm(l) for l in lines[:2] + lines[-2:]}:
            seen[key] += 1
    repeated = {k for k, n in seen.items() if len(pages) >= 3 and n >= max(3, 0.6 * len(pages))}
    for lines in pages:
        for idx in sorted({0, 1, len(lines) - 2, len(lines) - 1}, reverse=True):
            if 0 <= idx < len(lines) and (norm(lines[idx]) in repeated or _PAGE_NO.match(lines[idx]["text"])):
                del lines[idx]


def _pdf(p: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(p))
    try:
        pages = _pdf_lines(reader)
    except Exception:
        pages = []
    if not any(pages):
        parts = []
        for i, page in enumerate(reader.pages, 1):   # no positions to work from: the text as laid out
            text = "  \n".join(l.rstrip() for l in (page.extract_text() or "").strip().splitlines())
            if text:
                parts.append(f"## Page {i}\n\n{text}")
        if not parts:
            return f"# {p.stem}\n\nNo extractable text. This PDF is probably scanned images and needs OCR."
        return f"# {p.stem}\n\n" + "\n\n".join(parts)
    _drop_running_lines(pages)
    every = [l for lines in pages for l in lines]
    weight = Counter()
    for l in every:
        weight[l["size"]] += l["n"]
    body = weight.most_common(1)[0][0] if weight else 0
    # A long document may set its running text in more than one size (the main text, an appendix,
    # notes). Any size that carries a tenth of the text is running text; headings are larger than all of them.
    body = max([s for s, n in weight.items() if n >= 0.10 * sum(weight.values())] or [body])
    is_big = lambda s: bool(body) and s >= body * 1.08 and s >= body + 0.9
    body_lines = [l for l in every if not is_big(l["size"])]
    lengths = sorted(len(l["text"]) for l in body_lines)
    full = lengths[int(len(lengths) * 0.9)] if len(lengths) >= 8 else 0     # how long a line that fills the width is
    # the distance between two lines of running text: the commonest gap (the smaller on a tie),
    # so that the wider gap between two paragraphs stands out against it
    gaps = Counter(round(a["y"] - b["y"]) for lines in pages for a, b in zip(lines, lines[1:])
                   if a["y"] is not None and b["y"] is not None and 0 < a["y"] - b["y"] < 60)
    leading = min(gaps, key=lambda g: (-gaps[g], g)) if gaps else 0

    # heading levels: each distinct larger size is a level, largest first
    sizes = sorted({l["size"] for l in every if is_big(l["size"]) and len(l["text"]) <= 140}, reverse=True)
    level = {s: min(i + 1, 4) for i, s in enumerate(sizes)}
    bold_level = max(2, min(len(sizes) + 1, 4))
    is_bold = lambda l: l["n"] and l["bold"] >= 0.9 * l["n"]
    bold_ok = sum(1 for l in every if is_bold(l)) <= 0.3 * len(every)       # a document set all in bold has no bold headings

    def heading(l):
        t = l["text"]
        if l["size"] in level:
            return level[l["size"]]
        if bold_ok and is_bold(l) and 2 < len(t) <= 80 and re.search(r"[A-Za-z]", t) and not re.search(r"[.,;:]$", t) and not _BULLET.match(t):
            return bold_level
        return 0

    found = [heading(l) for l in every]
    structured = any(found) and sum(1 for f in found if f) <= 0.4 * len(every)
    blocks, prev, prev_kind = [], None, None

    def new_block(l, first_on_page):
        t = l["text"]
        if _BULLET.match(t) or _NUMBER.match(t) or _LETTER.match(t):
            return True
        if prev is None or prev_kind == "h":
            return True
        gap = prev["y"] - l["y"] if not first_on_page and prev["y"] is not None and l["y"] is not None else None
        if gap is not None and leading and gap > 1.45 * leading:
            return True
        return None        # same block; whether the line is joined or broken is decided by the caller

    for n, lines in enumerate(pages, 1):
        if not structured and lines:
            blocks.append(("h", 2, f"Page {n}"))
            prev, prev_kind = None, "h"
        for k, l in enumerate(lines):
            t = l["text"]
            lvl = heading(l) if structured else 0
            if lvl:
                if prev_kind == "h" and blocks[-1][1] == lvl and prev is not None and prev["size"] == l["size"] and k > 0:
                    blocks[-1] = ("h", lvl, blocks[-1][2] + " " + t)       # a heading that wrapped onto a second line
                else:
                    blocks.append(("h", lvl, t))
                prev, prev_kind = l, "h"
                continue
            if new_block(l, k == 0):
                m = _NUMBER.match(t)
                if m:
                    blocks.append(["li", 0, True, t[m.end():]])
                elif _BULLET.match(t):
                    blocks.append(["li", 0, False, _BULLET.sub("", t, 1)])
                else:
                    blocks.append(["p", t])
            else:
                last = blocks[-1]
                before = last[-1]
                wrapped = full and len(prev["text"]) >= 0.72 * full          # the line above filled the width, so this continues it
                if k == 0 and not re.search(r"[.!?:]$", before):
                    wrapped = True                                          # a sentence carried over the page
                if wrapped and re.search(r"[a-z]-$", before) and t[:1].islower():
                    last[-1] = before[:-1] + t                              # a word hyphenated at the line end
                elif wrapped or last[0] == "li":
                    last[-1] = before + " " + t
                else:
                    last[-1] = before + "\n" + t                            # a short line keeps its break (addresses, totals)
            prev, prev_kind = l, blocks[-1][0]
    md = _render([tuple(b) for b in blocks])
    if not re.search(r"^# ", md, re.M):
        md = f"# {p.stem}\n\n{md}"
    return md


# ---- Word -----------------------------------------------------------------------------------------

def _docx(p: Path) -> str:
    val = f"{W}val"
    with zipfile.ZipFile(p) as z:
        names = set(z.namelist())
        part = lambda n: ET.fromstring(z.read(n)) if n in names else None
        body = part("word/document.xml").find(f"{W}body")
        styles_x, nums_x, rels_x = part("word/styles.xml"), part("word/numbering.xml"), part("word/_rels/document.xml.rels")
    styles = {}                                       # style id -> (name, outline level, based on)
    for s in (styles_x.iter(f"{W}style") if styles_x is not None else []):
        name, ol, based = s.find(f"{W}name"), s.find(f"{W}pPr/{W}outlineLvl"), s.find(f"{W}basedOn")
        styles[s.get(f"{W}styleId")] = ((name.get(val) or "").lower() if name is not None else "",
                                        int(ol.get(val)) if ol is not None else None, based.get(val) if based is not None else None)
    ordered = {}                                      # numbering id -> {level: is it numbered rather than bulleted}
    if nums_x is not None:
        abstract = {a.get(f"{W}abstractNumId"): {l.get(f"{W}ilvl"): (l.find(f"{W}numFmt").get(val) if l.find(f"{W}numFmt") is not None else "bullet")
                                                  not in ("bullet", "none") for l in a.iter(f"{W}lvl")} for a in nums_x.iter(f"{W}abstractNum")}
        for n in nums_x.iter(f"{W}num"):
            ref = n.find(f"{W}abstractNumId")
            ordered[n.get(f"{W}numId")] = abstract.get(ref.get(val), {}) if ref is not None else {}
    links = {r.get("Id"): r.get("Target") for r in (rels_x if rels_x is not None else []) if r.get("TargetMode") == "External"}

    def kind(sid, depth=0):
        """What a paragraph style means, from its name (with no styles part, the id is the name)."""
        name, ol, based = styles.get(sid, ((sid or "").lower(), None, None))
        m = re.match(r"heading\s*(\d)", name)
        if m:
            return ("h", int(m.group(1)))
        if name == "title":
            return ("title",)
        if "quote" in name:
            return ("quote",)
        if name.startswith("list"):
            return ("list", "number" in name)
        if ol is not None and ol < 9:
            return ("h", ol + 1)
        return kind(based, depth + 1) if based and depth < 6 else None

    def runs(el, href=None, out=None):
        out = [] if out is None else out
        for c in el:
            if c.tag == f"{W}r":
                rp = c.find(f"{W}rPr")
                on = lambda n: rp is not None and rp.find(f"{W}{n}") is not None and rp.find(f"{W}{n}").get(val, "true") not in ("0", "false")
                text = ""
                for t in c:
                    if t.tag == f"{W}t":
                        text += t.text or ""
                    elif t.tag == f"{W}tab":
                        text += " "
                    elif t.tag in (f"{W}br", f"{W}cr") and t.get(f"{W}type") != "page":
                        text += "\n"
                    elif t.tag == f"{W}noBreakHyphen":
                        text += "-"
                if text:
                    out.append((text, on("b"), on("i"), href))
            elif c.tag == f"{W}hyperlink":
                runs(c, links.get(c.get(f"{R}id")) or href, out)
            elif c.tag in (f"{W}ins", f"{W}smartTag", f"{W}sdt", f"{W}sdtContent", f"{W}fldSimple", f"{W}customXml"):
                runs(c, href, out)
        return out

    kinds = [kind(s.get(val)) for s in body.iter(f"{W}pStyle")]
    has_title = ("title",) in kinds

    # Many documents (exported from other tools, or formatted by hand) use no heading styles at
    # all: a heading is just a short paragraph in larger type, or all in bold. When there is not
    # one styled heading, headings are read from that formatting instead, as for a PDF.
    inferred = {}
    if not any(k and k[0] in ("h", "title") for k in kinds):
        def look(par):          # (smallest type size among its words or None, all bold, length)
            sizes, bold, n = [], True, 0
            for r in par.iter(f"{W}r"):
                text = "".join(t.text or "" for t in r.iter(f"{W}t")).strip()
                if not text:
                    continue
                n += len(text)
                sz, b = r.find(f"{W}rPr/{W}sz"), r.find(f"{W}rPr/{W}b")
                sizes.append(int(sz.get(val)) if sz is not None and (sz.get(val) or "").isdigit() else None)
                bold = bold and b is not None and b.get(val, "true") not in ("0", "false")
            return (min(sizes) if sizes and None not in sizes else None), bold and n > 0, n

        tops = [(c, *look(c)) for c in body if c.tag == f"{W}p"]
        tops = [x for x in tops if x[3]]
        weight = Counter()
        for _, sz, _, n in tops:
            weight[sz] += n
        sized = {s: n for s, n in weight.items() if s is not None}
        base = max([s for s, n in sized.items() if n >= 0.10 * sum(sized.values())] or [0])
        listed = lambda par: par.find(f"{W}pPr/{W}numPr") is not None
        big = [(par, sz) for par, sz, _, n in tops if base and sz and sz >= base * 1.1 and n <= 140 and not listed(par)]
        levels = {s: min(i + 1, 4) for i, s in enumerate(sorted({sz for _, sz in big}, reverse=True))} if len(big) <= 0.4 * len(tops) else {}
        inferred = {id(par): levels[sz] for par, sz in big if levels}
        bolds = [par for par, sz, b, n in tops if b and 2 < n <= 80 and id(par) not in inferred and not listed(par)
                 and not re.search(r"[.,;:]$", "".join(t.text or "" for t in par.iter(f"{W}t")).strip())]
        if bolds and sum(1 for x in tops if x[2]) <= 0.3 * len(tops):
            inferred.update({id(par): max(2, min(len(levels) + 1, 4)) for par in bolds})

    def para(par):
        ppr = par.find(f"{W}pPr")
        style = ppr.find(f"{W}pStyle") if ppr is not None else None
        k = kind(style.get(val)) if style is not None else None
        rs = runs(par)
        if not _plain(rs):
            return None
        if id(par) in inferred:
            return ("h", inferred[id(par)], _plain(rs))
        if k and k[0] == "title":
            return ("h", 1, _plain(rs))
        if k and k[0] == "h":
            return ("h", k[1] + (1 if has_title else 0), _plain(rs))    # under a Title, "Heading 1" is the second level
        num = ppr.find(f"{W}numPr") if ppr is not None else None
        num_id = num.find(f"{W}numId").get(val) if num is not None and num.find(f"{W}numId") is not None else None
        if (num is not None and num_id != "0") or (k and k[0] == "list"):
            lvl = int(num.find(f"{W}ilvl").get(val)) if num is not None and num.find(f"{W}ilvl") is not None else 0
            numbered = ordered[num_id].get(str(lvl), False) if num_id in ordered else bool(k and k[0] == "list" and k[1])
            return ("li", lvl, numbered, _inline(rs))
        return ("quote", _inline(rs)) if k and k[0] == "quote" else ("p", _inline(rs))

    def table(tbl):
        rows = []
        for tr in tbl.findall(f"{W}tr"):
            row = []
            for tc in tr.findall(f"{W}tc"):
                parts = []
                for el in tc:
                    if el.tag == f"{W}p":
                        b = para(el)
                        if b:
                            parts.append(("\u2022 " if b[0] == "li" else "") + b[-1].replace("\n", "<br>"))
                    elif el.tag == f"{W}tbl":          # a table inside a cell: its words, in order
                        parts.append(" ".join("".join(t.text or "" for t in el.iter(f"{W}t")).split()))
                row.append("<br>".join(parts))
                span = tc.find(f"{W}tcPr/{W}gridSpan")
                row += [""] * (int(span.get(val, "1")) - 1 if span is not None else 0)
            rows.append(row)
        return _table(rows)

    blocks = []

    def walk(el):
        for c in el:
            if c.tag == f"{W}p":
                b = para(c)
                if b:
                    blocks.append(b)
            elif c.tag == f"{W}tbl":
                blocks.append(("raw", table(c)))
            elif c.tag in (f"{W}sdt", f"{W}sdtContent"):
                walk(c)

    walk(body)
    return _render(blocks)


# ---- PowerPoint -----------------------------------------------------------------------------------

def _pptx(p: Path) -> str:
    out = [f"# {p.stem}"]
    text_of = lambda par: " ".join("".join(t.text or "" for t in par.iter(f"{A}t")).split())
    level_of = lambda par: int(par.find(f"{A}pPr").get("lvl", "0")) if par.find(f"{A}pPr") is not None else 0
    with zipfile.ZipFile(p) as z:
        slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
        for i, name in enumerate(slides, 1):
            root = ET.fromstring(z.read(name))
            title, blocks = None, []
            for el in root.iter():
                if el.tag == f"{P}sp":
                    ph = el.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                    role = ph.get("type", "body") if ph is not None else None
                    paras = [(level_of(par), text_of(par)) for par in el.iter(f"{A}p") if text_of(par)]
                    if role in ("sldNum", "dt", "ftr") or not paras:
                        continue
                    if role in ("title", "ctrTitle") and title is None:
                        title = " ".join(t for _, t in paras)
                    else:
                        blocks += [("li", lvl, False, t) for lvl, t in paras]
                elif el.tag == f"{A}tbl":
                    rows = [[" ".join(text_of(par) for par in tc.iter(f"{A}p") if text_of(par)) for tc in tr.findall(f"{A}tc")] for tr in el.findall(f"{A}tr")]
                    blocks.append(("raw", _table(rows)))
            if title is None and not blocks:      # no shapes recorded: the first line is the title
                paras = [text_of(par) for par in root.iter(f"{A}p") if text_of(par)]
                title, blocks = (paras[0] if paras else None), [("li", 0, False, t) for t in paras[1:]]
            elif title is None and blocks and blocks[0][0] == "li":
                title, blocks = blocks[0][3], blocks[1:]
            out.append(f"## Slide {i}" + (f": {title}" if title else ""))
            body = _render(blocks)
            if body:
                out.append(body)
            notes = f"ppt/notesSlides/notesSlide{i}.xml"
            if notes in z.namelist():
                n = [text_of(par) for par in ET.fromstring(z.read(notes)).iter(f"{A}p")]
                n = [x for x in n if x and not x.isdigit()]
                if n:
                    out.append("> Notes: " + " ".join(n))
    return "\n\n".join(out)


# ---- Excel ----------------------------------------------------------------------------------------

def _xlsx(p: Path, max_rows=2000) -> str:
    out = [f"# {p.stem}"]
    with zipfile.ZipFile(p) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = ["".join(t.text or "" for t in si.iter(f"{S}t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{S}si")]
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{S}sheet"):
            target = rels.get(sheet.get(f"{R}id"), "")
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if path not in z.namelist():
                continue
            rows = []
            for row in ET.fromstring(z.read(path)).iter(f"{S}row"):
                cells = []
                for c in row.iter(f"{S}c"):
                    col = 0
                    for ch in re.match(r"[A-Z]+", c.get("r", "A")).group(0):
                        col = col * 26 + ord(ch) - 64
                    v, t = c.find(f"{S}v"), c.get("t")
                    if t == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{S}t"))
                    else:
                        val = v.text if v is not None else ""
                    cells += [""] * (col - 1 - len(cells)) + [val]
                rows.append(cells)
                if len(rows) >= max_rows:
                    break
            out.append(f"## {sheet.get('name')}\n\n" + (_table(rows) or "_empty_"))
            if len(rows) >= max_rows:
                out.append(f"_Truncated at {max_rows} rows._")
    return "\n\n".join(out)


# ---- HTML -----------------------------------------------------------------------------------------

class _HTML(HTMLParser):
    SKIP = {"script", "style", "head", "nav", "noscript", "svg", "template", "iframe"}

    def __init__(self):
        super().__init__()
        self.out, self.skip, self.href, self.pre = [], 0, None, False
        self.lists, self.held, self.tables = [], [], []   # open lists, outputs set aside, open tables
        self.title, self.in_title = "", False

    def _hold(self):          # start collecting into a fresh buffer (a table cell, a quote, a heading)
        self.held.append(self.out)
        self.out = []

    def _release(self) -> str:
        text, self.out = "".join(self.out), self.held.pop()
        return text

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag in self.SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
            self._hold()
        elif tag == "table":
            self.tables.append([])
            self._hold()
        elif tag == "tr" and self.tables:
            self.tables[-1].append([])
        elif tag in ("td", "th") and self.tables:
            if not self.tables[-1]:
                self.tables[-1].append([])
            self._hold()
            self.tables[-1][-1].append(int(a.get("colspan") or 1) if str(a.get("colspan") or "1").isdigit() else 1)
        elif tag == "blockquote":
            self._hold()
        elif tag in ("p", "div", "section", "article", "dd", "figcaption", "header", "footer", "main", "aside"):
            self.out.append("\n\n")
        elif tag == "dt":
            self.out.append("\n\n**")
        elif tag == "hr":
            self.out.append("\n\n---\n\n")
        elif tag == "br":
            self.out.append("<br>" if self.tables else "  \n")
        elif tag in ("ul", "ol"):
            if not self.lists:
                self.out.append("\n")
            self.lists.append([tag, 0])
        elif tag == "li":
            if not self.lists:
                self.lists.append(["ul", 0])
            self.lists[-1][1] += 1
            self.out.append("\n" + "    " * (len(self.lists) - 1) + (f"{self.lists[-1][1]}. " if self.lists[-1][0] == "ol" else "- "))
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag in ("del", "s", "strike"):
            self.out.append("~~")
        elif tag == "a":
            self.href = a.get("href")
            self.out.append("[")
        elif tag == "img" and a.get("src", "").startswith("http"):
            self.out.append(f"![{a.get('alt', '')}]({a['src']})")
        elif tag == "pre":
            self.pre = True
            self.out.append("\n\n```\n")
        elif tag == "code" and not self.pre:
            self.out.append("`")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif re.fullmatch(r"h[1-6]", tag) and self.held:
            heading = " ".join(self._release().replace("**", "").split())    # released first: that puts the outer buffer back
            self.out.append(heading + "\n\n")
        elif tag in ("td", "th") and self.tables and self.held:
            row = self.tables[-1][-1]
            span = row.pop()
            row += [re.sub(r"\s*\n\s*", " ", self._release()).strip()] + [""] * (span - 1)
        elif tag == "table" and self.tables and self.held:
            self._release()
            self.out.append("\n\n" + _table(self.tables.pop()) + "\n\n")
        elif tag == "blockquote" and self.held:
            quoted = re.sub(r"\n{3,}", "\n\n", self._release()).strip()
            self.out.append("\n\n" + "\n".join((">" + (" " + l if l.strip() else "")) for l in quoted.split("\n")) + "\n\n")
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            self.out.append("" if self.lists else "\n\n")      # a nested list closing leaves no blank line in the outer one
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag == "dt":
            self.out.append("**\n\n")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag in ("del", "s", "strike"):
            self.out.append("~~")
        elif tag == "a":
            self.out.append(f"]({self.href})" if self.href else "]")
            self.href = None
        elif tag == "pre":
            self.pre = False
            self.out.append("\n```\n\n")
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag in ("p", "div"):
            self.out.append("\n\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if not self.skip:
            self.out.append(data if self.pre else re.sub(r"\s+", " ", data))


def html_to_md(html: str) -> str:
    h = _HTML()
    h.feed(html)
    h.close()
    while h.held:                       # unclosed tags: nothing collected is lost
        h.out = h.held.pop() + h.out
    text = "".join(h.out)
    text = re.sub(r"\*\*(\s*)([^*\n]+?)(\s*)\*\*", r"\1**\2**\3", text)      # the markers hug the words
    text = re.sub(r"(?<![*\w])\*( +)([^*\n]+?)\*(?!\*)", r"\1*\2*", text)
    def clean(line):                    # one space between words; two at the end of a line are a line break and stay
        if line.startswith("|"):
            return line
        brk = "  " if re.search(r"\S  $", line) else ""
        return re.sub(r"(?<=\S) {2,}(?=\S)", " ", line.rstrip()) + brk

    parts = text.split("```")           # code blocks are left exactly as they are
    text = "```".join("\n".join(clean(l) for l in part.split("\n")) if n % 2 == 0 else part for n, part in enumerate(parts))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    title = " ".join(h.title.split())
    if title and not re.search(r"^# ", text, re.M):
        text = f"# {title}\n\n{text}"
    return text


def _epub(p: Path) -> str:
    """Chapters in reading order (the book's own spine), not in the order they sit in the file."""
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        pages = [n for n in names if n.lower().endswith((".xhtml", ".html", ".htm"))]
        try:
            opf = next(el.get("full-path") for el in ET.fromstring(z.read("META-INF/container.xml")).iter() if el.get("full-path"))
            pkg = ET.fromstring(z.read(opf))
            items = {el.get("id"): el.get("href") for el in pkg.iter() if el.tag.endswith("}item")}
            spine = [posixpath.normpath(posixpath.join(posixpath.dirname(opf), items[el.get("idref")].split("#")[0]))
                     for el in pkg.iter() if el.tag.endswith("}itemref") and el.get("idref") in items]
            pages = [n for n in spine if n in names] or pages
        except Exception:
            pass
        chapters = [html_to_md(z.read(n).decode("utf-8", "replace")) for n in pages]
    return f"# {p.stem}\n\n" + "\n\n".join(c for c in chapters if c)


def _ipynb(p: Path) -> str:
    out = []
    for c in json.loads(p.read_text("utf-8")).get("cells", []):
        src = "".join(c.get("source", []))
        out.append(src if c.get("cell_type") == "markdown" else f"```python\n{src}\n```")
    return "\n\n".join(out)


# ---- RTF and OpenDocument -------------------------------------------------------------------------
# Both were read by the earlier MeetingNoter app through extra packages; here they are read with
# the standard library so the worker stays small.
_RTF_DEST = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "footnote", "generator", "themedata",
             "datastore", "object", "xmlnstbl", "listtable", "listoverridetable", "rsidtbl", "latentstyles", "mmathPr"}
_RTF_CHAR = {"emdash": "\u2014", "endash": "\u2013", "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c",
             "rdblquote": "\u201d", "bullet": "\u2022", "tab": " ", "line": "\n"}
_RTF_TOKEN = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])|([{}])|[\r\n]+|([^\\{}\r\n]+)")


def rtf_to_md(rtf: str) -> str:
    """Markdown from RTF: paragraphs, headings (from the heading styles or outline levels), list
    items, tables, bold and italic. Control words are dropped, \\'hh and \\uN decoded."""
    heads = {int(m.group(1)): int(m.group(2)) for m in re.finditer(r"\{[^{}]*?\\s(\d+)(?!\d)[^{}]*?[Hh]eading (\d)\s*;\}", rtf)}
    blocks, rows, row, runs = [], [], [], []
    st = {"skip": False, "uc": 1, "b": False, "i": False, "cap": False}     # restored when a group closes
    stack, pending, marker_text = [], 0, []
    para = {"level": 0, "marker": None, "intbl": False}

    def end_table():
        if rows:
            blocks.append(("raw", _table(rows)))
            rows.clear()

    def end_para():
        text = _inline(runs)
        runs.clear()
        if not row:
            end_table()                 # a paragraph after the last row: the table is complete
        if not text.strip():
            return
        if para["level"]:
            blocks.append(("h", para["level"], re.sub(r"\*+", "", text)))
        elif para["marker"] or text.lstrip().startswith("\u2022"):
            blocks.append(("li", 0, para["marker"] == "1.", text.lstrip().lstrip("\u2022")))
        else:
            blocks.append(("p", text))
        para["marker"] = None

    def emit(text):
        (marker_text if st["cap"] else runs).append(text if st["cap"] else (text, st["b"], st["i"]))

    for m in _RTF_TOKEN.finditer(rtf):
        word, arg, hexv, sym, brace, text = m.groups()
        if brace == "{":
            stack.append(dict(st))
        elif brace == "}":
            if stack:
                was = st["cap"]
                st = stack.pop()
                if was and not st["cap"]:           # the list marker group has closed: bullet or number
                    para["marker"] = "1." if re.search(r"\d", "".join(marker_text)) else "-"
                    marker_text.clear()
        elif sym is not None:
            if sym == "*":
                st["skip"] = True                  # {\*\something ...} is a destination a reader may ignore
            elif not st["skip"] and sym in "{}\\":
                emit(sym)
            elif not st["skip"] and sym == "~":
                emit(" ")
        elif st["skip"]:
            continue
        elif word:
            if word in ("listtext", "pntext"):
                st["cap"] = True
            elif word in _RTF_DEST:
                st["skip"] = True
            elif word in ("par", "sect", "page"):
                if para["intbl"]:
                    emit("\n")                      # a new paragraph inside a table cell
                else:
                    end_para()
            elif word == "cell":
                row.append(_inline(runs).strip().replace("\n", "<br>"))
                runs.clear()
            elif word == "row":
                rows.append(list(row))
                row.clear()
            elif word in _RTF_CHAR:
                emit(_RTF_CHAR[word])
            elif word == "pard":
                para.update(level=0, intbl=False)
            elif word == "intbl":
                para["intbl"] = True
            elif word == "plain":
                st["b"] = st["i"] = False
            elif word in ("b", "i"):
                st[word] = arg != "0"
            elif word == "s" and arg and int(arg) in heads:
                para["level"] = heads[int(arg)]
            elif word == "outlinelevel" and arg and int(arg) < 9:
                para["level"] = int(arg) + 1
            elif word == "uc":
                st["uc"] = int(arg or 1)
            elif word == "u" and arg:
                n = int(arg)
                emit(chr(n + 65536 if n < 0 else n))
                pending = st["uc"]                  # the fallback characters after \uN are not text
        elif hexv:
            if pending:
                pending -= 1
            else:
                emit(bytes.fromhex(hexv).decode("cp1252", "replace"))
        elif text:
            if pending:
                text, pending = text[pending:], max(0, pending - len(text))
            if text:
                emit(text)
    if row:
        rows.append(list(row))
    end_para()
    end_table()
    return _render(blocks)


def _odt(p: Path) -> str:
    T = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    TB = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    ST = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
    FO = "{urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0}"
    XL = "{http://www.w3.org/1999/xlink}"
    with zipfile.ZipFile(p) as z:
        root = ET.fromstring(z.read("content.xml"))
    fmt = {}                                    # text style -> (bold, italic)
    for s in root.iter(f"{ST}style"):
        tp = s.find(f"{ST}text-properties")
        if tp is not None:
            fmt[s.get(f"{ST}name")] = (tp.get(f"{FO}font-weight") == "bold", tp.get(f"{FO}font-style") == "italic")

    def runs(el, b=False, i=False, href=None, out=None):
        out = [] if out is None else out
        if el.text:
            out.append((el.text, b, i, href))
        for c in el:
            if c.tag == f"{T}span":
                sb, si = fmt.get(c.get(f"{T}style-name"), (False, False))
                runs(c, b or sb, i or si, href, out)
            elif c.tag == f"{T}a":
                runs(c, b, i, c.get(f"{XL}href") or href, out)
            elif c.tag == f"{T}line-break":
                out.append(("\n", b, i, href))
            elif c.tag in (f"{T}tab", f"{T}s"):
                out.append((" ", b, i, href))
            elif c.tag != f"{T}note":             # footnotes are left out of the running text
                runs(c, b, i, href, out)
            if c.tail:
                out.append((c.tail, b, i, href))
        return out

    blocks = []

    def walk(el, depth=0, in_list=False):
        for child in el:
            if child.tag == f"{T}h":
                if _plain(runs(child)):
                    blocks.append(("h", int(child.get(f"{T}outline-level") or 1), _plain(runs(child))))
            elif child.tag == f"{T}p":
                text = _inline(runs(child))
                if text.strip():
                    blocks.append(("li", depth, False, text) if in_list else ("p", text))
            elif child.tag == f"{T}list":
                for item in child.findall(f"{T}list-item") + child.findall(f"{T}list-header"):
                    walk(item, depth + 1 if in_list else 0, True)
            elif child.tag == f"{TB}table":
                rows = [[" ".join(_inline(runs(par)).strip() for par in c.iter(f"{T}p")).strip() for c in r.findall(f"{TB}table-cell")]
                        for r in child.iter(f"{TB}table-row")]
                if _table(rows):
                    blocks.append(("raw", _table(rows)))
            else:
                walk(child, depth, in_list)

    walk(root)
    return _render(blocks)


def to_markdown(path: Path) -> str:
    ext = path.suffix.lower()
    read = lambda: path.read_text("utf-8", errors="replace")
    if ext in (".md", ".markdown", ".txt", ".vtt", ".srt", ""):
        return read()
    if ext == ".pdf":
        return _pdf(path)
    if ext == ".docx":
        return _docx(path)
    if ext == ".pptx":
        return _pptx(path)
    if ext == ".xlsx":
        return _xlsx(path)
    if ext in (".html", ".htm"):
        return html_to_md(read())
    if ext in (".csv", ".tsv"):
        rows = list(csv.reader(io.StringIO(read()), delimiter="\t" if ext == ".tsv" else ","))
        return f"# {path.stem}\n\n" + _table(rows[:2000])
    if ext == ".json":
        return f"# {path.name}\n\n```json\n{read()}\n```"
    if ext == ".ipynb":
        return _ipynb(path)
    if ext == ".epub":
        return _epub(path)
    if ext == ".rtf":
        return rtf_to_md(path.read_bytes().decode("latin-1"))
    if ext == ".odt":
        return _odt(path)
    if ext in CODE:
        return f"# {path.name}\n\n```{ext[1:]}\n{read()}\n```"
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise ValueError(f"{ext} is not supported by the built-in converter. Supported: {', '.join(SUPPORTED)}. "
                         "Installing the optional 'markitdown' package adds more formats.")
    return MarkItDown().convert(str(path)).text_content


def save_markdown(source: Path, markdown: str) -> Path:
    out = source.with_suffix(".md")
    n = 1
    while out.exists():
        out = source.with_name(f"{source.stem} ({n}).md")
        n += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, "utf-8")
    return out

"""One-off edit script for version 0.7.0: makes the PDF, converter and TwinMind pages accept
dropped files through the SDK's M.accept. Kept as a record of what was changed; it refuses to
run twice (every replacement asserts its old text is still there)."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def edit(path, pairs):
    p = ROOT / path
    s = p.read_text("utf-8")
    for old, new in pairs:
        assert old in s, (path, old[:70])
        s = s.replace(old, new, 1)
    p.write_text(s, "utf-8")


edit("apps/pdf-reader/ui/index.html", [
    ("function open(p) {", "function open(p, name) {"),
    (r"$('#name').textContent = p.split(/[\\/]/).pop(); $('#name').title = p;",
     r"$('#name').textContent = name || p.split(/[\\/]/).pop(); $('#name').title = name || p;"),
    ("Pick a PDF on the left.", "Pick a PDF on the left, or drop one anywhere in this window."),
    ("M.ready.then(async () => {\n  const start = M.param('path');",
     "M.accept = { exts: ['.pdf'], open };\nM.ready.then(async () => {\n  const start = M.param('path'), dropped = M.param('name');"),
    ("if (start) { fb.select(start); open(start); }", "if (start) { if (!dropped) fb.select(start); open(start, dropped); }"),
    ("start: start ? start.replace", "start: start && !dropped ? start.replace"),
    # the app's own page shows around the viewer, so a file dragged in over any edge is seen
    # by the page before the embedded viewer can take it
    ("  iframe { flex: 1; width: 100%; border: 0; min-height: 70vh; background: #fff; }",
     "  iframe { flex: 1; border: 0; min-height: 70vh; background: #fff; margin: 0 10px 10px; border-radius: 8px; box-shadow: 0 0 0 1px var(--line); }"),
])

edit("apps/to-markdown/ui/index.html", [
    ("async function convertPath(p) {\n  const t0 = performance.now(); $('#stat').textContent = 'Converting…';\n"
     "  try { loaded(await M.api('/api/convert?path=' + encodeURIComponent(p)), Math.round(performance.now() - t0)); } catch (e) { M.toast(e.message, 6000); }\n}",
     "// name is given for a dropped file: the path is then a temporary copy, so Save writes to Downloads, not beside it\n"
     "async function convertPath(p, name) {\n  const t0 = performance.now(); $('#stat').textContent = 'Converting…';\n  try {\n"
     "    const r = await M.api('/api/convert?path=' + encodeURIComponent(p));\n"
     "    loaded(name ? { ...r, name, path: null, dir: null } : r, Math.round(performance.now() - t0));\n"
     "  } catch (e) { M.toast(e.message, 6000); }\n}"),
    ("async function convertFile(file) {\n  const t0 = performance.now();\n  try {\n"
     "    const up = await M.api('/api/upload?name=' + encodeURIComponent(file.name), { method: 'POST', body: file });\n"
     "    const r = await M.api('/api/convert?path=' + encodeURIComponent(up.path));\n"
     "    loaded({ ...r, name: file.name, path: null, dir: null }, Math.round(performance.now() - t0));\n"
     "  } catch (e) { M.toast(e.message, 6000); }\n}\n", ""),
    ("$('#pick').onchange = (e) => e.target.files[0] && convertFile(e.target.files[0]);\n"
     "['dragover', 'dragenter'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));\n"
     "['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));\n"
     "drop.addEventListener('drop', (e) => e.dataTransfer.files[0] && convertFile(e.dataTransfer.files[0]));",
     "$('#pick').onchange = (e) => e.target.files[0] && M.openFile(e.target.files[0]);\n"
     "M.accept = { exts: null, open: convertPath };   // anything dropped anywhere in this window is converted here"),
    ("Drop a file here, or click to choose one", "Drop a file anywhere in this window, or click to choose one"),
    ("  const start = M.param('path');\n  browser = await M.browser($('#files'), { onPick: convertPath, start: start ? start.replace",
     "  const start = M.param('path'), dropped = M.param('name');\n"
     "  browser = await M.browser($('#files'), { onPick: (p) => convertPath(p), start: start && !dropped ? start.replace"),
    ("if (start) { browser.select(start); convertPath(start); }", "if (start) { if (!dropped) browser.select(start); convertPath(start, dropped); }"),
])

edit("apps/twinmind/ui/index.html", [
    (r"  const pick = (p) => {" "\n" r"    path = p; const name = p.split(/[\\/]/).pop();",
     r"  const pick = (p, shown) => {" "\n" r"    path = p; const name = shown || p.split(/[\\/]/).pop();"),
    ("  const start = M.param('path');",
     "  const exts = [...st.audio_exts, '.txt', '.md', '.vtt', '.srt', '.docx', '.rtf', '.odt', '.pdf', '.html'];\n"
     "  M.accept = { exts, open: pick };   // a recording or transcript dropped anywhere in this window\n"
     "  const start = M.param('path'), dropped = M.param('name');"),
    ("{ exts: [...st.audio_exts, '.txt', '.md', '.vtt', '.srt', '.docx', '.rtf', '.odt', '.pdf', '.html'], onPick: pick, start: start ? start.replace",
     "{ exts, onPick: (p) => pick(p), start: start && !dropped ? start.replace"),
    ("if (start) { fb.select(start); pick(start); }", "if (start) { if (!dropped) fb.select(start); pick(start, dropped); }"),
    ("Pick a recording or a transcript on the left</div>", "Pick a recording or a transcript on the left, or drop one here</div>"),
])
print("edited")

"""App builder: a prompt becomes a manifest draft, the draft becomes an installed app.

The draft is produced by reading the prompt for what a manifest can express: name,
connectors (Dropbox, local folders), capabilities it needs, output format. A capability is
added only when the prompt calls for it; most apps need none. You edit the draft before
creating it. The app starts on the generic workspace UI, with a SPEC.md carrying the original
prompt so its own UI and worker can be written against it later.
"""
import json
import re

from . import paths

NEEDS = [
    (r"diari[sz]|who (spoke|said)|speaker", "diarization"),
    (r"whisper|wispr|transcri|speech.to.text|audio|recording|meeting", "transcription"),
    (r"summar|rewrite|refine|chat|question|answer|ask|explain|extract|action items", "assistant"),
    (r"semantic|similar|search across|embedding", "embeddings"),
]
CATEGORIES = [(r"\bmeetings?\b|\bcalls?\b|transcri", "Meeting Intelligence", "mic"),
              (r"\bnotes?\b|journal|research|knowledge", "Knowledge", "book"),
              (r"\bpdfs?\b|\bdocs?\b|document|markdown|convert", "Documents", "doc"),
              (r"\bcode\b|\brepos?\b|\bgit\b", "Developer", "code"),
              (r"finance|budget|expense|invoice", "Finance", "coin")]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:40] or "app"


def draft(prompt: str) -> dict:
    p = prompt.lower()
    m = re.search(r"(?:called|named|name it|name is)\s+[\"']?([A-Za-z0-9][\w \-]{1,40}?)[\"']?(?=[,.;\n]|\s+(?:that|which|to|for|and|it)\b|$)", prompt, re.I)
    name = m.group(1).strip() if m else " ".join(re.findall(r"[A-Za-z0-9]+", prompt)[:4]).title() or "New App"
    category, icon = "Custom", "app"
    for pat, cat, ic in CATEGORIES:
        if re.search(pat, p):
            category, icon = cat, ic
            break

    connectors = []
    if "dropbox" in p:
        # a folder path is one unbroken token (Research/Papers); quote it if it contains spaces
        sub = re.search(r"dropbox[^.\n]*?(?:folder|path|under|in|at)\s+(?:\"([^\"]+)\"|'([^']+)'|([\w\-]+(?:[/\\][\w\-]+)*))", prompt, re.I)
        sub = next((g for g in sub.groups() if g), None) if sub else None
        connectors.append({"type": "dropbox", "path": (sub.strip().replace("\\", "/") if sub else f"Mitra/{name}"), "mode": "readwrite"})
    for path in re.findall(r"[A-Za-z]:\\[^\s,;\"']+|~/[^\s,;\"']+", prompt):
        connectors.append({"type": "folder", "path": path, "mode": "readwrite"})

    return {"id": slug(name), "name": name, "glyph": icon, "category": category, "version": "0.1.0",
            "description": prompt.strip().split("\n")[0][:160], "connectors": connectors, "uses": ["convert"],
            "needs": [cap for pat, cap in NEEDS if re.search(pat, p)],
            "output": {"format": "json" if re.search(r"\bjson\b", p) else "markdown"}, "prompt": prompt.strip()}


def create(manifest: dict, existing: set) -> str:
    for k in ("id", "name"):
        if not manifest.get(k):
            raise ValueError(f"Manifest needs '{k}'.")
    manifest["id"] = slug(manifest["id"])
    if manifest["id"] in existing:
        raise ValueError(f"An app with id '{manifest['id']}' already exists.")
    d = paths.USER_APPS / manifest["id"]
    d.mkdir(parents=True, exist_ok=False)
    (d / "mitra.app.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), "utf-8")
    (d / "SPEC.md").write_text(
        f"# {manifest['name']}\n\n## Original prompt\n\n{manifest.get('prompt', '')}\n\n"
        "## Status\n\nRunning on the generic workspace UI. To give it its own interface, add `ui/index.html` "
        "(include `/static/sdk.js`) and, for its own logic, `worker.py` exposing `ROUTES`. "
        "See APP_SPEC.md in the mitra-marketplace folder.\n", "utf-8")
    for c in manifest.get("connectors", []):
        if c.get("mode") == "readwrite":
            p = paths.resolve_connector(c)
            if p:
                p.mkdir(parents=True, exist_ok=True)
    return str(d)

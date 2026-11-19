"""Export the conversation in which Mitra Marketplace was built, with private details taken out.

    python logs/scripts/export_conversation.py <session.jsonl> <out.md>

What is kept: every message the owner typed, every reply the assistant wrote, and one line for each
action the assistant took (which tool, and its own short description of what it was doing).

What is left out, because it is where the private material is: the output of every tool (file
listings, file contents, transcripts, logs), the assistant's private reasoning, attached images and
files, and notices the system inserted.

What is replaced in the text that is kept:
  email addresses, phone numbers, the owner's surname and Windows user name;
  the names of recordings, and anything under the recordings folder;
  every client, every person and every meeting title found in the owner's meeting archive
  (read from the library index on this machine at export time, so none of them is written here);
  any run of Devanagari text (transcript lines).
The same lists are then searched for in the result, and the export fails if any is still there.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workers"))
from mitra_workers import library, paths  # noqa: E402

KEEP_PEOPLE = {"Anirudh"}                 # the owner's first name is the repository's name already
# Names that came up only in file names or in passing are in the owner's own file, not here:
# ~/.mitra/twinmind/redact_extra.json  {"people": [...], "clients": [...], "titles": [...], "surname": "...", "user": "..."}
_EXTRA = json.loads((paths.HOME / "twinmind" / "redact_extra.json").read_text("utf-8")) if (paths.HOME / "twinmind" / "redact_extra.json").is_file() else {}
EXTRA_PEOPLE, EXTRA_CLIENTS, EXTRA_TITLES = _EXTRA.get("people", []), _EXTRA.get("clients", []), _EXTRA.get("titles", [])


def lists():
    entries = library.index(paths.HOME / "twinmind" / "nothing-here", refresh=False)
    people, clients, titles = set(EXTRA_PEOPLE), set(EXTRA_CLIENTS), set(EXTRA_TITLES)
    for e in entries:
        if e["src"] != "archive":
            continue
        titles.add(e["title"])
        if e["project"]:
            clients.add(e["project"])
        for s in e["speakers"]:
            for part in [s] + s.split():
                if re.fullmatch(r"[A-Z][A-Za-z.'-]{2,}(?: [A-Z][A-Za-z.'-]+)*", part) and part not in KEEP_PEOPLE and not part.startswith("Speaker"):
                    people.add(part)
    names = paths.HOME / "twinmind" / "project_names.json"
    if names.is_file():
        clients.update(json.loads(names.read_text("utf-8")).values())
    common = {"The", "And", "For", "Team", "Client", "Speech", "Speaker", "Unknown", "User", "Host", "Guest", "Call", "Meeting", "Other", "Others", "You",
              "Sam", "Priya", "Dana", "Dev", "Amazon", "IVR", "Microsoft", "Google", "Apple", "No", "Shri"}
    people = {p for p in people if p not in common and len(p) > 2}
    clients = {c for c in clients if c not in common and len(c) > 1}
    titles = {t for t in titles if len(t) >= 12 and t not in ("Meeting Discussion",)}
    return people, clients, titles


def alternation(words, flags=0, bound=True):
    body = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile((r"(?<![\w])(?:" + body + r")(?![\w])") if bound else "(?:" + body + ")", flags)


PEOPLE, CLIENTS, TITLES = lists()
RX_TITLES, RX_PEOPLE, RX_CLIENTS = alternation(TITLES, re.I, bound=False), alternation(PEOPLE), alternation(CLIENTS)
RX = [
    (re.compile(r"<system-reminder>.*?</system-reminder>", re.S), ""),
    (re.compile(r"<task-notification>.*?</task-notification>", re.S), ""),
    (re.compile(r"</?pasted_content[^>]*>"), ""),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\+91[\s-]?\d{10}|(?<!\d)[6-9]\d{9}(?!\d)"), "[phone]"),
    (re.compile(r"E:[\\/]+Conversations & Meeting Transcripts[^\n\"'`]*?\.(?:m4a|mp3|wav|md|txt)", re.I), r"E:\\Conversations & Meeting Transcripts\\[recording]"),
    (re.compile(r"[\w +&().,'-]{3,80}\.(?:m4a|mp3)\b"), "[recording]"),
    (re.compile(r"[ऀ-ॿ][ऀ-ॿ\s।,.?!-]*"), "[transcript text] "),
    (re.compile(_EXTRA.get("surname") or r"(?!x)x", re.I), "[surname]"),
    (re.compile(r"\b" + re.escape(_EXTRA.get("user") or "\0") + r"\b"), "<you>"),
]


def clean(text: str) -> str:
    for rx, to in RX:
        text = rx.sub(to, text)
    text = RX_TITLES.sub("[meeting title]", text)
    text = RX_CLIENTS.sub("[client]", text)
    text = RX_PEOPLE.sub("[person]", text)
    return re.sub(r"\n{4,}", "\n\n\n", text).strip()


def action(block: dict) -> str:
    name, inp = block.get("name", "tool"), block.get("input") or {}
    short = {"Bash": "ran a shell command", "PowerShell": "ran a PowerShell command", "Write": "wrote a file", "Edit": "edited a file", "Read": "read a file",
             "Grep": "searched file contents", "Glob": "looked for files", "Agent": "started a helper agent", "WebSearch": "searched the web",
             "WebFetch": "read a web page", "Monitor": "watched a background job", "ToolSearch": "loaded a tool", "SendUserFile": "sent a file to the owner"}.get(name)
    if name.startswith("mcp__Claude_Browser") or name.startswith("mcp__claude-in-chrome"):
        short = "used the browser"
    if name.startswith("mcp__ccd_turn") or name in ("TaskStop",):
        return ""
    what = inp.get("description") or inp.get("query") or ""
    if name in ("Write", "Edit", "Read") and inp.get("file_path"):
        what = Path(str(inp["file_path"]).replace("\\", "/")).name
    if name == "WebFetch":
        what = inp.get("url", "")
    return f"- *{short or name}*" + (f": {clean(str(what))[:200]}" if what else "")


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    parts, stats = [], {"owner": 0, "assistant": 0, "actions": 0, "outputs_left_out": 0}
    last_role, day = None, ""
    for line in src.open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "queue-operation" and d.get("operation") == "remove" and d.get("reason") == "absorbed_mid_turn" and d.get("content") and not str(d["content"]).lstrip().startswith("<"):
            # a message the owner sent while the assistant was in the middle of working
            parts.append(f"\n### Owner (sent while the assistant was working)\n\n{clean(str(d['content']))}\n")
            stats["owner"] += 1
            last_role = "user"
            continue
        if d.get("isSidechain") or d.get("isMeta") or d.get("type") not in ("user", "assistant"):
            continue
        content = (d.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        role = d["type"]
        texts, acts = [], []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                texts.append(b.get("text") or "")
            elif b.get("type") == "tool_use":
                a = action(b)
                if a:
                    acts.append(a)
            elif b.get("type") == "tool_result":
                stats["outputs_left_out"] += 1
        text = clean("\n\n".join(texts))
        if role == "user" and (not text or text.startswith("[Request interrupted") or text.startswith("Caveat:") or text.startswith("<")):
            if not text or not d.get("isCompactSummary"):
                continue
        stamp = (d.get("timestamp") or "")[:10]
        if stamp and stamp != day:
            day = stamp
            parts.append(f"\n---\n\n## {day}\n")
            last_role = None
        if role == "user":
            summary = d.get("isCompactSummary") or text.startswith("This session is being continued from a previous conversation")
            head = "### Summary carried over" if summary else "### Owner"
            note = "\n*Written by the assistant when the conversation grew too long to keep whole; it stands in for the earlier part.*\n" if summary else ""
            parts.append(f"\n{head}\n{note}\n{text}\n")
            stats["owner"] += 0 if summary else 1
            last_role = "user"
        else:
            if text:
                if last_role != "assistant":
                    parts.append("\n### Assistant\n")
                parts.append(f"\n{text}\n")
                stats["assistant"] += 1
                last_role = "assistant"
            if acts:
                if last_role != "assistant":
                    parts.append("\n### Assistant\n")
                    last_role = "assistant"
                parts.append("\n" + "\n".join(acts) + "\n")
                stats["actions"] += len(acts)
    head = f"""# Building Mitra Marketplace: the conversation

The working conversation between the owner and the assistant (Claude) in which this project was built, from 2026-11-11 on.

**What is here:** every message the owner typed ({stats['owner']}), every reply the assistant wrote ({stats['assistant']}), and one line for each action the assistant took ({stats['actions']}).

**What is left out:** the output of the tools ({stats['outputs_left_out']} results: file listings, file contents, logs, transcripts), the assistant's private reasoning, attachments, and notices inserted by the system. That is where the private material was.

**What is replaced:** email addresses, phone numbers, the owner's surname and Windows user name, the names of recordings, and every client, person and meeting title found in the owner's meeting archive, shown as `[client]`, `[person]`, `[meeting title]`, `[recording]`, `[email]`, `[phone]`. Lines of transcript are shown as `[transcript text]`. Made by `logs/scripts/export_conversation.py`, which also checks the result for anything on those lists.
"""
    body = head + "".join(parts)
    # the check: nothing on the lists may be left
    left = sorted(set(RX_PEOPLE.findall(body)) | set(RX_CLIENTS.findall(body)) | set(m.lower() for m in RX_TITLES.findall(body)))
    other = [n for n, rx in (("email", RX[3][0]), ("phone", RX[4][0]), ("devanagari", re.compile("[ऀ-ॿ]")), ("surname", RX[8][0]), ("user name", RX[9][0]))
             if rx.search(body)]
    if left or other:
        sys.exit(f"NOT WRITTEN: still present: {left[:20]} {other}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, "utf-8")
    print(json.dumps({**stats, "chars": len(body), "people_on_list": len(PEOPLE), "clients_on_list": len(CLIENTS), "titles_on_list": len(TITLES)}))


main()

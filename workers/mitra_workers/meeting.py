"""Meeting understanding: transcript sections in, grounded notes and action items out.

The task contract (prompts, the four-section notes format, the action-item JSON schema, the
output caps, the deterministic merge) is absorbed from APTM / Mitra Ear (mind/prompts.py and
app/aptm/mind.py). The Mitra Ear fine-tune was trained on exactly these prompt strings, so for
the "mind-v1" contract they must not change; a general model gets the same prompts plus a
short reminder of the format.

Nothing here keeps a model in memory: the caller holds one `models.Assistant` for the length
of a meeting and it is unloaded when the block ends.
"""
import json
import re

from . import grounding

NOTES = "Write English meeting notes for this transcript chunk. Use only facts in the chunk."
ACTIONS = "List action items in this transcript chunk as JSON. Only explicit commitments or requests."
TITLE = "Give a 3 to 6 word English title for this transcript chunk."
FORMAT_HINT = ("\nEach point is one full sentence in your own words saying what was discussed, agreed or asked for, with the "
               "names, dates and numbers that were said. Do not copy lines from the transcript and do not start a point with a speaker label. "
               "Skip greetings and thanks."
               "\nReply in exactly this format and nothing else:\nTopic: <what this part of the meeting is about>\nPoints:\n- ...\n"
               "Decisions:\n- ... (write - None if there are none)\nOpen questions:\n- ... (write - None if there are none)")
ACTIONS_HINT = (" owner is the person who will do the task, exactly as named in the transcript. "
                "due is the deadline as spoken, or null.")
ACTIONS_SCHEMA = {
    "type": "object",
    "properties": {"actions": {"type": "array", "maxItems": 8, "items": {
        "type": "object",
        "properties": {"owner": {"type": "string", "maxLength": 40},
                       "task": {"type": "string", "maxLength": 160},
                       "due": {"type": ["string", "null"], "maxLength": 40}},
        "required": ["owner", "task", "due"]}}},
    "required": ["actions"],
}
# A looping model hits the cap mid-JSON; a capped, unparseable action list is treated as
# "no actions, flagged", never as data.
MAX_TOKENS = {"notes": 320, "actions": 360, "title": 16}
CHUNK_WORDS = 420


def tidy(s: str, limit: int = 70) -> str:
    """A title or topic as plain words: a small model wraps them in ** and quotes, repeats the
    word "Title:", or runs on into a second line."""
    s = (s or "").splitlines()[0] if (s or "").strip() else ""
    s = re.sub(r"[*_`#<>]+", "", s).strip(" \"'“”‘’")
    s = re.sub(r"\bSpeaker \d+(?:['’]s)?\s*:?\s*", "", s)              # "Speaker 1's Discussion on ...": a label is not a title
    s = re.sub(r"(?i)^\s*(?:(?:topic|title)\s*:|(?:meeting|discussion|call) (?:on|about|regarding)\b)\s*", "", s)
    s = re.sub(r"(?i)(?<=\S)\s+(transcript\s+)?title\s*:.*$", "", s)   # "... Transcript Title: "..." said again
    s = s.strip(" \"'“”‘’.:-")
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return s[:1].upper() + s[1:] if s else ""


def said_in(title: str, section: str, need: float = 0.6) -> bool:
    """A title is kept only if most of its words of four letters or more were actually said."""
    words = set(re.findall(r"[a-z]{4,}", title.lower())) - {"meeting", "discussion", "call", "about", "with", "from", "this", "that"}
    low = section.lower()
    return bool(words) and sum(w in low or w.rstrip("s") in low for w in words) / len(words) >= need


def chunk(lines: list[str], max_words: int = CHUNK_WORDS) -> list[str]:
    """Sections of about 420 words, cut on line boundaries (the size the fine-tune was trained on)."""
    out, cur, n = [], [], 0
    for line in lines:
        if not line.strip():
            continue
        cur.append(line.strip())
        n += len(line.split())
        if n >= max_words:
            out.append("\n".join(cur))
            cur, n = [], 0
    if cur:
        out.append("\n".join(cur))
    return out


def parse_notes(text: str) -> dict:
    out = {"topic": "", "points": [], "decisions": [], "open_questions": []}
    key = None
    heads = {"topic": "topic", "points": "points", "decisions": "decisions", "open questions": "open_questions"}
    for line in text.splitlines():
        s = line.strip().strip("*").strip()
        m = re.match(r"^(topic|points|decisions|open questions)\s*:\s*(.*)$", s, re.I)
        if m:
            key = heads[m.group(1).lower()]
            if key == "topic":
                out["topic"] = m.group(2).strip()
            continue
        if key == "topic" and re.match(r"^[-*•]\s+", s):
            key = "points"          # some models go from the topic straight to the bullets, with no "Points:" line
        # Under a heading every line is an item, with or without a bullet: Gemma 3 1B writes its
        # points as plain lines, and dropping those left a correct set of notes empty.
        if key and key != "topic" and s:
            item = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", s).strip()
            item = re.sub(r"^(?:\[[\d:]+\]\s*)?Speaker \d+\s*:\s*", "", item).strip()   # a transcript label echoed onto a note
            if item and item.lower().rstrip(".") != "none":
                out[key].append(item)
    return out


def parse_actions(text: str) -> tuple[list[dict], bool]:
    try:
        d = json.loads(text)
        acts = d.get("actions") if isinstance(d, dict) else None
        if isinstance(acts, list) and all(isinstance(a, dict) for a in acts):
            return acts, True
    except json.JSONDecodeError:
        pass
    # Cut off mid-list by the length cap: the items that were finished are still good.
    whole = []
    for m in re.finditer(r"\{[^{}]*\}", text or ""):
        try:
            a = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(a, dict) and "task" in a:
            whole.append(a)
    return (whole, True) if whole else ([], False)


def understand(assistant, section: str, index: int = 0) -> dict:
    """One section through the model, then through the grounding guards."""
    generic = assistant.p.get("contract", "generic") != "mind-v1"
    user = f"Transcript:\n{section}"
    notes = parse_notes(assistant.chat(user, NOTES + (FORMAT_HINT if generic else ""), MAX_TOKENS["notes"], 0.0)["text"])
    raw = assistant.chat(user, ACTIONS + (ACTIONS_HINT if generic else ""), MAX_TOKENS["actions"], 0.0, ACTIONS_SCHEMA)["text"]
    acts, ok = parse_actions(raw)
    title = tidy(assistant.chat(user, TITLE, MAX_TOKENS["title"], 0.0)["text"], 80) if section else ""
    notes["topic"] = tidy(notes["topic"])
    if not said_in(title, section):
        title = ""             # "Designing for the Future: A Call to Action" for a call about a proposal: invented, not heard
    flags = [] if ok else ["action items: the model's output was not valid JSON, so none were taken from it"]
    for k in ("points", "decisions", "open_questions"):
        notes[k], f = grounding.guard_bullets(notes[k], section, k.replace("_", " ").rstrip("s"))
        flags += f
    if grounding.ungrounded_numbers(notes["topic"], section) or notes["topic"].strip("<>. ").lower() in ("one line", "what this part of the meeting is about"):
        notes["topic"] = ""    # an invented number, or the model echoed the format instead of filling it in
    acts, f = grounding.guard_actions(acts, section)
    return {"index": index, "notes": notes, "actions": acts, "title": title, "flags": flags + f}


def _dup(a: str, seen: list[str], thr: float = 0.8) -> bool:
    ta = set(re.findall(r"[a-z0-9]+", a.lower()))
    for b in seen:
        tb = set(re.findall(r"[a-z0-9]+", b.lower()))
        if ta and tb and len(ta & tb) / len(ta | tb) >= thr:
            return True
    return False


def merge(results: list[dict]) -> dict:
    """Deterministic merge, no generation: sections in time order, near-duplicates removed, each
    item tagged with the section it came from so it can be traced back to the transcript."""
    out = {"topics": [], "points": [], "decisions": [], "open_questions": [], "actions": [], "flags": [], "title": ""}
    seen = {k: [] for k in ("points", "decisions", "open_questions", "actions")}
    for r in results:
        n = r["notes"]
        if n.get("topic") and not _dup(n["topic"], out["topics"]):
            out["topics"].append(n["topic"])
        for k in ("points", "decisions", "open_questions"):
            for b in n[k]:
                if not _dup(b, seen[k]):
                    seen[k].append(b)
                    out[k].append({"text": b, "section": r["index"] + 1})
        for a in r["actions"]:
            if not _dup(a["task"], seen["actions"]):
                seen["actions"].append(a["task"])
                out["actions"].append({**a, "section": r["index"] + 1})
        out["flags"] += [f"section {r['index'] + 1}: {f}" for f in r["flags"]]
        if not out["title"] and len((r.get("title") or "").split()) >= 2:
            out["title"] = r["title"]
    if not out["title"] and out["topics"]:
        out["title"] = out["topics"][0]      # no title that was grounded in what was said: the first topic is
    return out

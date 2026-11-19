"""Grounding guards: nothing a model writes reaches your notes unless the transcript backs it.

Absorbed from APTM / Mitra Ear (app/aptm/mind.py, guard 4.4), with one addition: speech is
transcribed as words ("ninety percent", "the twentieth") while models write digits ("90%",
"20th"), so the source is first expanded with the digit form of every number it spells out.

  - a bullet that states a number the transcript does not contain is dropped
  - an action item's owner must be a name heard in that part of the transcript
  - an action item's due date must be something that was said
Every removal is returned as a flag, so the note can say what was taken out and why.
"""
import re

_NUM = re.compile(r"\b\d[\d,.:]*\d\b|\b\d\b")
_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_ORD = {"first": 1, "second": 2, "third": 3, "fifth": 5, "eighth": 8, "ninth": 9, "twelfth": 12}
_SCALE = {"hundred": 100, "thousand": 1000, "lakh": 100000, "million": 1000000, "crore": 10000000}


def _word_value(w: str):
    w = w.lower()
    if w in _UNITS:
        return _UNITS[w]
    if w in _TENS:
        return _TENS[w]
    if w in _ORD:
        return _ORD[w]
    if w.endswith("ieth") and w[:-4] + "y" in _TENS:      # twentieth, thirtieth
        return _TENS[w[:-4] + "y"]
    if w.endswith("th") and w[:-2] in _UNITS:             # fourth, sixteenth
        return _UNITS[w[:-2]]
    return None


def spoken_numbers(text: str) -> set[str]:
    """Digit forms of the numbers a transcript spells out: 'two hundred' -> 200, 'twenty-fourth' -> 24."""
    out, cur, total, active = set(), 0, 0, False
    for w in re.findall(r"[A-Za-z]+|\S", text.replace("-", " ")) + ["."]:
        v, lw = _word_value(w), w.lower()
        if v is not None:
            cur, active = cur + v, True
        elif lw in _SCALE and active:
            cur = max(cur, 1) * _SCALE[lw]
            if _SCALE[lw] >= 1000:
                total, cur = total + cur, 0
        elif lw == "and" and active:
            continue
        else:
            if active:
                out.add(str(total + cur))
            cur, total, active = 0, 0, False
    return out


def ungrounded_numbers(text: str, source: str) -> list[str]:
    src = source.replace(",", "")
    spoken = spoken_numbers(source)
    bad = []
    for n in _NUM.findall(text):
        plain = n.replace(",", "").rstrip(".:")
        if plain not in src and plain not in spoken:
            bad.append(n)
    return bad


_FLAT = re.compile(r"[a-z0-9ऀ-෿]+")
_SMALL_TALK = {"correct", "thank", "thanks", "you", "okay", "ok", "yes", "yeah", "no", "hello", "hi", "bye", "sorry", "right", "good",
               "evening", "morning", "night", "done", "sure", "fine", "great", "welcome", "please", "so", "very", "much", "and", "the"}


def flat(text: str) -> str:
    return " ".join(_FLAT.findall(text.lower()))


def copied(text: str, flat_source: str) -> bool:
    """True when `text` is the transcript's own wording pasted in: every sentence of it that is
    three words or longer appears word for word in the transcript. A summary never does that."""
    parts = [flat(s) for s in re.split(r"(?<=[.?!])\s+", text)]
    parts = [p for p in parts if len(p.split()) >= 3]
    return bool(parts) and all(p in flat_source for p in parts)


_SPOKEN = re.compile(r"\b(I|I'm|I'll|I've|me|my|you|your|you're|we|we'll|our|us)\b")


def pasted(text: str, flat_source: str) -> bool:
    """A transcript line offered as a note or a task: copied word for word, and either several
    sentences or said in the first or second person ("I will think about it and tell you").
    One sentence in the third person that happens to match the transcript ("The release stays
    on the twentieth") is a fair note and is kept."""
    if not copied(text, flat_source):
        return False
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s.strip()]
    return len(sentences) > 1 or bool(_SPOKEN.search(text))


def guard_bullets(bullets: list[str], source: str, label: str = "bullet") -> tuple[list[str], list[str]]:
    keep, flags = [], []
    flat_source = flat(re.sub(r"(?m)^(?:\[[\d:]+\]\s*)?Speaker \d+:\s*", "", source))
    for b in bullets:
        bad = ungrounded_numbers(b, source)
        words = re.findall(r"[A-Za-z0-9ऀ-෿]+", b)
        if "(write" in b.lower() or re.fullmatch(r"[\W.…]*", b):
            continue                     # the format's own placeholder, echoed back
        if len(words) < 3 or all(w.lower() in _SMALL_TALK for w in words):
            flags.append(f"{label} removed: \"{b[:70]}\" says nothing")
            continue
        if pasted(b, flat_source):
            flags.append(f"{label} removed: \"{b[:70]}\" is a line copied from the transcript, not a note")
            continue
        if bad:
            flags.append(f"{label} removed: \"{b[:70]}\" states {', '.join(bad)}, which the transcript does not contain")
        else:
            keep.append(b)
    return keep, flags


def _heard(form: str, low_source: str) -> bool:
    return re.search(r"(?<![\wऀ-෿])" + re.escape(form.lower()) + r"(?![\wऀ-෿])", low_source) is not None


def guard_actions(actions: list[dict], source: str) -> tuple[list[dict], list[str]]:
    """Keep an action only if its task is grounded; blank an owner or due date that was never said."""
    low, out, flags = source.lower(), [], []
    for a in actions:
        task = str(a.get("task") or "").strip()
        owner = str(a.get("owner") or "").strip()
        due = a.get("due")
        task = re.sub(r"^(?:\[[\d:]+\]\s*)?Speaker \d+\s*:\s*", "", task).strip()
        if not task:
            continue
        said_words = flat(task).split()
        if len(said_words) < 2 or all(w in _SMALL_TALK for w in said_words):
            # "Correct", "Thank you": a small model fills the list with whatever was last said
            flags.append(f"action removed: \"{task[:60]}\" is not a task")
            continue
        spoken = re.sub(r"(?m)^(?:\[[\d:]+\]\s*)?Speaker \d+:\s*", "", source)
        whole = {flat(s) for s in re.split(r"(?<=[.?!])\s+|\n", spoken)}
        parts = [p for p in (flat(s) for s in re.split(r"(?<=[.?!])\s+", task)) if len(p.split()) >= 3]
        if (len(said_words) >= 5 and pasted(task, flat(spoken))) or (parts and all(p in whole for p in parts)):
            # what someone said, pasted in whole ("You tell the client, we will be sharing it by
            # Wednesday", "Last time, Prachi sent it correctly") is not a task stated; a phrase
            # lifted from inside a sentence ("recreate the design") is fine
            flags.append(f"action removed: \"{task[:60]}\" is a line copied from the transcript, not a task")
            continue
        if ungrounded_numbers(task, source):
            flags.append(f"action removed: \"{task[:60]}\" states a number the transcript does not contain")
            continue
        # the task must share real words with the transcript, not just be plausible
        words = {w for w in re.findall(r"[a-z]{4,}", task.lower())}
        if words and len([w for w in words if w in low]) / len(words) < 0.5:
            flags.append(f"action removed: \"{task[:60]}\" is not supported by the transcript")
            continue
        # An owner or a date must not only have been said somewhere: it must have been said in a
        # line that is about this task. Otherwise a small model pairs any name with any deadline.
        lines = [l.lower() for l in source.splitlines() if l.strip()] or [low]
        about = lambda l: any(w in l for w in words) if words else True
        if owner and not _heard(owner, low):
            flags.append(f"owner \"{owner}\" was not heard in this part of the transcript; left unassigned")
            owner = ""
        elif owner and not any(_heard(owner, l) and about(l) for l in lines):
            flags.append(f"owner \"{owner}\" was never linked to \"{task[:40]}\" in the transcript; left unassigned")
            owner = ""
        if due and str(due).lower() not in low:
            flags.append(f"due date \"{due}\" was not said; removed")
            due = None
        elif due and not any(str(due).lower() in l and about(l) for l in lines):
            flags.append(f"due date \"{due}\" was said, but not about \"{task[:40]}\"; removed")
            due = None
        out.append({"owner": owner, "task": task, "due": due})
    return out, flags

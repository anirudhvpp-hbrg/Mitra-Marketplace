"""Extractive gist: two or three sentences copied word for word from a meeting, so a list row
or the top of a note can say what the meeting was about without inventing anything.

Absorbed from APTM / Mitra Ear (app/aptm/gist.py, 2026-10). No model and no memory cost: the
turns are split into sentences, fillers and very short lines are skipped, and each candidate
is scored by TF-IDF cosine similarity to the meeting's centroid (how central it is to
everything said). The top sentences, minus near-duplicates, come back in transcript order.
The output is a pure function of the text, so the same meeting always gets the same gist.

Indic scripts: words are runs of `\\w` plus the U+0900-U+0DFF blocks, so Devanagari, Kannada,
Telugu and Tamil vowel signs stay inside their word; the danda ends a sentence like a full stop.
"""
import math
import re

WORD = re.compile(r"[\wऀ-෿]+")
SENT_END = re.compile(r"(?<=[.!?।॥])\s+")
FILLER = set("""
yeah yes yep yup no nope ok okay okk hmm hm mm mhm uh um uhh umm ah oh right so like sure fine alright
great good nice cool thanks thank bye hello hi hey haan han ha accha achha acha theek thik ji ok-ok
""".split())
STOP = set("""
a an the and or but if then so to of in on at by for with from as is are was were be been being am
i you he she it we they me him her us them my your his its our their this that these those there here
what which who whom whose when where why how do does did doing done have has had having will would
shall should can could may might must not no yes just also very really actually basically like
going gonna want wanna get got make made let lets let's okay ok yeah one two kind sort thing things
about into over than too only even still some any all more most much many well now know think mean
say said see go come take put way something anything everything need right sure uh um hmm
hai hain tha thi the ho hoga hogi ka ki ke ko se me mein par pe aur ya bhi toh to na nahi nahin kya
kyun kaise yeh ye woh wo vo jo ek haan accha achha matlab theek bas abhi phir fir kar karo karna
है हैं था थी थे हो का की के को से में पर और या भी तो ना नहीं क्या ये यह वो वह जो एक हाँ हां अच्छा
""".split())
MIN_WORDS, MIN_CONTENT = 6, 4
MIN_CHARS, MAX_CHARS, MAX_CHARS_RELAXED = 30, 280, 500
BUDGET_CHARS = 480         # the whole gist; about three lines in a list row
EXCERPT_CHARS = 240        # opening of an unpunctuated turn when nothing else qualifies
REDUNDANT = 0.5            # cosine above this to an already chosen sentence = says the same thing
FULL_STOP = (".", "?", "!", "।", "॥")
RICH = 12                  # sentences with fewer content words than this are scored down


def _words(s: str) -> list[str]:
    return [w.lower() for w in WORD.findall(s)]


def sentences(turns: list[str]) -> list[tuple[int, str]]:
    """(turn index, verbatim sentence) for every sentence in the turns, in order."""
    out = []
    for i, t in enumerate(turns):
        for s in SENT_END.split((t or "").strip()):
            s = s.strip()
            if s:
                out.append((i, s))
    return out


def _candidate(s: str, max_chars: int, min_words: int, min_content: int, strict: bool):
    if not (MIN_CHARS <= len(s) <= max_chars):
        return None
    if strict and (not s.endswith(FULL_STOP) or s.endswith("..") or "a" <= s[0] <= "z"):
        return None
    ws = _words(s)
    if len(ws) < min_words:
        return None
    content = [w for w in ws if w not in STOP and w not in FILLER and len(w) > 1 and not w.isdigit()]
    if len(content) < min_content or sum(w in FILLER for w in ws) * 2 > len(ws):
        return None
    return content


def _vec(words, idf):
    v = {}
    for w in words:
        v[w] = v.get(w, 0.0) + idf[w]
    n = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {k: x / n for k, x in v.items()}


def _dot(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(k, 0.0) for k, x in a.items())


def extract(turns: list[str], n: int = 3) -> list[dict]:
    """Up to `n` verbatim sentences as [{"text", "seg"}] (seg = index of the turn it came from)."""
    sents = sentences(turns)
    cands = []
    for max_chars, min_words, min_content, strict in ((MAX_CHARS, MIN_WORDS, MIN_CONTENT, True),
                                                      (MAX_CHARS_RELAXED, 4, 3, False)):
        cands = []
        for k, (seg, s) in enumerate(sents):
            c = _candidate(s, max_chars, min_words, min_content, strict)
            if c:
                cands.append((k, seg, s, c))
        if len(cands) >= 3:
            break
    if not cands:
        return _excerpt(sents)
    df = {}
    for *_, c in cands:
        for w in set(c):
            df[w] = df.get(w, 0) + 1
    total = len(cands)
    idf = {w: math.log((total + 1) / (d + 1)) + 1.0 for w, d in df.items()}
    vecs = [_vec(c, idf) for *_, c in cands]
    centroid = {}
    for v in vecs:
        for k, x in v.items():
            centroid[k] = centroid.get(k, 0.0) + x
    scores = [_dot(v, centroid) * math.sqrt(min(len(c[3]), RICH) / RICH) for v, c in zip(vecs, cands)]
    order = sorted(range(total), key=lambda i: (-round(scores[i], 9), i))
    chosen, used = [], 0
    for i in order:
        if len(chosen) >= n:
            break
        s = cands[i][2]
        if chosen and used + len(s) > BUDGET_CHARS:
            continue
        if any(_dot(vecs[i], vecs[j]) > REDUNDANT for j in chosen):
            continue
        chosen.append(i)
        used += len(s)
    chosen.sort(key=lambda i: cands[i][0])
    return [{"text": cands[i][2], "seg": cands[i][1]} for i in chosen]


def _excerpt(sents):
    """The opening words of the richest over-long sentence, up to EXCERPT_CHARS."""
    best = None
    for seg, s in sents:
        if len(s) <= MAX_CHARS_RELAXED:
            continue
        c = _candidate(s, len(s), MIN_WORDS, MIN_CONTENT, False)
        if c and (best is None or len(c) > best[0]):
            best = (len(c), seg, s)
    if best is None:
        return []
    _, seg, s = best
    cut = s[:EXCERPT_CHARS]
    cut = cut[:cut.rfind(" ")] if " " in cut else cut
    return [{"text": cut.rstrip(" ,;:-"), "seg": seg, "cut": True}]

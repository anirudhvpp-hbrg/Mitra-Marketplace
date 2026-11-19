"""Three faults found in the first live recording (2026-11-20, synthesized two-voice speech):

1. The microphone track, with nobody speaking into it, produced "Thank you." The speech model invents
   such lines from near-silence. A piece is now judged by its average loudness (it was the loudest
   single sample, which a click sets off), and stock phrases heard on a quiet piece are dropped.
2. A sentence that straddled two half-minute pieces was cut in two, and the small live model then
   dropped its second half. The last line of a piece, if it runs into the piece's end, is now held
   back and heard again whole at the start of the next piece.
3. The 40-name prompt made the small live model drop whole sentences. The live transcript no longer
   uses it; known wrong spellings are still put right afterwards. (The accurate model, used for the
   memo, was not affected by the prompt on the same audio and keeps it.)
Run once from the project root: python logs/scripts/fix_live_transcript.py
"""
from pathlib import Path

f = Path("workers/mitra_workers/live.py")
s = f.read_text("utf-8")


def rep(a, b):
    global s
    assert s.count(a) == 1, (s.count(a), a[:70])
    s = s.replace(a, b)


rep("QUIET = 250          # a piece whose loudest sample is below this (of 32767) is silence: no model is run for it",
    "QUIET = 45           # a piece whose average loudness is below this (of 32767) is silence: no model is run for it\n"
    "FAINT = 150          # below this a piece is faint, and a stock phrase heard on it is the model filling silence\n"
    "CARRY_MAX = 14.0     # the most of a piece's end, in seconds, that is heard again with the next piece\n"
    "_STOCK = re.compile(r\"^\\W*(thank you|thanks|thanks for watching|thank you very much|okay|ok|bye|you|yeah|hmm+|so)\\W*$\", re.I)")

a0, a1 = s.index("def peak(wav: Path) -> int:"), s.index("def record(app: str, job, title: str, attendees: str) -> dict:")
s = s[:a0] + '''def loud(wav: Path) -> int:
    """Average loudness of a piece (root mean square of its samples)."""
    with wave.open(str(wav), "rb") as w:
        a = array("h")
        a.frombytes(w.readframes(w.getnframes()))
    part = a[::8]
    return int((sum(x * x for x in part) / max(1, len(part))) ** 0.5)


def _with_lead(wav: Path, before: Path | None, lead: float) -> Path:
    """`wav` with the last `lead` seconds of the piece before it put in front, so a sentence that ran
    over the join is heard whole. Returns `wav` itself when there is nothing to put in front."""
    if not before or lead <= 0.05 or not before.is_file():
        return wav
    out = wav.with_name(wav.stem + "-lead.wav")
    with wave.open(str(before), "rb") as b, wave.open(str(wav), "rb") as w, wave.open(str(out), "wb") as o:
        o.setnchannels(1)
        o.setsampwidth(2)
        o.setframerate(w.getframerate())
        n = min(b.getnframes(), int(lead * b.getframerate()))
        b.setpos(b.getnframes() - n)
        o.writeframes(b.readframes(n))
        o.writeframes(w.readframes(w.getnframes()))
    return out


def hear_piece(app: str, p: dict, wav: Path, before: Path | None = None, lead: float = 0.0, last: bool = False) -> tuple[list[dict], float]:
    """One piece through the live speech model. Returns (lines, held): `lines` are [{start, end, text}]
    in seconds from this piece's own start (negative for words carried over from the piece before);
    `held` is how many seconds of this piece's end were left for the next piece to hear whole."""
    src = _with_lead(wav, before, lead)
    lead = lead if src != wav else 0.0
    with wave.open(str(wav), "rb") as w:
        length = w.getnframes() / w.getframerate()
    out = src.with_suffix("")
    lang, _ = models.transcribe_plan(p)
    try:
        models._run_model(app, p, [p["runtime_path"], "-m", p["file"], "-f", str(src), "-oj", "-np", "-of", str(out),
                                   "-t", str(paths.config()["threads"]), *p.get("args", []), *lang], "the live transcript")
        data = json.loads(out.with_suffix(".json").read_text("utf-8", errors="replace"))
    finally:
        out.with_suffix(".json").unlink(missing_ok=True)
        if src != wav:
            src.unlink(missing_ok=True)
    faint = loud(wav) < FAINT
    lines = []
    for seg in data.get("transcription", []):
        text = models._NOISE.sub(" ", seg.get("text", "")).strip()
        if len(re.sub(r"\\W+", "", text)) < 2 or (faint and _STOCK.match(text)):
            continue
        lines.append({"start": seg["offsets"]["from"] / 1000 - lead, "end": seg["offsets"]["to"] / 1000 - lead, "text": library.fix_names(text)[0]})
    held = 0.0
    if lines and not last and lines[-1]["end"] >= length - 0.4 and length - lines[-1]["start"] <= CARRY_MAX and lines[-1]["start"] > 0:
        held = length - lines[-1]["start"]          # it runs into the end: the next piece will hear it whole
        lines.pop()
    return lines, held


''' + s[a1:]

rep('''                new = []
                for t, f in have:
                    try:
                        loud = peak(f)
                        if loud >= QUIET and p.get("ready"):
                            for l in hear_piece(app, p, f, names):
                                new.append({"t": round((n - 1) * PIECE_S + l["start"], 1), "who": me if t == "mic" else "Others", "text": l["text"]})
                    except (models.MemoryDenied, models.Stopped, RuntimeError) as e:''',
    '''                new = []
                for t, f in have:
                    try:
                        before, lead = (d / f"{t}-{n - 1:04d}.wav", held.get(t, 0.0)) if n > 1 else (None, 0.0)
                        held[t] = 0.0
                        if (loudness_of := loud(f)) >= QUIET or lead:
                            if p.get("ready"):
                                got, held[t] = hear_piece(app, p, f, before, lead, last=ended and not (d / f"{t}-{n + 1:04d}.wav").is_file())
                                for l in got:
                                    new.append({"t": round(max(0.0, (n - 1) * PIECE_S + l["start"]), 1), "who": me if t == "mic" else "Others", "text": l["text"]})
                    except (models.MemoryDenied, models.Stopped, RuntimeError) as e:''')
rep("    me, n, lines_n, last = owner(), 1, 0, {}\n", "    me, n, lines_n, last, held = owner(), 1, 0, {}, {}\n")
f.write_text(s, "utf-8")
print("ok")

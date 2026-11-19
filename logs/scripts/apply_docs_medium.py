"""Bring README.md, docs/ARCHITECTURE.md and docs/architecture.html in line with Whisper medium
being the speech model (2026-11-13). Reports any text it could not find instead of stopping."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
missed = []


def edit(rel, pairs):
    f = root / rel
    t = f.read_text("utf-8")
    for old, new in pairs:
        if t.count(old) != 1:
            missed.append((rel, t.count(old), old[:80]))
            continue
        t = t.replace(old, new)
    f.write_text(t, "utf-8")


SPEECH_NEW = ("Whisper medium (99 languages, 5-bit, 514 MB, greedy decoding) on pieces of 5 minutes cut in pauses. Each piece is heard whole, "
              "with word timings; each sentence goes to the speaker talking for most of it. Whatever is spoken is written in English. "
              "Whisper small takes over if this device cannot give medium the memory, and the memo says so")

edit("README.md", [
    ("| What was said | Whisper small (99 languages, 5-bit, 181 MB) on pieces of 5 minutes cut in pauses. Each piece is heard whole, with word timings; each sentence goes to the speaker talking for most of it. Whatever is spoken is written in English | 605 to 637 MB. About 11 s per minute of audio |",
     f"| What was said | {SPEECH_NEW} | 964 to 980 MB. About 25 s per minute of audio |"),
    ("A 4-minute call takes about 2 minutes; a 16-minute call took 7 minutes.",
     "A 4-minute call takes 3 minutes 18 seconds; a 16-minute call took 12 minutes 17 seconds (with Whisper small they took 1 minute 45 and 7 minutes; the larger speech model was chosen on 2026-11-13 for accuracy)."),
    ("| Models: Gemma 3 1B 769, Qwen3 0.6B 378, Whisper small 181, diarization 102, Whisper tiny 31 | 1460.7 |",
     "| Models: Gemma 3 1B 769, Whisper medium 514, Qwen3 0.6B 378, Whisper small 181, diarization 102, Whisper tiny 31 | 1975.0 |"),
    ("| **In the package** | **1607.1** |", "| **In the package** | **2121.3** |"),
    ("| **Everything Mitra uses** | **1705.2** |", "| **Everything Mitra uses** | **2219.4** |"),
    ("| whisper-small-q5_1-cpp while transcribing a real call | 605 to 637 MB |",
     "| whisper-medium-q5_0-cpp while transcribing a real call | 964 to 980 MB |\n| whisper-small-q5_1-cpp, the step-down | 605 to 637 MB |"),
])

edit("docs/ARCHITECTURE.md", [
    ("| On disk | 1,607 MB in the package, 1,705 MB with ffmpeg |", "| On disk | 2,121 MB in the package, 2,219 MB with ffmpeg. That is 121 MB over the 2 GB target; Whisper small (181 MB) is kept as the step-down |"),
    ("       Gemma 3 1B       speech to text     who speaks when", "       Gemma 3 1B       speech to text     who speaks when"),
    ("       Qwen3 0.6B       Whisper small      Sortformer", "       Qwen3 0.6B       Whisper medium     Sortformer"),
    ("| 2 | What was said | Whisper small, 99 languages, on pieces of 5 minutes cut in pauses. Each piece is heard whole with word timings. Each sentence goes to the speaker talking for most of it. Hindi and English come out as one English transcript | 605 to 637 MB. About 11 s per minute |",
     "| 2 | What was said | Whisper medium, 99 languages, greedy decoding, on pieces of 5 minutes cut in pauses. Each piece is heard whole with word timings. Each sentence goes to the speaker talking for most of it. Hindi and English come out as one English transcript. Whisper small takes over if this device cannot give medium the memory, and the memo says so | 964 to 980 MB. About 25 s per minute |"),
    ("A 4-minute call takes about 2 minutes; a 16-minute call about 7.", "A 4-minute call takes 3 minutes 18 seconds; a 16-minute call took 12 minutes 17 seconds."),
    ("| Speech to text | Whisper small Q5_1 | 181 MB | 605 to 637 MB | whisper.cpp |",
     "| Speech to text | Whisper medium Q5_0, greedy | 514 MB | 964 to 980 MB | whisper.cpp |\n| Speech to text, step-down | Whisper small Q5_1 | 181 MB | 605 to 637 MB | whisper.cpp |"),
    ("| **Best upgrade found. Fits. About 2.6 times slower** |", "| **Switched on, 2026-11-13.** In the app it peaks at 964 to 980 MB |"),
    ("None of these is switched on. Whisper medium is the one to decide first.",
     "The first is switched on (2026-11-13). The other three are not built."),
    ("| 949 MB then 945 MB, one after the other. A 16-minute call would take about 12 minutes instead of 7. Package grows by 514 MB to about 2.1 GB, just over the 2 GB target, unless Whisper small is left out of the package |",
     "| **Done.** 980 MB then 945 MB, one after the other. A 16-minute call takes 12 minutes 17 seconds instead of 7 minutes. The package is 2,121 MB |"),
])

edit("docs/architecture.html", [
    ("s: 'Whisper small · 605 to 637 MB', kind: 'Model',", "s: 'Whisper medium · 964 to 980 MB', kind: 'Model',"),
    ("f: ['99 languages; follows Hindi and English mixed', 'About 11 seconds per minute of audio', 'Whisper medium fits at 949 MB and is better; not switched on'] },",
     "f: ['99 languages; follows Hindi and English mixed', 'Greedy decoding keeps it under the ceiling', 'About 25 seconds per minute of audio', 'Whisper small (637 MB) takes over if memory is refused'] },"),
    ("'What was said: the speech model hears 5-minute pieces, about 630 MB. Sentences are given to speakers.'", "'What was said: the speech model hears 5-minute pieces, about 975 MB. Sentences are given to speakers.'"),
    ("'1,461 MB of models in the package'", "'1,975 MB of models in the package'"),
    ("f: ['Three models, one after another', 'A 16-minute call takes about 7 minutes',", "f: ['Three models, one after another', 'A 16-minute call takes about 12 minutes',"),
    ("['Speech (Whisper small)', 637, 714]", "['Speech (Whisper medium)', 980, 1024]"),
    ("[626, 627, 637].forEach((mb, i) => { SEG.push({ a: t, z: t + 50, mb, c: 'var(--navy-600)', n: `Speech, piece ${i + 1} of 3`, m: 'Whisper small' }); t += 50; });",
     "[972, 972, 979].forEach((mb, i) => { SEG.push({ a: t, z: t + 120, mb, c: 'var(--navy-600)', n: `Speech, piece ${i + 1} of 3`, m: 'Whisper medium' }); t += 120; });"),
    ("[177, 178, 173, 177].forEach((mb, i) => { SEG.push({ a: t, z: t + 52, mb,", "[187, 177, 177, 171].forEach((mb, i) => { SEG.push({ a: t, z: t + 67, mb,"),
    ("SEG.push({ a: t, z: t + 92, mb: 941,", "SEG.push({ a: t, z: t + 107, mb: 941,"),
    ("[0, 120, 240, 360].forEach((sec) =>", "[0, 180, 360, 540, 720].forEach((sec) =>"),
    ("'<span class=\"muted\">Total about 7 minutes. At no point are two models in memory.</span>'", "'<span class=\"muted\">Total about 12 minutes. At no point are two models in memory.</span>'"),
    ("models: ['Sortformer 187 MB', 'Whisper small 637 MB', 'Gemma 3 1B 945 MB'],", "models: ['Sortformer 187 MB', 'Whisper medium 980 MB', 'Gemma 3 1B 945 MB'],"),
    ("{ n: 'What was said', s: 'Whisper small', mem: '605 to 637 MB', time: '11 s per minute of audio',", "{ n: 'What was said', s: 'Whisper medium', mem: '964 to 980 MB', time: '25 s per minute of audio',"),
    ("['Whisper medium, 5-bit, greedy', 'Speech', '934 to 949 MB', 'Clearly better than small on a real call: what was pitched, who tells whom, clean short sentences. 108 s against 41 s.', 'best', 'Best upgrade found'],",
     "['Whisper medium, 5-bit, greedy', 'Speech', '964 to 980 MB', 'Clearly better than small on a real call: what was pitched, who tells whom, clean short sentences. About 2.6 times slower. Switched on 13 November.', 'use', 'In use'],"),
    ("['Whisper small Q5_1', 'Speech', '605 to 637 MB', 'Follows Hindi and English mixed; names and dates right.', 'use', 'In use'],",
     "['Whisper small Q5_1', 'Speech', '605 to 637 MB', 'Follows Hindi and English mixed. Takes over if medium is refused memory.', 'maybe', 'Step-down'],"),
    ("const FILTERS = [['all', 'All'], ['use', 'In use'], ['best', 'Best upgrade'], ['maybe', 'Feasible'], ['no', 'Rejected']];",
     "const FILTERS = [['all', 'All'], ['use', 'In use'], ['maybe', 'Feasible or fallback'], ['no', 'Rejected']];"),
    ("'949 MB then 945 MB, one after the other. A 16-minute call: about 12 minutes instead of 7. Package grows to about 2.1 GB.'],",
     "'Switched on 13 November. 980 MB then 945 MB, one after the other. A 16-minute call takes about 12 minutes instead of 7.'],"),
    ("<p>Pick something you might do.", "<p>Pick something you might do."),
])
for m in missed:
    print("NOT FOUND:", m)
print("done;", len(missed), "missed")

"""Why did the long two-voice test recording split one voice between two speakers?

    python logs/scripts/debug_long_speakers.py [rounds]

Makes the same synthesized recording the test makes (two installed Windows voices taking turns),
runs the speaker model the way TwinMind does, and prints for each window which local speaker was
mapped to which, then the transcript's speaker per line beside the voice that actually spoke it
(known from the words: voice 1 says "export", voice 2 says "snapshots").
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workers"))
from mitra_workers import models, paths  # noqa: E402

rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 30
wav = paths.HOME / "tmp" / "debug-long.wav"
wav.parent.mkdir(parents=True, exist_ok=True)
a = "Round {n}. Please fix the export before the release. The export fails on large invoices and the client is waiting."
b = "Understood, round {n}. The staging database is nearly full, so I will clear old snapshots this afternoon and report back."
ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
      "$v = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }); "
      f"$s.SetOutputToWaveFile('{wav}'); "
      f"for ($n = 1; $n -le {rounds}; $n++) {{ $s.SelectVoice($v[0]); $s.Speak('{a}'.Replace('{{n}}', $n)); "
      f"if ($v.Count -gt 1) {{ $s.SelectVoice($v[1]) }}; $s.Speak('{b}'.Replace('{{n}}', $n)) }}; "
      "$s.Dispose(); Write-Output ($v -join ' | ')")
print("voices:", subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, text=True).stdout.strip())
wav16, made = models.prepare_wav(wav)
total = models.wav_seconds(wav16)
print(f"length {total:.0f} s; windows {models.diar_windows(total)}")

orig = models.link_windows


def traced(before, local, o0, o1):
    out = orig(before, local, o0, o1)
    def talk(turns, lo, hi):
        t = {}
        for x in turns:
            s = max(0.0, min(x["end"], hi) - max(x["start"], lo))
            if s > 0:
                t[x["speaker"]] = round(t.get(x["speaker"], 0) + s, 1)
        return t
    print(f"  join at {o0:.0f}-{o1:.0f} s | earlier turns in overlap {talk(before, o0, o1)} | new window in overlap {talk(local, o0, o1)} "
          f"| new window overall {talk(local, o0, 1e9)} | after join {talk(out, (o0 + o1) / 2, 1e9)}")
    return out


models.link_windows = traced
turns = models.diarize("debug", wav16)
print("turns:", len(turns), "speakers:", sorted({t["speaker"] for t in turns}))
info = {}
lines = models.transcribe("debug", wav16, wav_ready=True, turns=turns, info=info)
print("transcribe:", info)
bad = 0
for l in lines:
    low = l["text"].lower()
    voice = "1" if ("export" in low or "invoice" in low) and "snapshot" not in low else "2" if ("snapshot" in low or "staging" in low) and "export" not in low else "?"
    flag = ""
    if voice != "?" and l.get("speaker") != f"Speaker {voice}":
        bad += 1
        flag = "   <-- other speaker"
    print(f"[{l['start']:6.1f}-{l['end']:6.1f}] {l.get('speaker', '-'):<10} voice {voice}  {l['text'][:95]}{flag}")
print("lines:", len(lines), "under the other speaker:", bad)
if made:
    wav16.unlink(missing_ok=True)

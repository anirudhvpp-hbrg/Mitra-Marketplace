"""Replace the transcription half of workers/mitra_workers/models.py with the 0.8 version
(whole pieces with word timings, speakers given per clause). Run once from the project root."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
target = root / "workers" / "mitra_workers" / "models.py"
text = target.read_text("utf-8")
at = text.index("def transcribe_turns(")
new = (Path(__file__).parent / "models_transcribe_0_8.py.txt").read_text("utf-8")
target.write_text(text[:at] + new, "utf-8")
print("replaced from offset", at, "; file is now", len(text[:at] + new), "chars")

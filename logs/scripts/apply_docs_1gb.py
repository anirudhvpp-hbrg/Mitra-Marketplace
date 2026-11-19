"""Bring README.md in line with the 1 GB ceiling and the Gemma 3 1B notes model (2026-11-13).
Run once from the project root."""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
f = root / "README.md"
t = f.read_text("utf-8")

pairs = [
    ("| Notes | Qwen3 0.6B, section by section, then the grounding check | 763 to 772 MB |",
     "| Notes | Gemma 3 1B, section by section, then the grounding check. If this device cannot give it the memory, Qwen3 0.6B writes the notes and the memo says so | 915 to 945 MB |"),
    ("if one is stopped at that cap and the 800 MB ceiling still has room",
     "if one is stopped at that cap and the 1 GB ceiling still has room"),
    ("| Models: Qwen3 0.6B 378, Whisper small 181, diarization 102, Whisper tiny 31 | 692.0 |",
     "| Models: Gemma 3 1B 769, Qwen3 0.6B 378, Whisper small 181, diarization 102, Whisper tiny 31 | 1460.7 |"),
    ("| **In the package** | **838.3** |", "| **In the package** | **1607.1** |"),
    ("| **Everything Mitra uses** | **936.4** |", "| **Everything Mitra uses** | **1705.2** |"),
    ("and none above `model_budget_mb` (default 800).", "and none above `model_budget_mb` (default 1024, that is 1 GB; it was 800 until 2026-11-13)."),
    ("is stopped at about 230 MB, not at 800.", "is stopped at about 230 MB, not at 1024."),
    ('  "model_budget_mb": 800,', '  "model_budget_mb": 1024,'),
    ("| qwen3-0.6b-q4_k_m while answering | 734 to 756 MB |",
     "| qwen3-0.6b-q4_k_m while answering (Ask Mitra) | 564 MB |\n| gemma-3-1b-it-q4_k_m while writing meeting notes | 915 to 945 MB |"),
]
for old, new in pairs:
    assert t.count(old) == 1, old[:60]
    t = t.replace(old, new)

# the notes-quality paragraph under "Not done yet"
start = t.index("- **Notes quality is the weak part of TwinMind.**")
end = t.index("\n", start)
t = t[:start] + (
    "- **Notes quality is better, not solved.** On 2026-11-13 you raised the ceiling to 1 GB and the notes model became Gemma 3 1B. "
    "On your two calls it writes concrete points and real action items (\"Share the proposal with the client by Wednesday\", "
    "\"Schedule a discovery session with the client\") and no longer repeats transcript lines, where Qwen3 0.6B produced mostly noise. "
    "It still gets things wrong: it sometimes gives a statement or a task to the wrong speaker, it writes vague tasks (\"Give example\"), "
    "and it repeats any mistake in the translated transcript as fact (a mistranslated word became \"the donkey's video\"). "
    "The check removes an owner, date or number the transcript does not support. Read the notes against the quoted commitments before acting on them."
) + t[end:]

# how the memory was found
old = "How the assistant's 881 MB was brought to about 750 MB is recorded in `logs/scripts/bench_llama_flags.py`: an 8-bit context cache and a 1,536-token context. A 4-bit cache saved more and produced garbage."
assert old in t
t = t.replace(old, old + " On 2026-11-13 turning off load-time weight repacking (`--no-repack`) took it from 762 MB to 564 MB, and Gemma 3 1B from 987 to about 915 MB, with the same answers and no loss of speed measured (`logs/scripts/apply_no_repack.py`).")
f.write_text(t, "utf-8")
print("README updated")

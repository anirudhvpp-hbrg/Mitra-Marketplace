# What Mitra took from APTM (Mitra Ear)

APTM was the earlier local meeting app at `C:\Users\<you>\Desktop\APTM` (Mitra Ear 1.2, October 2026). On 2026-11-11 its portable capabilities were moved into Mitra Marketplace and the folder was sent to the Recycle Bin. The complete source, docs, tests, bake-off results and packaging scripts are kept in `aptm-source-2026-11-11.zip` beside this file (93 files; compiled `.pyc` files and logs left out), so nothing that was not ported is lost.

## Absorbed and working

| APTM capability | Where it came from | Where it is now | State |
|---|---|---|---|
| Quoted gist: two or three sentences picked by TF-IDF centrality, word for word, no model, Indic-aware | `app/aptm/gist.py` | `workers/mitra_workers/gist.py` | Ported whole. Tested (T19, T32) |
| Grounding guard: drop bullets whose numbers are not in the transcript; blank owners and due dates never said | `app/aptm/mind.py` (guard 4.4) | `workers/mitra_workers/grounding.py` | Ported and extended: numbers spoken as words ("ninety percent", "the twentieth") now count as grounded. Tested (T19) |
| Notes contract: four-section notes, action items as schema-constrained JSON, title, output caps | `mind/prompts.py` | `workers/mitra_workers/meeting.py` | Ported. The exact prompt strings are kept because the fine-tune was trained on them |
| Deterministic merge across sections with de-duplication, each item tagged with its section | `app/aptm/mind.py` `merge_summary` | `meeting.merge` | Ported |
| 420-word sections on line boundaries | `chunk_transcript` | `meeting.chunk` | Ported |
| Mitra Ear fine-tune (Gemma 3 270M, trained on 4,600 labelled chunks of your meetings) | `E:\Local AI Models\08 Customized Models\gemma-3-270m-mitra-ear` | `catalog.json`, capability `meeting-notes`, second candidate | Registered and measured: 361 MB. On the test meeting it stated one decision wrongly and found one action of four, so Qwen3 0.6B is first and the fine-tune is used where the ceiling is below 760 MB |
| Search across meetings, passages quoted exactly | `app/aptm/index.py` (the idea, not the code) | TwinMind `search` route and "Find what was said" box | Rewritten as a plain scan of saved memos; no index, no model. Tested (T32) |
| Meeting list rows that show the gist | `app/aptm/api.py` | TwinMind `meetings` route | Rewritten |
| Prompt cache off (`--cache-ram 0`): APTM measured the model server growing to 6.25 GB over about 500 sections | `app/aptm/mind.py` | `assistant_args` default | Applied |
| "A stage that fails must not cost you the transcript" | pipeline design | TwinMind `run` | Applied to diarization |

## Not absorbed, and why

| APTM capability | Why not |
|---|---|
| Multilingual Ear (IndicConformer packs for Hindi, Marathi, Kannada, Telugu, Tamil, Sanskrit, plus NeMo English; two-pack language routing by confidence) | Needs `onnxruntime`, `numpy` and `kaldi_native_fbank`, which Mitra's workers do not carry, and the model packs were under `Downloads\MITRA-local-state\aptm\models\ear`, which no longer exists on this machine. The code is in the archive (`app/aptm/ear.py`); the bake-off numbers are in `bakeoff/BAKEOFF-REPORT.md`. Mitra transcribes English with Whisper tiny |
| Live recording, meeting detection (microphone in use by Teams, Zoom, Meet; window titles), auto-stop rules | Windows-only device and registry access through `sounddevice` and PortAudio. Mitra takes a finished recording file. Code: `capture.py`, `detector.py`, `audio.py`, `watcher.py` |
| Outlook calendar ("Up next", meeting title from the calendar) | Windows COM, classic Outlook only. Code: `outlook.py` |
| Speaker registry, tag vocabulary, rule-based classification, "names to resolve" | Tied to the old `MITRA\Meeting Intelligence` folder layout (REGISTRY.md, tags.md, graph files). The canonical archive is now `0. AP Persistent AI Brain\Meeting Intelligence` with a different schema. Code: `mi.py`, `classify.py`, `vault.py` |
| Grounded question answering over retrieved passages (answer kept only if it restates the passages) | Mitra's search returns quoted passages only. The guard logic is in the archive (`mind.py` `ask`) and is a small step from here |
| Phone access through Tailscale with a pairing code | Mitra listens on this device only, by design. Code: `auth.py`, `service.py` |
| Desktop shell (pywebview window, tray icon), MSI installer | Mitra opens in the browser and installs from a zip. Scripts: `packaging/` |
| Process bound to a Windows Job Object so a child dies with the app even on a hard kill | Not yet in the Rust governor; a model can be orphaned if the governor itself is killed. Worth doing. Code: `procjob.py` |
| The 265 pytest cases | They test APTM's own modules. Mitra has its own suite (`logs/tests`) |

## Findings carried over from APTM's reports

- Fine-tuning is what makes a 270M model usable for notes, and even tuned it missed action items (APTM Phase 1 report). Mitra's measurement agrees.
- LFM2.5-350M needs 5 to 10 times more tokens for Indic text and rewrites text it is asked to keep (APTM bake-off). It stays in Mitra's catalog only as an English fallback.
- One hour of meeting is about 20 sections; at measured CPU speeds the notes take a minute or two.

# Fine-tuning plan: a meeting-notes model for your own TwinMind

Status: on hold. On 2026-11-11 the decision was to use Qwen3 0.6B untrained, with the model ceiling raised to 800 MB, because it summarised the test meeting accurately where the 350M model did not. Nothing has been trained and no training environment is installed. The archive was read, not changed. This plan stays here in case commitments extraction or summary quality on real meetings turns out to need it; if it is revived, Qwen3 0.6B joins the candidate bases.

## Goal

Make the notes from Mitra's TwinMind accurate enough to rely on, with a model that still fits the 500 MB budget on CPU.

Baseline measured on 2026-11-11: LFM2.5-350M (415 to 447 MB) gets one or two facts wrong per summary and cannot extract who-does-what. Qwen3 0.6B was accurate but needs 866 to 882 MB.

## The data: your Meeting Intelligence archive

Source: `Dropbox\0. AP Persistent AI Brain\Meeting Intelligence`. The TwinMind connector and its daily limit are not used at all.

What is in it, counted on 2026-11-11 with `logs/scripts/meeting_archive_stock.py`:

| Measure | Count |
|---|---|
| Records in the manifest | 3,740 |
| Normalised transcripts | 2,597 |
| Of those, with 10 or more speaker turns | 1,599 |
| Notes files (summary and action headings, no transcript) | 854 |
| Transcripts with no client named | 1,844 |
| Transcripts whose speakers are resolved or partly resolved | 733 |
| Transcript length | median 2,700 words; one in ten is over 9,900 |
| Date span | mostly 2025 and 2026 |

**The finding that shapes the plan: transcripts and notes are rarely linked.** Only 21 transcripts match a notes file by date and title, and none match by meeting id. At most 188 transcripts share a day with a notes file. So there is plenty of input (transcripts) and plenty of example output (notes), but few ready-made pairs.

Rules from the archive's own README that this plan follows:

- The archive is read-only for this work. Training data is copied out to `~/.mitra/finetune/data/`, outside every synced folder. Nothing is written into the archive.
- A person is named as the owner of something only where the transcript's speakers are resolved. Unresolved transcripts can teach summarising, not who-said-what.

## Steps

### 1. Select

- Take normalised transcripts with real speaker turns.
- Leave out records with a client named, by default. That leaves up to 1,844. A blank client field does not prove a meeting was internal, so a keyword screen for client names runs as a second check.
- Scrub emails, phone numbers and account-like numbers.

### 2. Recover the pairs that exist

- Match notes to transcripts by date plus overlap of names and distinctive words, beyond the 21 exact matches. Expect somewhere between 21 and 188 pairs.
- These pairs are too few to train on. They become the **test set**: real notes for real meetings, never shown to the model in training.

### 3. Create the training targets

Because pairs are scarce, targets are written by a larger local teacher model from your library (4B to 10B class) on this laptop's GPU. No transcript leaves the machine.

| Task | Input | Target |
|---|---|---|
| Section summary | One transcript section | 3 to 5 bullets with exact dates and numbers |
| Commitments | One section from a speaker-resolved transcript | Owner, task, deadline, or "none" |
| Merge | Bullets from all sections | The final note |

- The 854 notes files show the teacher what a finished note looks like in your archive, so the output matches your format and vocabulary.
- Every teacher answer is checked automatically: a number, date or name in it must appear in the section it came from, or it is discarded.
- Size: about 300 transcripts give roughly 3,000 section examples (estimate), which is enough for a model this small. More can be added if the gates are not met.

### 4. Train

- Two bases compete: **Gemma 3 270M** (333 MB measured) and **LFM2.5-350M** (415 MB measured). Qwen3 0.6B is excluded because it cannot fit the budget.
- LoRA adapters, merged into the base and converted to a Q4 GGUF.
- On this laptop's RTX 4050. Runs should take well under an hour each (estimate). PyTorch is needed for training only, about 3 GB, in a separate environment; the product stays free of it.

### 5. Evaluate

A candidate replaces the current model only if it passes every gate on the test set:

| Gate | Measure | Pass |
|---|---|---|
| Fits | Peak RAM measured by the governor | 500 MB or less |
| No invented facts | Summaries containing a number, date or name absent from the transcript | Fewer than the base model, and under 5% |
| Coverage | Decisions and actions from the real notes that appear in the output | More than the base model |
| Commitments | Precision and recall on speaker-resolved test meetings | Both above 80%, and better than the pattern match |
| Speed | Seconds per section on CPU | No slower than the base model |
| Your judgement | Blind comparison, old against new, on 10 meetings | You prefer the new one |

### 6. Ship

- GGUF and `MODEL_CARD.md` into `E:\Local AI Models\08 Customized Models\mitra-marketplace-finetunes\<name>\`.
- Added to `catalog.json`, measured, as TwinMind's first candidate. Ask Mitra keeps the general model.
- A regression case added to the test suite.
- Rollback is removing the catalog entry.

## Decisions needed

| # | Decision | Default if you say go |
|---|---|---|
| 1 | Include meetings with a client named? | No |
| 2 | Output format: the seven sections in your archive's `SCHEMA.md` (Context, Decisions, Actions, Numbers, Risks, Open questions, Verbatim), or the shorter Summary plus Commitments that Mitra writes today? | `SCHEMA.md`, so Mitra's notes can enter the archive's `notes/` layer, which is empty today |
| 3 | Install the PyTorch training environment (about 3 GB) | Yes, under `~/.mitra/finetune/env` |
| 4 | Your blind comparison on 10 meetings at the end | Required |

## Risks

- **Ceiling.** A 270M to 350M model may not reach the gates even after training. The fallback is a 900 MB budget for TwinMind only, with Qwen3 0.6B.
- **Seven sections is a lot for a small model.** If decision 2 is `SCHEMA.md`, each section is produced by its own short request, which is slower. Sections it cannot fill reliably will say "none" instead of guessing.
- **The teacher's mistakes become the student's.** The automatic fact check and the real-notes test set limit this, but do not remove it.
- **Speaker names.** 1,864 records are unresolved. Commitments training uses only the 733 resolved or partly resolved transcripts, and Mitra's own recordings have no speaker labels until diarization works.
- **Untagged client meetings.** Some of the 1,844 "no client" transcripts may be client meetings that were never tagged.

## Rough timeline

| Day | Work |
|---|---|
| 1 | Select, screen, scrub; recover pairs for the test set |
| 2 | Teacher labelling and automatic checks |
| 3 | Train both bases, evaluate, pick one |
| 4 | Your blind comparison; ship or fall back |

All estimates. Nothing waits on an outside service.

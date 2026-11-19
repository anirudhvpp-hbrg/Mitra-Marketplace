# Mitra interface review

Reviewed on 2026-11-11, version 0.5.0, on Windows 11 in a Chromium browser.

## What this review covered and how

Every screen of the marketplace and all five apps was opened and used with real files, one feature at a time, and the result of each step was read back from the page. The files were made for the purpose (`logs/scripts/make_review_fixtures.py`): a two-page PDF, a Markdown file that uses every construct the reader claims to support, a Word file, a CSV, an HTML page and a meeting transcript.

The second half compares each app with the established products in its category. That research is in two companion files:

- `docs/research/meeting-apps-interface-map.md`: Fireflies, TwinMind, Granola, Otter, Fathom.
- `docs/research/pdf-and-markdown-readers-interface-map.md`: Acrobat Reader, Edge, Preview, PDF.js, Obsidian, Typora, VS Code, GitHub.

**Limits of this review.** The walk-through was driven by automation, not by a person, so it shows that features work, not how they feel. Not exercised: dragging a file onto the converter, the browser's own confirm dialogs, a real meeting recording, and a real phone. The competitor research is from documentation; nobody opened those products.

## Result in one table

| Screen | Features exercised | Result |
|---|---|---|
| Home | Greeting, status line, search filter, empty search, recent files, app order by use, theme switch, command palette, arrow keys | All work |
| Create | Draft from a description, edit, create, open on the generic workspace, connector folder created, remove | All work |
| Memory | Week, two weeks, month, save report | Work; three defects fixed (below) |
| System | RAM ring, history, limits, running models, capability table | All work |
| Markdown Reader | Open by path, 14 Markdown constructs, outline, source toggle, raw HTML shown as text, unsafe link blocked | Works; three defects fixed |
| PDF Reader | Open by path, page view, text view, convert, open in tab | Works; two defects fixed |
| Anything to Markdown | Convert Word, edit source, preview, save | Works; one defect fixed |
| Ask Mitra | Ask, follow-up, RAM returned after each answer | Works; one defect fixed, three improvements made |
| TwinMind | Process a transcript, progress steps, meetings list with gist, search, open the memo | Works; three defects fixed |
| Manager panel | Open on TwinMind | Works; one defect fixed |
| Phone width | Home and TwinMind at 375 px | No sideways scroll; no control under 40 px |

## Defects found and fixed during the review

| # | Where | What was wrong | Fix |
|---|---|---|---|
| 1 | Markdown Reader | A bare web address at the end of a sentence took the full stop into the link | The closing punctuation is left out |
| 2 | Markdown Reader | A link to another file beside the open one led to a missing page | It opens that file in the reader (PDFs in the PDF Reader) |
| 3 | Markdown Reader | Links to a heading in the same file (`#some-heading`) did not work | Headings get the ids other tools give them |
| 4 | PDF Reader | Text view ran each page's lines together into one paragraph | Lines stay lines |
| 5 | PDF Reader | At narrow widths the file name disappeared from the toolbar | The toolbar wraps |
| 6 | Anything to Markdown | After saving, nothing showed the new file or offered to open it | The file list refreshes and a link opens it in the reader |
| 7 | Ask Mitra | A follow-up repeated the previous answer before answering | Earlier turns are sent as conversation, not pasted into the question |
| 8 | TwinMind | Search showed the same sentence three times (transcript, points, commitments) | One result per sentence, pointing at the transcript |
| 9 | TwinMind | A search result opened the memo at the top | It opens at the passage and marks it |
| 10 | TwinMind | `mitra-marketplace open twinmind FILE` ignored the file | The file is preselected |
| 11 | TwinMind | Memo file names could contain a double space | Collapsed |
| 12 | Memory | Requests from the document apps were counted under "shell", so those apps showed no RAM figures | Counted under the app whose page made the request |
| 13 | Memory, Manager | A model working as designed (756 of 800 MB) was flagged as near its limit | Flagged only when a run exceeds the cap it was given |
| 14 | Memory | Raw timestamps and internal action names in the usage table | Readable dates and plain names |

Also improved in Ask Mitra: the conversation survives a reload, each answer has a Copy button, and there is a New conversation button.

All 38 automated tests pass after these changes.

## App by app, against the established products

### TwinMind (against Fireflies, Granola, Otter, TwinMind, Fathom)

**What Mitra already has that they do not all have**

- A gist quoted word for word, and a grounding check that removes unsupported owners, dates and numbers and lists what it removed. No product in the research documents anything like a confidence or grounding mark.
- Everything stays on the device, with no bot in the call.
- File upload, which Granola lacks, and Markdown output, which only Fireflies and Granola offer.

**Where Mitra is behind, most important first**

| # | Gap | What the others do | Why it matters here | Size |
|---|---|---|---|---|
| 1 | No meeting page. A memo opens in the general Markdown Reader | All five land on the notes with the transcript beside it or one click away | The memo is the product; it deserves its own screen | Medium |
| 2 | A note does not link to the moment it came from | Granola's magnifier per point, Otter's "View in transcript", Fireflies' timestamped chapters | Mitra's notes need checking (the model's action items are unreliable), and this is how checking is made quick | Small once #1 exists: items already carry their section |
| 3 | The recording is not kept with the memo or playable | Fireflies, Otter and Fathom play audio in step with the transcript. Granola keeps none, and that is its most cited complaint | Mitra has the file and the timestamps; clicking a line to hear it is the strongest check there is | Medium |
| 4 | Speakers cannot be renamed | Click the label and apply to all (Fireflies, Otter). TwinMind and Granola have no control, and are criticised for it | Mitra's speakers are "Speaker 1, Speaker 2" | Small |
| 5 | Notes cannot be edited or regenerated in place | Editable notes and an explicit Regenerate button everywhere | Corrections are lost today unless made in a text editor | Medium |
| 6 | No list of action items across meetings | Fireflies' Tasks page, Otter's Action Items tab, with checkboxes and assignees. Due dates are rare | The point of extracting actions is to track them | Medium |
| 7 | Search returns passages but cannot answer a question | Chat scoped to one meeting, a folder or everything; Otter and Granola show clickable sources | Mitra's quoted search is honest; an answer with citations would be the next step, and APTM already had the guard for it | Medium |
| 8 | No folders, people or date filters on the meeting list | Folders or channels everywhere; people pages in Granola and TwinMind | Matters once there are dozens of meetings | Small to medium |
| 9 | One fixed memo format | Templates as prompts with section toggles | Your archive's `SCHEMA.md` is a natural second template | Small |
| 10 | No export choices | Speaker and timestamp toggles; SRT and DOCX | Low; Markdown covers most uses | Small |
| 11 | No live capture | All five record live; most show a live transcript | Large, and Windows-specific. The code exists in the APTM archive | Large |

### PDF Reader (against Acrobat Reader, Edge, Preview, PDF.js)

Mitra shows the PDF in the browser's own viewer, so zoom, page number, rotate, print and find already work inside the page area. What Mitra itself adds is thin: a text view and a convert button.

| # | Gap | What the others do | Size |
|---|---|---|---|
| 1 | No search across the extracted text with a results list | All four highlight every match; Acrobat lists results with context, nested by page | Small: the text is already extracted per page |
| 2 | No outline | All four show the PDF's bookmarks as a table of contents | Small if read from the file's outline |
| 3 | No search across a folder of PDFs | Acrobat's Advanced Search, with results per document | Medium |
| 4 | No highlights or notes | All four, saved with the file; Acrobat and Preview list them | Large if written into the PDF; small if kept beside it as a notes file |
| 5 | No read aloud | Acrobat and Edge | Small: the browser has speech built in |
| 6 | No questions about the document | Acrobat's paid assistant answers with numbered citations that jump to the passage | Medium: the assistant and the grounding check exist; a 1,536-token context limits it to a few pages at a time |
| 7 | No document details | Acrobat's properties: title, author, page count, security | Small |
| 8 | Reopening does not return to the last page | Acrobat restores it | Small |
| 9 | No page thumbnails | Acrobat, Preview, PDF.js | Medium |

Night reading is worth noting: Acrobat has no real dark mode for pages. Mitra's text view already follows the dark theme, which is an advantage to keep.

### Markdown Reader (against Obsidian, Typora, VS Code, GitHub)

Mitra covers the top four items on the common-feature list: rendered view with a source toggle, a clickable outline, tables and task lists and images, and (after this review) heading anchors and links between files. Front matter is shown in its own block.

| # | Gap | What the others do | Size |
|---|---|---|---|
| 1 | No search across files | Obsidian, Typora and VS Code search a whole folder, with context | Medium |
| 2 | Code blocks are plain, with no copy button | All four colour code | Small for a copy button; medium for colouring without a library |
| 3 | No Mermaid diagrams or math | All four render Mermaid; three render math | Large without bringing in a library |
| 4 | No editing | Typora and Obsidian are editors | Medium for a plain-text edit and save; outside a reader's brief |
| 5 | The outline does not show where you are | Obsidian and VS Code highlight the current heading | Small |
| 6 | No export to PDF | Typora | Small: the browser's print does it with a print stylesheet |
| 7 | No backlinks | Obsidian only | Medium; valuable only with many linked notes |

### Anything to Markdown

There was no direct competitor in the research. Against Acrobat's export (paid) it already does the main job free and locally. Gaps seen in use: no batch conversion of a folder, no choice of where to save, and scanned PDFs yield nothing because there is no text recognition.

### Ask Mitra

Against the chat in the meeting apps: answers arrive all at once (no streaming), there is one conversation, not a history of them, and a file cannot be attached. The model is the real limit: on the follow-up question in this review it gave a correct answer only after the history fix, and still restated its first sentence.

### Home, Create, Memory, System

These work as designed and have no direct equivalent in the research. Small things noticed: apps cannot be pinned, a finished TwinMind job is only visible on TwinMind's own page, and the Create screen gives no hint of which words it recognises.

## Recommended order

1. **A meeting page for TwinMind** with notes on the left and the transcript on the right (TwinMind #1), built so that each note and action links to its place in the transcript (#2) and speakers can be renamed with apply-to-all (#4). These three belong together and change the app the most.
2. **Keep the recording and play from any line** (#3). It turns "check it against the transcript" into one click.
3. **Edit and regenerate notes; a cross-meeting action list** (#5, #6).
4. **PDF Reader: search with a results list, outline, read aloud, last page** (PDF #1, #2, #5, #8). Four small items that close most of the visible distance to Acrobat for reading.
5. **Search across files** for Markdown and PDF together (Markdown #1, PDF #3), since it is one piece of work.
6. **Questions with citations**, for a meeting and for a PDF (TwinMind #7, PDF #6), using the guard already in the APTM archive.

Left for later on purpose: live capture, annotations written into PDFs, Mermaid and math. Each is large, and none is needed for the apps to be useful every day.

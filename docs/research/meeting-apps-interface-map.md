# Meeting-note apps: interface map

Fireflies, TwinMind, Granola, Otter and Fathom, researched on 2026-11-11 for the Mitra interface review.

**How to read this.** Everything here comes from the vendors' help centres, their blogs, or third-party reviews. Nobody opened the apps to check the screens, so layout details are documented, not observed. Tags: **[D]** read in vendor documentation, **[B]** vendor blog or marketing page, **[R]** third-party review, **NV** not verified (no source found; not guessed). Products change quickly; anything here may be out of date. TwinMind and Fathom are thinly documented.

## Summary table

| Aspect | Fireflies | TwinMind | Granola | Otter | Fathom |
|---|---|---|---|---|---|
| Home | Left nav; feed, upcoming, tasks | Memories grouped by day; People | Upcoming events and notes list; folder sidebar | Calendar and Action Items tabs; folders, channels | Call lists with a chat panel on the right |
| Capture | Bot, bot-free desktop, upload; live transcript and notes | Phone mic, browser tab audio, desktop; live transcript | System audio, no bot, no upload; notepad plus live transcript | Bot, bot-free desktop, import; live transcript | Bot or bot-free; summary builds live |
| Meeting page | Notes left, transcript right | Overview, actions; Transcript and Notes pills | One document; transcript in a toggled panel | Summary tab and Transcript tab; right panel | Summary, Action Items, Transcript views |
| Fixing speakers | Click the name, apply to one or all | Write a note ("Speaker 1 is Daniel"), regenerate | Me/Them or names from the call platform; no rename control | Click to tag; applies everywhere and trains recognition | NV |
| Notes | Templates, section toggles, regenerate | Edit summary, regenerate | Editable; your own text marked; templates | Gist locked; outline and actions editable; templates | Custom instructions, regenerate |
| Tasks | Tasks page, assignee, checkbox | To-do list | A section inside the notes only | Cross-meeting list, assignee, checkbox | Checkbox, assign |
| Organisation | Channels, topic trackers | People, calendar | Folders, people, companies | Folders, channels | Folders, deals |
| Search and ask | Global search with filters; AskFred at three scopes | Search; ask one memory or all | Chat whose scope follows where you are | Chat that lists its sources | Ask at four scopes, plus keyword search |
| Verifying a note | Timestamped chapters link into the transcript | NV | Magnifying glass beside each point shows its source | "View in transcript" on each AI action item | Summary copies with links to moments (inferred) |
| Export | PDF, DOCX, SRT, CSV, JSON, Markdown | Share summary, with or without transcript | Markdown copy; bulk CSV | TXT, DOCX, PDF, SRT, MP3 | Clipboard only |
| Most common complaint | The visible bot and auto-join; metered AI | Speaker separation is paid | No audio kept, so nothing to re-listen to | Speakers mislabelled | Speakers mislabelled |

## Patterns most of them share

1. **The summary is the landing view**, with the transcript beside it or one click away. None open on the transcript.
2. **A fixed skeleton:** a short gist, then topic notes or a timestamped outline, then action items.
3. **Templates are prompts plus section toggles**, and applying one regenerates the notes. Regenerating is always a button, never automatic, and no product keeps the previous version.
4. **Speakers are corrected by clicking the label**, with "apply to all". The summary picks up new names only after a manual regenerate. This is the most complained-about area in every product.
5. **Provenance, not confidence scores.** A note links to the place in the transcript it came from (Granola's magnifier, Otter's "View in transcript", Fireflies' timestamped chapters). No product documents confidence marks.
6. **Chat scope follows location:** one meeting, a folder or channel, or everything. Otter and Granola show clickable sources.
7. **Action items are checkable and assignable; due dates are rare.** Fireflies and Otter add a list across meetings.
8. **An explicit transcript edit mode** (Fireflies, Otter) with find and replace. Granola and TwinMind treat the transcript as read-only.
9. **Export exposes speaker and timestamp toggles.** Only Fireflies and Granola offer Markdown.

For a local app, the most useful observation is Granola's weakness: it keeps no audio, so a reader cannot re-listen to check a note. An app that keeps the recording and lets a note jump to its moment covers the gap reviewers complain about.

## Fireflies.ai

- **Layout [D].** Left navigation: Home, AskFred, Meetings, Tasks, AI Skills, Analytics, Voice Agents, Integrations, Settings. Top bar: global search (Ctrl+K), a Capture menu, notifications. Home shows Daily Digest, Meeting Prep and Tasks cards with Recent, Upcoming and AI Feed tabs. ([home guide](https://guide.fireflies.ai/articles/8020055559-fireflies-welcome-screen-guide-new-home-dashboard))
- **Capture [D].** A bot joins from the calendar or a pasted link. The desktop app can record device audio with no bot, but then saves no audio and labels speakers only "Speaker 1/2" ([desktop guide](https://guide.fireflies.ai/articles/1208704416-getting-started-with-the-fireflies-desktop-app)). Uploads accept MP3, M4A, WAV, MP4, WEBM. During a meeting, Live Assist shows a live transcript with names and timestamps, an AI Notes tab, your own Notes tab, and prompt chips such as Catch Up and Action Items ([Live Assist](https://fireflies-knowledge-base.help.usepylon.com/articles/3499406277-how-to-use-fireflies-during-a-meeting)).
- **Meeting page [D].** Two panels: AI notes left, transcript right; either can expand to full screen. A collapsible rail holds Smart Search, Index, Soundbites, Comments and Bookmarks ([Notepad guide](https://guide.fireflies.ai/articles/6653885315-learn-about-the-fireflies-notepad)). Default summary sections in order: Keywords, Overview, Notes, Time-stamped Notes, Action Items ([summaries guide](https://guide.fireflies.ai/articles/9547055509-learn-about-the-fireflies-ai-meeting-summaries)). Audio or video plays in step with the transcript. Clicking a transcript line to seek: NV.
- **Transcript [D].** Click a speaker name, type the correct one, choose "apply to current speaker" or "apply to all Speaker X". The summary does not update until you regenerate ([speaker labels](https://guide.fireflies.ai/articles/4994477228-how-to-edit-speaker-labels-or-names-in-a-transcript)). Find or replace; an edit mode with undo and autosave; soundbites from highlighted text; timestamped comment threads; bookmarks.
- **Notes [D].** A template dropdown (General, 1:1, Standup, sales, custom), "Customize Notes" to tick sections, Concise or Detailed length, Regenerate in the menu. Direct editing of the AI summary: NV.
- **Tasks [D].** A Tasks page with My Tasks and All Tasks; editable text, assignee, checkbox with strikethrough. No due-date field documented ([Tasks feed](https://guide.fireflies.ai/articles/1574234155-learn-about-the-tasks-feed)).
- **Organisation [D].** Channels (My Meetings, All Meetings, Uploads, custom), bulk move and delete, Topic Trackers. No tags or folders documented.
- **Search [D].** Global search "by title or keyword"; whether transcript text is indexed is not stated. Meeting-list filters: host, participants, date range, duration, source. In-meeting Smart Search filters by questions, tasks, dates, metrics, sentiment, topics, speakers. AskFred works per meeting, per channel and globally; how it cites sources: NV. One review says search returns the matching sentence with its timestamp across calls [R] ([eesel](https://www.eesel.ai/blog/fireflies-ai-review)).
- **Export [D].** Transcript as PDF, DOCX, SRT, CSV, JSON, Markdown, with timestamp and speaker toggles; summary as DOCX, PDF, JSON, Markdown ([download guide](https://guide.fireflies.ai/articles/3319752033-how-to-download-transcripts-summaries-and-meeting-recordings-from-fireflies)).
- **Praise and complaints [R].** Praised: search across meetings, summaries that surface action items. Complaints: aggressive auto-join and the visible bot; speakers wrong in larger calls; AI features metered by credits.

## TwinMind

Documentation is thin: vendor "101" blog posts from September 2026.

- **Layout [B].** The mobile home has Memories (notes and digests grouped by day) and People, an orange Capture button, "Ask anything", and a search icon ([Mobile 101](https://twinmind.com/blogs/twinmind-101-mobile)). The web app's top bar: View Memories, View Digest, To-Do List, Transcribe ([Chrome extension 101](https://twinmind.com/blogs/twinmind-ce-101)).
- **Capture [B].** Phone microphone; the Chrome extension captures the microphone plus the tab's audio; the desktop app has a floating microphone, a hotkey, call detection and a calendar prompt ([Desktop](https://twinmind.com/blogs/twinmind-for-desktop)). While capturing on mobile: View Transcript (live), Add Text (your notes feed the summary), Pause, Stop. Audio is discarded unless "Save audio" is on.
- **Memory page [B].** Title and date, Transcript and Notes pills, an Overview of key takeaways, action items, then Share and "Ask about this". Playback only if audio was saved.
- **Transcript [B].** Speaker separation runs after capture, only with saved audio (paid), and yields "Speaker 1/2". There is no rename control: you add a note such as "Speaker 1 is Daniel" and press Regenerate ([Save audio post](https://twinmind.com/blogs/save-audio-and-identify-speakers)). Timestamps, editing, highlights: NV.
- **Notes [B].** A menu offers Edit Title, Edit Summary, Delete. Custom instructions or templates shape the summary; Regenerate exists.
- **To-dos [B].** Action items per memory, and a To-Do List in the web top bar. Tasks reportedly carry deadlines, priorities and status.
- **Organisation [B].** Memories by day, People cards, Google Calendar. Folders and tags: NV.
- **Search and chat [B].** A search icon over past captures; "Ask about this" for one memory and "Ask anything" across all, with chat history. Citations: NV.
- **Export [B].** Share the summary, with or without the transcript. File formats: NV.
- **Praise and complaints [R].** Praised: generous free transcription, a minimal interface. Complaints: speaker separation behind the paid tier (weak sourcing).

## Granola

- **Layout [D].** Home lists "Coming up" (calendar events; clicking one creates a note) and "Your notes". The sidebar has My notes and a team space, each with folders, and closes when a note opens. An "Ask anything" bar sits at the bottom of every screen ([Granola 101](https://docs.granola.ai/help-center/getting-started/granola-101.md)).
- **Capture [D].** The desktop app captures system audio plus the microphone, with no bot. Transcription starts only when you open a note. No audio is stored and file upload is not supported. During the meeting you type in a notepad; a button toggles the live transcript panel ([Transcription](https://docs.granola.ai/help-center/taking-notes/transcription.md)).
- **Note page [D].** One document. After the call it becomes "enhanced notes" under template-defined headings; a control switches back to your raw notes. The transcript is a toggled panel of chat bubbles: grey on the left for system audio, green on the right for your microphone. No player.
- **Transcript [D].** "Me" and "Them" by default; names come from the call platform where available. No rename control ([Speaker tags](https://docs.granola.ai/help-center/taking-notes/speaker-attribution.md)). Copy all or part, delete chunks, search within it.
- **Notes [D].** Your typed text stays black inside the enhanced notes, with AI text styled differently. The notes are directly editable; one control picks a template and another regenerates. Templates are prompts ([Enhanced notes](https://docs.granola.ai/help-center/taking-notes/ai-enhanced-notes.md)).
- **Action items.** Only a section in the notes when the template asks for one. No task objects, owners or due dates.
- **Organisation [D].** Folders (one level of nesting; a note can sit in several; recurring meetings can be filed automatically), People and Companies views built from attendees.
- **Search and chat [D].** Chat scope follows where you are: all notes, one meeting, a folder, ticked meetings, a person or company. Saved prompts are called Recipes ([Chat](https://docs.granola.ai/help-center/getting-more-from-your-notes/chatting-with-your-meetings.md)). Keyword search over notes: no help page found.
- **Verifying [D].** A magnifying glass beside each enhanced-note point shows where in the transcript or raw notes it came from ([Sharing](https://docs.granola.ai/help-center/sharing/sharing-notes.md)).
- **Export [D].** "Copy enhanced notes" gives Markdown; the transcript copies separately; bulk export is CSV by email ([Exporting](https://docs.granola.ai/help-center/sharing/exporting-notes.md)).
- **Praise and complaints [R].** Praised: minimal, fast, built around what you typed. Complaints: no audio to re-listen to; weaker speaker attribution with three or more people ([Layer3 Labs](https://www.layer3labs.io/guides/granola-ai-review)).

## Otter.ai

- **Layout [D].** Home has Calendar and Action Items tabs. Left navigation includes My Conversations, All Conversations, Channels and Folders. Ctrl/Cmd+K opens search and ask ([Action Items](https://help.otter.ai/hc/en-us/articles/25983095114519-Action-Items-Overview)).
- **Capture [D].** A bot for Zoom, Meet and Teams; a desktop app that records without a bot; mobile and web recording; file import. The transcript appears in real time, and you can highlight, comment and add images while recording.
- **Conversation page [D].** Two tabs. **Summary:** Overview, Action Items, Outline, and template-driven Insights. **Transcript:** keywords and each speaker's share of talk time at the top, the transcript, a "Show only highlights" toggle, and a playback bar. A right panel holds AI Chat, Outline and Comments ([Conversation Page](https://help.otter.ai/hc/en-us/articles/5093228433687-Conversation-Page-Overview)).
- **Transcript [D].** Click a speaker icon and pick a suggested, existing or new speaker. Tagging one "Speaker 2" retags all of them and trains future recognition; "Rematch" re-runs identification on old conversations ([Tagging speakers](https://help.otter.ai/hc/en-us/articles/360048465453-Tagging-speaker-names-in-a-conversation)). An explicit Edit mode; edited text is realigned to the audio. Highlights, comments with mentions, reactions.
- **Notes [D].** The gist is not editable; Action Items and Outline are. Regenerate is in the menu and keeps no previous version. Free-text user notes were removed.
- **Action items [D].** Assigned to people automatically; add, rename, assign, delete; a checkbox moves an item to Completed. Home lists items assigned to you across conversations. Due dates: not documented.
- **Search and chat [D].** AI Chat on Home, in a conversation and in a Channel; "Add context" scopes it; each answer lists its sources, clickable ([AI Chat](https://help.otter.ai/hc/en-us/articles/19682180167575-Otter-AI-Chat-Overview)).
- **Verifying [D].** AI action items have a "View in transcript" icon.
- **Export [D].** Clipboard, TXT, DOCX, PDF, SRT, MP3, with options for speaker names, timestamps, highlights, and merging same-speaker paragraphs ([Export](https://help.otter.ai/hc/en-us/articles/360047733634-Export-conversations)).
- **Praise and complaints [R].** Praised: a speaker rename that applies everywhere; playback speed and skip-silence. Complaints: mislabelled speakers in group calls; manual transcript cleanup.

## Fathom

The least documented for layout; treat as partial.

- **Layout [D].** My Calls and Team Calls lists with an Ask Fathom panel on the right; Folders have their own tab ([Ask Fathom](https://help.fathom.video/en/articles/3239425)).
- **Capture.** A bot, or bot-free capture in the Mac app; iOS for in-person meetings. The desktop app shows a summary building live and a personal scratchpad [B] ([What's new](https://www.fathom.ai/whats-new)).
- **Call page [D].** The recording with Summary, Action Items and Transcript views; Ask Fathom to the right; highlights listed on the right.
- **Transcript [D].** Hover a transcript block and click the plus to make a typed highlight; drag to resize; share as a clip link ([highlights](https://help.fathom.video/en/articles/295680)).
- **Notes [D].** A summary-type picker; a gear adds custom instructions; "Regenerate Summary", then "Apply to Future Summaries" ([Customizing summaries](https://help.fathom.video/en/articles/3239809)).
- **Search and chat [D].** Ask Fathom at call, folder, deal and account scope; keyword search over titles, participants and transcripts was added in October 2026. Chat history is not saved.
- **Export [D].** The transcript copies to the clipboard only; no file download ([transcript](https://help.fathom.video/en/articles/296000)).
- **Praise and complaints [R].** Praised: one-click highlights. Complaints: speaker mislabels in large calls.

"""What was done before the project went to a public repository (2026-11-20), kept as a record.

Nothing about the owner's clients, colleagues or folders stays in the source:

  - `workers/mitra_workers/library.py` reads project spellings and the archive's location from the
    owner's own files (`~/.mitra/twinmind/project_names.json`, and `meeting_archive` in
    `~/.mitra/config.json`). They used to be written in the code.
  - The tests' fixtures use made-up companies and people.
  - `.gitignore` leaves out models, runtimes, build output, binaries and another project's source zip.

The first version of this script carried the real names it was replacing, and was itself pushed.
That commit was rewritten the same day. The names are now only on the owner's machine, in
`~/.mitra/twinmind/redact_extra.json`, which `check_public_tree.py` and `export_conversation.py` read.
"""
print(__doc__)

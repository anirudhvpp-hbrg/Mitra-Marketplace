"""Mitra workers: all logic that is not serving files. Each request starts a fresh process
(`python -m mitra_workers.dispatch`) that exits when it has answered, so nothing here is ever
resident in memory between uses. Standard library only, apart from pypdf for PDF text."""

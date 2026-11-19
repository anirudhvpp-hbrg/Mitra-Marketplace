"""On Windows a file cannot be replaced while another process has it open for reading. The launcher
reads a job's file every time the page polls, so now and then a worker's save of that file was
refused ([WinError 5]) and the whole job failed (seen in T341 on 2026-11-14; very likely the cause
of the intermittent T227 failure of 2026-11-13). Every atomic save now retries for up to two seconds.
Run once from the project root."""
from pathlib import Path
p = Path("workers/mitra_workers/paths.py"); s = p.read_text("utf-8")
assert "def replace(" not in s
s += '''

def replace(tmp: Path, dest: Path) -> None:
    """Put `tmp` in place of `dest`. On Windows this is refused while another process is reading
    `dest` (the launcher reads a job's file whenever the page polls), so try again for two seconds."""
    import time
    for attempt in range(40):
        try:
            tmp.replace(dest)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05)
'''
p.write_text(s, "utf-8")
for path, a, b in [
    ("workers/mitra_workers/jobs.py", "        tmp.replace(self.file)", "        paths.replace(tmp, self.file)"),
    ("workers/mitra_workers/work.py", "        tmp.replace(self.dir / f\"{name}.json\")", "        paths.replace(tmp, self.dir / f\"{name}.json\")"),
    ("apps/twinmind/worker.py", "    tmp.replace(f)\n", "    paths.replace(tmp, f)\n"),
]:
    f = Path(path); s = f.read_text("utf-8"); assert s.count(a) == 1, path; f.write_text(s.replace(a, b), "utf-8")
print("ok")

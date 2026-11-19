"""One-off: brings APP_SPEC.md up to version 0.7.0 (the "opens" key, mitra.accept, drop routes)."""
import pathlib

p = pathlib.Path(__file__).resolve().parents[2] / "APP_SPEC.md"
s = p.read_text("utf-8")


def swap(old, new):
    global s
    assert old in s, old[:50]
    s = s.replace(old, new, 1)


swap('  "uses": ["convert"]\n}', '  "uses": ["convert"],\n  "opens": [".pdf"]\n}')
swap("- `glyph`: the app's icon,",
     "- `opens`: the file types this app opens, as extensions (`\".pdf\"`). A file of that type dropped on the launcher or on another app's window "
     "is sent here, and `mitra-marketplace register` offers this app for it under Windows' \"Open with\" and Default apps. `\"*\"` means "
     "\"anything no other app claims\". Leave it empty for an app that opens no files.\n\n- `glyph`: the app's icon,")
swap("| `mitra.home(page)` |",
     "| `mitra.accept = {exts, open(path, name)}` | Say what this window takes when a file is dropped on it: `exts` is a list of extensions, or `null` for anything. "
     "`open` receives a path to read and the file's own name. Without it, dropped files go to the app whose manifest lists the type. |\n"
     "| `mitra.openFile(file)` | Open a browser `File` (from a file picker) the same way as a dropped one. |\n| `mitra.home(page)` |")
swap("Endpoints: `GET /api/jobs/{id}` and the file browser are open to every app;",
     "A file arrives in a page in one of two ways, and both reach the same code: `?path=...` in the address (from the launcher, the command line, "
     "Explorer) and `mitra.accept.open` (dropped). A dropped file also carries `?name=...` when it starts the app, because its path is a temporary copy.\n\n"
     "Endpoints: `GET /api/opens` (extension to apps) and `POST /api/drop/{app}?name=` (keep a dropped file and hand it to that app) are open to every process; "
     "`GET /api/jobs/{id}` and the file browser are open to every app;")
p.write_text(s, "utf-8")
print("spec updated")

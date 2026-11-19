# Writing a Mitra app

An app is a folder. Built-in apps live in `apps/`; apps you create live in `~/.mitra/apps/`.

```
my-app/
  mitra.app.json     required: what the app is and what it needs
  ui/index.html      optional: its interface (without it, the generic workspace is used)
  worker.py          optional: its own logic, run on demand
```

## mitra.app.json

```json
{
  "id": "my-app",
  "name": "My App",
  "glyph": "doc",
  "category": "Documents",
  "description": "One sentence shown beside the app's icon.",
  "connectors": [{"type": "dropbox", "path": "Mitra/MyApp", "mode": "readwrite"}],
  "needs": ["assistant"],
  "uses": ["convert"],
  "opens": [".pdf"]
}
```

Each app is its own program. Clicking its icon starts `mitra-marketplace app my-app`: a separate process on its own port, shown in its own window, which ends a few seconds after the window closes. The port is the same each time the app starts (worked out from the app's id; any free port if that one is taken), so what the page keeps in `localStorage` survives closing and reopening it. The theme is kept in a cookie, which every port shares. That process serves this app's screen and routes and nothing else. The launcher has no capabilities of its own, and one app's process refuses requests meant for another.

- `uses`: shared services the app's process may call. `convert` allows `/api/convert`, `/api/convert/save` and `/api/upload`. Leave it empty if the app reads no documents. The assistant route (`/api/ask`) is allowed only when `needs` contains `assistant`.

- `opens`: the file types this app opens, as extensions (`".pdf"`). A file of that type dropped on the launcher or on another app's window is sent here, and `mitra-marketplace register` offers this app for it under Windows' "Open with" and Default apps. `"*"` means "anything no other app claims". Leave it empty for an app that opens no files.

- `glyph`: the app's icon, one of `doc`, `pdf`, `convert`, `chat`, `mic`, `book`, `code`, `coin`, `app`. Icons are one drawn SVG set so they look the same on every device; do not use emoji.
- `tagline`: optional, three or four words under the icon saying what the app is for ("Meetings into memos"). Without it the line under the icon says how many models the app uses.
- `connectors`: `dropbox` (a path inside the locally synced Dropbox folder) or `folder` (any local path). Mitra resolves them per device; on a device with no Dropbox client, set `connectors.dropbox` in `~/.mitra/config.json`.
- `needs`: capabilities from `catalog.json`, never model names. Leave it empty unless the app has a specific job for a model. Mitra picks the best candidate on the device that fits `model_budget_mb`.

## ui/index.html

Include the stylesheet and the SDK; the SDK adds the top bar, RAM pill and Manager button, and logs open and close.

```html
<link rel="stylesheet" href="/static/mitra.css">
<script src="/static/sdk.js"></script>
<script>
mitra.ready.then((app) => { /* app is the resolved manifest */ });
</script>
```

| SDK call | What it does |
|---|---|
| `mitra.icon(name)`, `mitra.glyph(name)` | An inline SVG icon, or the icon in its rounded tile. |
| `mitra.palette()` | Open the Ctrl+K command palette. |
| `mitra.log(type, data)` | Append an event to the memory log. Use `action.*` for things the user did. |
| `mitra.api(path, {body})` | Call the server; throws with the server's message and logs the error. |
| `mitra.browser(el, {exts, onPick, start})` | The shared file browser, with recent files from the memory log. |
| `mitra.md(markdown, baseDir)` | Render Markdown to HTML. |
| `mitra.fileUrl(path)` | URL that serves a local file (supports seeking). |
| `mitra.launch(id, {path})` | Start another app in its own process and window, optionally on a file. A plain link to `/apps/other/` does the same. |
| `mitra.accept = {exts, open(path, name)}` | Say what this window takes when a file is dropped on it: `exts` is a list of extensions, or `null` for anything. `open` receives a path to read and the file's own name. Without it, dropped files go to the app whose manifest lists the type. |
| `mitra.openFile(file)` | Open a browser `File` (from a file picker) the same way as a dropped one. |
| `mitra.home(page)` | Show the launcher, optionally on `create`, `memory` or `system`. |

A file arrives in a page in one of two ways, and both reach the same code: `?path=...` in the address (from the launcher, the command line, Explorer) and `mitra.accept.open` (dropped). A dropped file also carries `?name=...` when it starts the app, because its path is a temporary copy.

Endpoints: `GET /api/opens` (extension to apps) and `POST /api/drop/{app}?name=` (keep a dropped file and hand it to that app) are open to every process; `GET /api/jobs/{id}` and the file browser are open to every app; `GET /api/convert?path=` (any file to Markdown) and `POST /api/upload?name=` need `"uses": ["convert"]`; `POST /api/ask` (`{app_id, prompt, system}`) needs `assistant` in `needs`.

### Look and brand

Use the tokens in `mitra.css`; do not hard-code colours. Navy carries structure and text, saffron and amber are for the one primary action on a screen and for "live" state, nothing else. The logo is the `.logo` class (the SDK puts it in the top bar): it keeps its proportions, is never recoloured, and uses the colour variant on light and the tint variant on dark. Headings use `var(--serif)`, everything else `var(--sans)`. Keep touch targets at 44 px on phones and leave focus rings visible.

## worker.py

```python
from mitra_workers import models, memory, paths

def status(req):                 # GET /api/apps/my-app/status
    return {"ok": True}

def run(req):                    # POST /api/apps/my-app/job/run  -> returns {id}, poll /api/jobs/{id}
    req.job.step("thinking", "running")
    with models.Assistant("my-app") as a:      # loads once, unloads when the block ends
        text = a.chat("…")["text"]
    req.job.step("thinking", "done")
    return {"text": text}

ROUTES = {("GET", "status"): status, ("POST", "job/run"): run}
```

- A worker is a fresh process per request and exits when it returns. Keep nothing in memory between calls; write state to files.
- Routes under `job/` run detached; report progress with `req.job.step(stage, status, note)`.
- `APP` (the app object) is injected into the module: `APP.manifest`, `APP.dir`, `APP.public()`.
- Every model goes through `mitra_workers.models`, which starts it under the governor. Do not start model processes directly.
- Use the standard library. A dependency that needs compiling will not install on Termux.

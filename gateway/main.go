// mitra-marketplace: one command that opens your local app suite in the browser.
//
// This binary is the only part of Mitra that stays running, and it is deliberately thin:
// it serves the web UI and files, appends to the memory log, and starts everything else on
// demand. Logic runs in Python workers that exit when the request is done; models run under
// the Rust governor. With no browser tab talking to it, it shuts itself down.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const version = "0.10.0"

var (
	root, home   string
	cfg          = map[string]any{}
	activeJobs  atomic.Int32
	workerLast   atomic.Int64 // peak MB of the most recent worker
	workerMax    atomic.Int64 // largest worker peak since the server started
	logMu        sync.Mutex
	sysMu        sync.Mutex
	sysCache     map[string]any
	sysAt        time.Time
	history      []float64
	httpServer   *http.Server
)

// ---- locations and config ---------------------------------------------------------------

func initPaths() {
	root = os.Getenv("MITRA_ROOT")
	if root == "" {
		exe, _ := os.Executable()
		exe, _ = filepath.EvalSymlinks(exe)
		root = filepath.Dir(filepath.Dir(exe)) // <root>/bin/mitra-marketplace
	}
	home = os.Getenv("MITRA_HOME")
	if home == "" {
		h, _ := os.UserHomeDir()
		home = filepath.Join(h, ".mitra")
	}
	for _, d := range []string{"apps", "memory/events", "memory/reports", "memory/rollups", "memory/archive", "tmp", "run/jobs", "run/apps", "logs"} {
		os.MkdirAll(filepath.Join(home, filepath.FromSlash(d)), 0o755)
	}
	if b, err := os.ReadFile(filepath.Join(home, "config.json")); err == nil {
		json.Unmarshal(b, &cfg)
	}
}

func cfgInt(key string, def int) int {
	if v, ok := cfg[key].(float64); ok {
		return int(v)
	}
	return def
}

func cfgFloat(key string, def float64) float64 {
	if v, ok := cfg[key].(float64); ok {
		return v
	}
	return def
}

func cfgStr(key, def string) string {
	if v, ok := cfg[key].(string); ok && v != "" {
		return v
	}
	return def
}

func baseURL() string { return fmt.Sprintf("http://127.0.0.1:%d", cfgInt("port", 7421)) }

func bin(name string) string {
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	return filepath.Join(root, "bin", name)
}

func python() string {
	if p := cfgStr("python", ""); p != "" {
		return p
	}
	for _, c := range []string{"python3", "python"} {
		if p, err := exec.LookPath(c); err == nil {
			return p
		}
	}
	return "python"
}

func tzOffsetMin() string {
	_, off := time.Now().Zone()
	return fmt.Sprint(off / 60)
}

func childEnv() []string {
	return append(os.Environ(),
		"MITRA_ROOT="+root, "MITRA_HOME="+home, "MITRA_GOVERNOR="+bin("mitra-governor"),
		"MITRA_TZ_OFFSET_MIN="+tzOffsetMin(), "PYTHONPATH="+filepath.Join(root, "workers"),
		"PYTHONIOENCODING=utf-8", "PYTHONUTF8=1", "MITRA_APP="+appMode)
}

// ---- memory log -------------------------------------------------------------------------

func logEvent(app, kind string, data any, session string) {
	now := time.Now()
	rec := map[string]any{"ts": now.Format("2006-01-02T15:04:05"), "app": app, "type": kind}
	if session != "" {
		rec["session"] = session
	}
	if data != nil {
		rec["data"] = data
	}
	line, _ := json.Marshal(rec)
	logMu.Lock()
	defer logMu.Unlock()
	f, err := os.OpenFile(filepath.Join(home, "memory", "events", now.Format("2006-01-02")+".jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	f.Write(append(line, '\n'))
}

// ---- helpers ----------------------------------------------------------------------------

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"detail": msg})
}

// serveUnder serves rel from base and refuses anything that escapes it.
func serveUnder(w http.ResponseWriter, r *http.Request, base, rel string) {
	if rel == "" {
		rel = "index.html"
	}
	full := filepath.Join(base, filepath.FromSlash(rel))
	if relp, err := filepath.Rel(base, full); err != nil || strings.HasPrefix(relp, "..") {
		fail(w, 404, "Not found")
		return
	}
	if st, err := os.Stat(full); err != nil || st.IsDir() {
		fail(w, 404, "Not found")
		return
	}
	http.ServeFile(w, r, full)
}

func appDir(id string) string {
	if id == "" || strings.ContainsAny(id, `/\.`) {
		return ""
	}
	for _, base := range []string{filepath.Join(root, "apps"), filepath.Join(home, "apps")} {
		d := filepath.Join(base, id)
		if _, err := os.Stat(filepath.Join(d, "mitra.app.json")); err == nil {
			return d
		}
	}
	return ""
}

func dropboxRoot() string {
	if c, ok := cfg["connectors"].(map[string]any); ok {
		if p, ok := c["dropbox"].(string); ok && p != "" {
			return p
		}
	}
	h, _ := os.UserHomeDir()
	candidates := []string{filepath.Join(h, ".dropbox", "info.json")}
	for _, e := range []string{"LOCALAPPDATA", "APPDATA"} {
		if v := os.Getenv(e); v != "" {
			candidates = append(candidates, filepath.Join(v, "Dropbox", "info.json"))
		}
	}
	for _, c := range candidates {
		if b, err := os.ReadFile(c); err == nil {
			var info map[string]map[string]any
			if json.Unmarshal(b, &info) == nil {
				for _, k := range []string{"personal", "business"} {
					if p, ok := info[k]["path"].(string); ok {
						return p
					}
				}
			}
		}
	}
	return filepath.Join(h, "Dropbox")
}

// ---- Python workers: started per request, gone when it returns --------------------------

type workerReq struct {
	Method string            `json:"method"`
	Path   string            `json:"path"`
	Query  map[string]string `json:"query"`
	Body   string            `json:"body"`
	Job    string            `json:"job,omitempty"`
}

// A worker answering a request is tied to that request: if the page gives up (a cancelled
// question), the worker is stopped, and the governor it started sees its caller gone and leaves
// the line for the model. A job is tied to nothing and outlives the request that started it.
func workerCmd(ctx context.Context, req workerReq) *exec.Cmd {
	cmd := exec.CommandContext(ctx, python(), "-m", "mitra_workers.dispatch")
	payload, _ := json.Marshal(req)
	cmd.Stdin = bytes.NewReader(payload)
	cmd.Env = childEnv()
	cmd.Dir = root
	hide(cmd)
	return cmd
}

func toWorkerReq(r *http.Request, job string) workerReq {
	q := map[string]string{}
	for k, v := range r.URL.Query() {
		q[k] = v[0]
	}
	body, _ := io.ReadAll(io.LimitReader(r.Body, 64<<20))
	return workerReq{Method: r.Method, Path: r.URL.Path, Query: q, Body: string(body), Job: job}
}

func handleWorker(w http.ResponseWriter, r *http.Request) {
	t0 := time.Now()
	cmd := workerCmd(r.Context(), toWorkerReq(r, ""))
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	var res struct {
		Status int             `json:"status"`
		Body   json.RawMessage `json:"body"`
		PeakMB int64           `json:"peak_mb"`
	}
	if jerr := json.Unmarshal(out, &res); jerr != nil || res.Status == 0 {
		msg := strings.TrimSpace(stderr.String())
		if len(msg) > 600 {
			msg = msg[len(msg)-600:]
		}
		if msg == "" && err != nil {
			msg = err.Error()
		}
		logEvent("shell", "error", map[string]any{"msg": "worker failed: " + msg, "path": r.URL.Path}, "")
		fail(w, 500, "Worker failed: "+msg)
		return
	}
	// Every request's cost is recorded: how long the worker ran and the most RAM it held.
	workerLast.Store(res.PeakMB)
	for {
		cur := workerMax.Load()
		if res.PeakMB <= cur || workerMax.CompareAndSwap(cur, res.PeakMB) {
			break
		}
	}
	// Whatever a process does is that app's cost: an app's process logs under the app's name.
	owner, path := "shell", strings.TrimPrefix(r.URL.Path, "/api/")
	if appMode != "" {
		owner = appMode
		path = strings.TrimPrefix(path, "apps/"+appMode+"/")
	}
	logEvent(owner, "api.call", map[string]any{"path": path, "status": res.Status, "ms": time.Since(t0).Milliseconds(), "worker_mb": res.PeakMB}, "")
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(res.Status)
	w.Write(res.Body)
}

// The job workers this process started and that are still at work.
var (
	jobMu    sync.Mutex
	jobProcs = map[string]*os.Process{}
)

// stopJobs ends every job this process started: used when the app itself is told to close, so no
// worker is left running with no app. What each job had finished stays on disk and can be resumed.
func stopJobs() {
	jobMu.Lock()
	defer jobMu.Unlock()
	for id, p := range jobProcs {
		p.Kill()
		f := filepath.Join(home, "run", "jobs", id+".json")
		var j map[string]any
		if b, err := os.ReadFile(f); err == nil && json.Unmarshal(b, &j) == nil && (j["status"] == "running" || j["status"] == nil) {
			j["status"] = "stopped"
			if b, err := json.Marshal(j); err == nil {
				os.WriteFile(f, b, 0o644)
			}
		}
		logEvent(appMode, "job.stopped", map[string]any{"job": id, "how": "its app was closed"}, "")
	}
}

// A job is a worker that keeps running after the request returns; the browser polls its file.
func handleJobStart(w http.ResponseWriter, r *http.Request) {
	id := fmt.Sprintf("%x", time.Now().UnixNano())
	cmd := workerCmd(context.Background(), toWorkerReq(r, id))
	logf, _ := os.OpenFile(filepath.Join(home, "run", "jobs", id+".log"), os.O_CREATE|os.O_WRONLY, 0o644)
	cmd.Stdout, cmd.Stderr = logf, logf
	if err := cmd.Start(); err != nil {
		fail(w, 500, "Could not start job: "+err.Error())
		return
	}
	activeJobs.Add(1)
	jobMu.Lock()
	jobProcs[id] = cmd.Process
	jobMu.Unlock()
	go func() {
		cmd.Wait()
		logf.Close()
		jobMu.Lock()
		delete(jobProcs, id)
		jobMu.Unlock()
		activeJobs.Add(-1)
		lastReq.Store(time.Now().UnixNano())
	}()
	writeJSON(w, 200, map[string]string{"id": id})
}

// ---- governor ---------------------------------------------------------------------------

func governor(args ...string) (map[string]any, error) {
	cmd := exec.Command(bin("mitra-governor"), args...)
	cmd.Env = childEnv()
	hide(cmd)
	out, err := cmd.Output()
	if err != nil {
		return nil, err
	}
	var v map[string]any
	return v, json.Unmarshal(out, &v)
}

func systemStatus() map[string]any {
	sysMu.Lock()
	defer sysMu.Unlock()
	if sysCache != nil && time.Since(sysAt) < 2*time.Second {
		return sysCache
	}
	s, err := governor("status")
	if err != nil {
		return map[string]any{"error": "governor not available: " + err.Error(), "ram": map[string]any{"pct": 0, "total_mb": 0, "used_mb": 0, "free_mb": 0},
			"state": "ok", "leases": []any{}, "limits": map[string]any{}, "history": []float64{}}
	}
	if ram, ok := s["ram"].(map[string]any); ok {
		if p, ok := ram["pct"].(float64); ok {
			history = append(history, p)
			if len(history) > 120 {
				history = history[1:]
			}
		}
	}
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	s["history"] = history
	s["gateway_mb"] = m.Sys / (1 << 20)
	s["app"] = appMode
	s["worker_last_mb"] = workerLast.Load()
	s["worker_max_mb"] = workerMax.Load()
	s["idle_exit_min"] = cfgFloat("idle_exit_min", 10)
	s["jobs"] = activeJobs.Load()
	sysCache, sysAt = s, time.Now()
	return s
}

// ---- server -----------------------------------------------------------------------------

func isLocal(host string) bool {
	h := strings.Split(host, ":")[0]
	return h == "127.0.0.1" || h == "localhost"
}

func guard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Only this device's browser, and only pages Mitra itself served, may call in.
		// A refusal still reads the (small) body first; closing with unread data makes the
		// connection reset and the caller never sees the 403.
		refuse := func(why string) {
			io.Copy(io.Discard, io.LimitReader(r.Body, 1<<20))
			fail(w, 403, why)
		}
		if !isLocal(r.Host) {
			refuse("bad host")
			return
		}
		if o := r.Header.Get("Origin"); o != "" && r.Method != "GET" {
			if u, err := url.Parse(o); err != nil || !isLocal(u.Host) {
				refuse("bad origin")
				return
			}
		}
		// Being asked "are you there?" is not use. The launcher asks every running app that
		// every few seconds; if it counted, an app whose window had closed would never end.
		if r.URL.Path != "/api/ping" {
			lastReq.Store(time.Now().UnixNano())
		}
		reqCount.Add(1)
		inflight.Add(1)
		defer inflight.Add(-1)
		if status, why := scope(r); status != 0 {
			io.Copy(io.Discard, io.LimitReader(r.Body, 1<<20))
			fail(w, status, why)
			return
		}
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Cross-Origin-Resource-Policy", "same-origin")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		next.ServeHTTP(w, r)
	})
}

func routes() http.Handler {
	mux := http.NewServeMux()
	web := filepath.Join(root, "web")

	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		if appMode != "" { // an app's process has one page: the app
			http.Redirect(w, r, "/apps/"+appMode+"/", http.StatusFound)
			return
		}
		serveUnder(w, r, web, "index.html")
	})
	mux.HandleFunc("GET /static/{rest...}", func(w http.ResponseWriter, r *http.Request) {
		serveUnder(w, r, filepath.Join(web, "static"), r.PathValue("rest"))
	})
	mux.HandleFunc("GET /apps/{id}", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/apps/"+r.PathValue("id")+"/", http.StatusFound)
	})
	mux.HandleFunc("GET /apps/{id}/{rest...}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		dir := appDir(id)
		if dir == "" {
			fail(w, 404, "No such app")
			return
		}
		if appMode == "" {
			// The launcher never serves an app's screen. Asking it for one starts that app's
			// own process and sends the browser there.
			info, _, err := spawnApp(id)
			if err != nil {
				fail(w, 500, err.Error())
				return
			}
			http.Redirect(w, r, fmt.Sprintf("http://127.0.0.1:%d%s", info.Port, r.URL.RequestURI()), http.StatusFound)
			return
		}
		if id != appMode {
			fail(w, 404, "This process is "+appMode+" only.")
			return
		}
		base := filepath.Join(dir, "ui")
		if _, err := os.Stat(base); err != nil {
			base = filepath.Join(web, "generic") // apps created from a prompt start on the generic workspace
		}
		serveUnder(w, r, base, r.PathValue("rest"))
	})

	processRoutes(mux)
	fileRoutes(mux)
	meetRoutes(mux)
	mux.HandleFunc("POST /api/log", func(w http.ResponseWriter, r *http.Request) {
		var e struct {
			App, Type, Session string
			Data               any
		}
		if json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&e) != nil || e.Type == "" {
			fail(w, 400, "bad event")
			return
		}
		if e.App == "" {
			e.App = "shell"
		}
		logEvent(e.App, e.Type, e.Data, e.Session)
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
	mux.HandleFunc("GET /api/system", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, systemStatus()) })
	mux.HandleFunc("POST /api/system/evict", func(w http.ResponseWriter, r *http.Request) {
		v, _ := governor("kill")
		writeJSON(w, 200, v)
	})

	mux.HandleFunc("GET /api/fs/roots", func(w http.ResponseWriter, r *http.Request) {
		h, _ := os.UserHomeDir()
		type rt struct {
			Name string `json:"name"`
			Path string `json:"path"`
		}
		out := []rt{}
		add := func(name, p string) {
			if st, err := os.Stat(p); p != "" && err == nil && st.IsDir() {
				out = append(out, rt{name, p})
			}
		}
		add("Home", h)
		add("Dropbox", dropboxRoot())
		add("Documents", filepath.Join(h, "Documents"))
		add("Downloads", filepath.Join(h, "Downloads"))
		add("Desktop", filepath.Join(h, "Desktop"))
		add("Phone storage", filepath.Join(h, "storage", "shared"))
		if runtime.GOOS == "windows" {
			for _, c := range "CDEFGH" {
				add(string(c)+":", string(c)+`:\`)
			}
		} else {
			add("/", "/")
		}
		writeJSON(w, 200, out)
	})
	mux.HandleFunc("GET /api/fs/list", func(w http.ResponseWriter, r *http.Request) {
		p, err := filepath.Abs(r.URL.Query().Get("path"))
		entries, err2 := os.ReadDir(p)
		if err != nil || err2 != nil {
			fail(w, 404, "Cannot open folder: "+r.URL.Query().Get("path"))
			return
		}
		type item struct {
			Name  string `json:"name"`
			Path  string `json:"path"`
			Dir   bool   `json:"dir"`
			Ext   string `json:"ext"`
			Size  int64  `json:"size"`
			Mtime int64  `json:"mtime"`
		}
		dirs, files := []item{}, []item{}
		for _, e := range entries {
			n := e.Name()
			if strings.HasPrefix(n, ".") || strings.HasPrefix(n, "$") || strings.HasPrefix(n, "~$") {
				continue
			}
			st, err := os.Stat(filepath.Join(p, n)) // follows links, so a linked folder lists as a folder
			if err != nil || hiddenEntry(e) {      // system and hidden entries (AppData, NetHood, desktop.ini) are not documents
				continue
			}
			it := item{Name: n, Path: filepath.Join(p, n), Dir: st.IsDir(), Ext: strings.ToLower(filepath.Ext(n)), Mtime: st.ModTime().Unix()}
			if it.Dir {
				dirs = append(dirs, it)
			} else {
				it.Size = st.Size()
				files = append(files, it)
			}
		}
		var parent any
		if d := filepath.Dir(p); d != p {
			parent = d
		}
		writeJSON(w, 200, map[string]any{"path": p, "parent": parent, "items": append(dirs, files...)})
	})
	serveFile := func(w http.ResponseWriter, r *http.Request) {
		p := r.URL.Query().Get("path")
		if st, err := os.Stat(p); err != nil || st.IsDir() {
			fail(w, 404, "Not a file: "+p)
			return
		}
		// inline, with the file's own name: the browser's viewer titles it and "Save" keeps the name
		w.Header().Set("Content-Disposition", mime.FormatMediaType("inline", map[string]string{"filename": filepath.Base(p)}))
		http.ServeFile(w, r, p) // supports range requests, so audio and large PDFs seek properly
	}
	mux.HandleFunc("GET /api/fs/file", serveFile)
	// the same, with the file's name as the last part of the address: Chrome's PDF viewer titles the
	// page from the address, not from the header ("file" otherwise). The name is cosmetic; path decides.
	mux.HandleFunc("GET /api/fs/file/{name}", serveFile)
	mux.HandleFunc("POST /api/upload", func(w http.ResponseWriter, r *http.Request) {
		name := filepath.Base(r.URL.Query().Get("name"))
		if name == "." || name == "" {
			name = "upload"
		}
		dst := filepath.Join(home, "tmp", fmt.Sprintf("%d-%s", time.Now().UnixMilli(), name))
		f, err := os.Create(dst)
		if err != nil {
			fail(w, 500, err.Error())
			return
		}
		defer f.Close()
		io.Copy(f, io.LimitReader(r.Body, 2<<30))
		writeJSON(w, 200, map[string]string{"path": dst, "name": name})
	})

	mux.HandleFunc("POST /api/apps/{id}/job/{name}", handleJobStart)
	mux.HandleFunc("GET /api/jobs/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if strings.ContainsAny(id, `/\.`) {
			fail(w, 400, "bad id")
			return
		}
		b, err := os.ReadFile(filepath.Join(home, "run", "jobs", id+".json"))
		if err != nil {
			writeJSON(w, 200, map[string]any{"id": id, "status": "starting", "steps": []any{}})
			return
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Write(b)
	})

	mux.HandleFunc("/api/", handleWorker) // everything else is logic, and logic lives in the workers
	return guard(mux)
}

// tune trades a little CPU for a smaller heap; these processes exist to be small.
func tune() {
	debug.SetGCPercent(25)
	debug.SetMemoryLimit(48 << 20)
}

// serve runs the launcher: the welcome screen, the icons, and the memory and system pages.
// No app's screen and no capability lives here.
func serve() {
	tune()
	lastReq.Store(time.Now().UnixNano())
	logEvent("shell", "server.start", map[string]any{"version": version, "os": runtime.GOOS, "arch": runtime.GOARCH}, "")
	go func() { // the optimizer: housekeeping at start and every six hours while running
		for {
			governor("optimize")
			time.Sleep(6 * time.Hour)
		}
	}()
	go watch(cfgFloat("idle_exit_min", 10) * 60)
	httpServer = &http.Server{Addr: fmt.Sprintf("127.0.0.1:%d", cfgInt("port", 7421)), Handler: routes()}
	if err := httpServer.ListenAndServe(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

// ---- CLI --------------------------------------------------------------------------------

func call(method, path string, payload any, timeout time.Duration) ([]byte, error) {
	var body io.Reader
	if payload != nil {
		b, _ := json.Marshal(payload)
		body = bytes.NewReader(b)
	}
	req, _ := http.NewRequest(method, baseURL()+path, body)
	req.Header.Set("Content-Type", "application/json")
	resp, err := (&http.Client{Timeout: timeout}).Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		var e struct{ Detail string }
		json.Unmarshal(b, &e)
		return b, fmt.Errorf("%s", e.Detail)
	}
	return b, nil
}

func running() bool {
	b, err := call("GET", "/api/ping", nil, time.Second)
	return err == nil && bytes.Contains(b, []byte(`"mitra":true`)) && bytes.Contains(b, []byte(`"app":""`))
}

func ensureRunning() {
	if running() {
		return
	}
	fmt.Println("Starting Mitra...")
	exe, _ := os.Executable()
	cmd := exec.Command(exe, "serve")
	logf, _ := os.OpenFile(filepath.Join(home, "logs", "launcher.log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	cmd.Stdout, cmd.Stderr = logf, logf
	cmd.Env = append(os.Environ(), "MITRA_ROOT="+root, "MITRA_HOME="+home)
	detach(cmd)
	if err := cmd.Start(); err != nil {
		fmt.Println("Could not start:", err)
		os.Exit(1)
	}
	for i := 0; i < 60; i++ {
		time.Sleep(150 * time.Millisecond)
		if running() {
			return
		}
	}
	fmt.Println("The launcher did not come up. See", filepath.Join(home, "logs", "launcher.log"))
	os.Exit(1)
}

func must(b []byte, err error) []byte {
	if err != nil {
		fmt.Println("Error:", err)
		os.Exit(1)
	}
	return b
}

func usage() {
	fmt.Print(`mitra-marketplace            open the welcome screen and your apps
mitra-marketplace open APP [FILE]   start one app in its own window, optionally on a file
mitra-marketplace apps       apps running now, each with its port and memory
mitra-marketplace close APP  stop one app
mitra-marketplace models [sync]   the models your apps use; sync copies them into this folder
mitra-marketplace size       what the whole package takes on disk
mitra-marketplace list       installed apps
mitra-marketplace new "PROMPT" [--yes]   create an app from a description
mitra-marketplace memory report [weekly|biweekly|monthly]
mitra-marketplace memory prune [DAYS_TO_KEEP]
mitra-marketplace status     RAM, the model running now, limits
mitra-marketplace optimize   housekeeping now: temp files, old job files, stale locks
mitra-marketplace stop       stop every app, the launcher and any running model
mitra-marketplace register [--desktop]   Windows: add the apps to the Start menu, "Open with" and Default apps
mitra-marketplace unregister  undo that

Across systems (shared folder, by default Dropbox/Mitra/releases):
mitra-marketplace push       pack this install into a versioned zip in the shared folder
mitra-marketplace update [--check]   install the newest zip from the shared folder
mitra-marketplace install [APP|ZIP]  search this system for Mitra zips and install them
mitra-marketplace releases [prune N] list releases; prune keeps the newest N
mitra-marketplace pack APP   zip one app for another system to install

mitra-marketplace test [--quick] [T012 ...]   run the test suite
`)
}

func main() {
	initPaths()
	args := os.Args[1:]
	cmd := ""
	if len(args) > 0 {
		cmd = args[0]
	}
	switch cmd {
	case "serve":
		serve()
	case "app": // one app, as its own process; this is what an icon starts
		if len(args) < 2 {
			usage()
			os.Exit(2)
		}
		serveApp(args[1])
	case "apps", "ps":
		list := runningApps()
		if len(list) == 0 {
			fmt.Println("No app is running.")
		}
		for _, a := range list {
			fmt.Printf("  %-18s pid %-7d %s  %d MB  since %s\n", a.ID, a.PID, a.URL, a.MB, a.Started)
		}
	case "close":
		if len(args) < 2 {
			usage()
			os.Exit(2)
		}
		if stopApp(args[1]) {
			fmt.Println("Closed", args[1]+".")
		} else {
			fmt.Println(args[1], "is not running.")
		}
	case "models", "size":
		c := exec.Command(python(), append([]string{"-m", "mitra_workers.bundle", cmd}, args[1:]...)...)
		c.Env = childEnv()
		c.Stdout, c.Stderr = os.Stdout, os.Stderr
		if err := c.Run(); err != nil {
			os.Exit(1)
		}
	case "register", "unregister":
		var err error
		if cmd == "register" {
			err = register(args[1:])
		} else {
			err = unregister()
		}
		if err != nil {
			fmt.Println("Error:", err)
			os.Exit(1)
		}
	case "help", "-h", "--help":
		usage()
	case "version", "--version":
		fmt.Println(version)
	case "stop":
		apps := runningApps()
		for _, a := range apps {
			stopApp(a.ID)
		}
		governor("kill")
		up := running()
		if up {
			call("POST", "/api/shutdown", map[string]any{}, 5*time.Second)
			for i := 0; i < 50 && running(); i++ { // return only once it is really gone, so a start right after is not fooled
				time.Sleep(100 * time.Millisecond)
			}
		}
		if up || len(apps) > 0 {
			fmt.Printf("Stopped. %d app(s) closed.\n", len(apps))
		} else {
			fmt.Println("Not running.")
		}
	case "status":
		s, err := governor("status")
		if err != nil {
			fmt.Println("Governor not available:", err)
			os.Exit(1)
		}
		ram := s["ram"].(map[string]any)
		fmt.Printf("Launcher: %v\nRAM: %v%% used (%v of %v MB), state %v\nLimits: %v\n", map[bool]string{true: "running at " + baseURL(), false: "not running (nothing in memory)"}[running()],
			ram["pct"], ram["used_mb"], ram["total_mb"], s["state"], s["limits"])
		leases, _ := s["leases"].([]any)
		if len(leases) == 0 {
			fmt.Println("Models loaded: none")
		}
		for _, l := range leases {
			m := l.(map[string]any)
			fmt.Printf("Model running: %v, %v MB (budget %v MB), used by %v\n", m["name"], m["mb"], m["budget_mb"], m["apps"])
		}
		apps := runningApps()
		if len(apps) == 0 {
			fmt.Println("Apps running: none")
		}
		for _, a := range apps {
			fmt.Printf("App running: %s, %d MB, %s\n", a.ID, a.MB, a.URL)
		}
	case "optimize":
		v, err := governor("optimize")
		if err != nil {
			fmt.Println("Governor not available:", err)
			os.Exit(1)
		}
		fmt.Printf("Removed %v old files (%v KB). Log rotated: %v. Stale lock cleared: %v. Model running: %v. RAM free: %v of %v MB.\n",
			v["files_removed"], v["freed_kb"], v["log_rotated"], v["stale_lock_cleared"], v["model_running"], v["ram_free_mb"], v["ram_total_mb"])
	case "push", "update", "install", "releases", "pack":
		var err error
		arg := ""
		if len(args) > 1 {
			arg = args[1]
		}
		switch cmd {
		case "push":
			err = push()
		case "update":
			err = update(arg == "--check")
		case "install":
			err = install(arg)
		case "pack":
			err = packApp(arg)
		case "releases":
			keep := 0
			if arg == "prune" {
				keep = 3
				if len(args) > 2 {
					fmt.Sscan(args[2], &keep)
				}
				if keep < 1 {
					keep = 1
				}
			}
			err = releases(keep)
		}
		if err != nil {
			fmt.Println("Error:", err)
			os.Exit(1)
		}
	case "test":
		c := exec.Command(python(), append([]string{filepath.Join(root, "logs", "tests", "run_tests.py")}, args[1:]...)...)
		c.Env = append(os.Environ(), "MITRA_ROOT="+root)
		c.Stdout, c.Stderr = os.Stdout, os.Stderr
		if err := c.Run(); err != nil {
			os.Exit(1)
		}
	case "", "home":
		ensureRunning()
		u := baseURL() + "/"
		if len(args) > 1 && args[1] != "" {
			u += "#" + args[1]
		}
		if openWindow(u) == "page" {
			fmt.Println("Open this in your browser:", u)
		} else {
			fmt.Println("Mitra is open at", u)
		}
	case "open":
		if len(args) < 2 {
			usage()
			os.Exit(2)
		}
		query := ""
		if len(args) > 2 {
			abs, _ := filepath.Abs(args[2])
			query = "path=" + url.QueryEscape(abs)
		}
		res, err := launch(args[1], query, true)
		if err != nil {
			fmt.Println("Error:", err)
			os.Exit(1)
		}
		if res["opened"] == "page" {
			fmt.Println("Open this in your browser:", res["url"])
		} else {
			fmt.Printf("%v is running at %v\n", args[1], res["url"])
		}
	case "list":
		ensureRunning()
		var apps []map[string]any
		json.Unmarshal(must(call("GET", "/api/apps", nil, 60*time.Second)), &apps)
		for _, a := range apps {
			fmt.Printf("  %-18v %-22v opens(30d)=%v\n", a["id"], a["category"], a["opens_30d"])
		}
	case "new":
		if len(args) < 2 {
			usage()
			os.Exit(2)
		}
		ensureRunning()
		draft := must(call("POST", "/api/builder/draft", map[string]any{"prompt": args[1]}, 60*time.Second))
		var pretty bytes.Buffer
		json.Indent(&pretty, draft, "", "  ")
		fmt.Println(pretty.String())
		yes := len(args) > 2 && args[2] == "--yes"
		if !yes {
			fmt.Print("\nCreate this app? [y/N] ")
			var ans string
			fmt.Scanln(&ans)
			yes = strings.ToLower(strings.TrimSpace(ans)) == "y"
		}
		if !yes {
			fmt.Println("Not created. You can edit the draft in the browser under Create.")
			return
		}
		var m any
		json.Unmarshal(draft, &m)
		var created map[string]any
		json.Unmarshal(must(call("POST", "/api/builder/create", map[string]any{"manifest": m}, 60*time.Second)), &created)
		fmt.Printf("Created %v at %v\n", created["id"], created["dir"])
	case "memory":
		if len(args) < 2 {
			usage()
			os.Exit(2)
		}
		ensureRunning()
		if args[1] == "prune" {
			keep := "90"
			if len(args) > 2 {
				keep = args[2]
			}
			var n int
			fmt.Sscan(keep, &n)
			fmt.Println(string(must(call("POST", "/api/memory/prune", map[string]any{"keep_days": n}, 5*time.Minute))))
			return
		}
		days := "7"
		if len(args) > 2 {
			days = map[string]string{"weekly": "7", "biweekly": "14", "monthly": "30"}[args[2]]
			if days == "" {
				days = args[2]
			}
		}
		var r struct{ Markdown, Saved string }
		json.Unmarshal(must(call("GET", "/api/memory/report?save=1&days="+days, nil, 2*time.Minute)), &r)
		fmt.Println(r.Markdown)
		fmt.Println("Saved to", r.Saved)
	default:
		usage()
		os.Exit(2)
	}
}

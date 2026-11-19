// Each app is its own process.
//
// The launcher (plain `mitra-marketplace`) only shows the welcome screen and the icons. Clicking
// an icon starts `mitra-marketplace app <id>`: a separate process on its own port that serves
// that one app and nothing else, opened in its own window. Closing the window ends the process.
// The processes share what must be shared and nothing more: the runtimes, the model store, the
// one governor (so only one model runs at a time across every app) and the one memory log.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"time"
)

var (
	appMode   string          // "" in the launcher; otherwise the one app this process serves
	appNeeds  = map[string]bool{} // capabilities its manifest declares ("assistant", ...)
	appUses   = map[string]bool{} // shared services its manifest declares ("convert")
	appPort   int
	startedAt = time.Now()
	lastReq   atomic.Int64 // UnixNano of the most recent request
	byeAt     atomic.Int64 // UnixNano of the last "my window is closing" beacon
	inflight  atomic.Int32
	reqCount  atomic.Int64
)

type runInfo struct {
	ID      string `json:"id"`
	PID     int    `json:"pid"`
	Port    int    `json:"port"`
	Started string `json:"started"`
	MB      uint64 `json:"mb,omitempty"`
	URL     string `json:"url,omitempty"`
}

func runFile(id string) string { return filepath.Join(home, "run", "apps", id+".json") }

// appURL is the app's page, optionally with a query ("path=...&find=..."). The query is parsed
// and written out again, so nothing in it can change which page is opened.
func appURL(port int, id, query string) string {
	u := fmt.Sprintf("http://127.0.0.1:%d/apps/%s/", port, id)
	if v, err := url.ParseQuery(strings.TrimPrefix(query, "?")); err == nil && len(v) > 0 {
		u += "?" + v.Encode()
	}
	return u
}

// appAlive reports the running process for an app, by asking it. A run file whose process no
// longer answers is a leftover from a crash and is removed.
func appAlive(id string) (runInfo, bool) {
	var info runInfo
	b, err := os.ReadFile(runFile(id))
	if err != nil || json.Unmarshal(b, &info) != nil || info.Port == 0 {
		return info, false
	}
	resp, err := (&http.Client{Timeout: 700 * time.Millisecond}).Get(fmt.Sprintf("http://127.0.0.1:%d/api/ping", info.Port))
	if err == nil {
		defer resp.Body.Close()
		var ping struct {
			App string
			MB  uint64
		}
		if json.NewDecoder(resp.Body).Decode(&ping) == nil && ping.App == id {
			info.MB, info.URL = ping.MB, appURL(info.Port, id, "")
			return info, true
		}
	}
	if time.Since(fileTime(runFile(id))) > 5*time.Second { // not one that is still starting
		os.Remove(runFile(id))
	}
	return info, false
}

func fileTime(p string) time.Time {
	if st, err := os.Stat(p); err == nil {
		return st.ModTime()
	}
	return time.Time{}
}

func runningApps() []runInfo {
	out := []runInfo{}
	files, _ := filepath.Glob(filepath.Join(home, "run", "apps", "*.json"))
	for _, f := range files {
		if info, ok := appAlive(strings.TrimSuffix(filepath.Base(f), ".json")); ok {
			out = append(out, info)
		}
	}
	return out
}

// spawnApp starts the app's process if it is not already running and waits until it answers.
func spawnApp(id string) (runInfo, bool, error) {
	if appDir(id) == "" {
		return runInfo{}, false, fmt.Errorf("no app '%s'", id)
	}
	if info, ok := appAlive(id); ok {
		return info, false, nil
	}
	exe, _ := os.Executable()
	cmd := exec.Command(exe, "app", id)
	logf, _ := os.OpenFile(filepath.Join(home, "logs", id+".log"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	cmd.Stdout, cmd.Stderr = logf, logf
	cmd.Env = append(os.Environ(), "MITRA_ROOT="+root, "MITRA_HOME="+home)
	detach(cmd)
	if err := cmd.Start(); err != nil {
		return runInfo{}, false, err
	}
	go cmd.Wait()
	for i := 0; i < 80; i++ {
		time.Sleep(100 * time.Millisecond)
		if info, ok := appAlive(id); ok {
			return info, true, nil
		}
	}
	return runInfo{}, false, fmt.Errorf("%s did not start; see %s", id, filepath.Join(home, "logs", id+".log"))
}

func stopApp(id string) bool {
	info, ok := appAlive(id)
	if !ok {
		return false
	}
	req, _ := http.NewRequest("POST", fmt.Sprintf("http://127.0.0.1:%d/api/shutdown", info.Port), strings.NewReader("{}"))
	if resp, err := (&http.Client{Timeout: 5 * time.Second}).Do(req); err == nil {
		resp.Body.Close()
	}
	for i := 0; i < 50; i++ {
		if _, still := appAlive(id); !still {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	return true
}

// ---- windows ------------------------------------------------------------------------------

// chromium finds a Chrome-family browser. Those can show a page as a bare window with no tabs
// or address bar, which is what makes each app look like its own program without shipping a
// browser with it.
func chromium() string {
	if p := cfgStr("browser", ""); p != "" {
		return p
	}
	var c []string
	switch runtime.GOOS {
	case "windows":
		for _, base := range []string{os.Getenv("ProgramFiles"), os.Getenv("ProgramFiles(x86)"), os.Getenv("LOCALAPPDATA")} {
			if base != "" {
				c = append(c, filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe"), filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
			}
		}
	case "darwin":
		c = []string{"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
			"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", "/Applications/Chromium.app/Contents/MacOS/Chromium"}
	default:
		for _, n := range []string{"google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"} {
			if p, err := exec.LookPath(n); err == nil {
				return p
			}
		}
	}
	for _, p := range c {
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p
		}
	}
	return ""
}

// openWindow shows a URL: "window" (its own bare window), "tab" (the default browser), "page"
// (nothing could be opened from here, so the calling page should open it) or "none" (opening
// is switched off, as in the tests).
func openWindow(u string) string {
	mode := cfgStr("app_window", "window")
	if mode == "none" {
		return "none"
	}
	if mode == "window" {
		if b := chromium(); b != "" {
			cmd := exec.Command(b, "--app="+u, "--window-size=1240,860")
			detach(cmd)
			if cmd.Start() == nil {
				go cmd.Wait()
				return "window"
			}
		}
	}
	cmd := browserCommand(u)
	if cmd.Start() == nil {
		go cmd.Wait()
		return "tab"
	}
	return "page"
}

func launch(id, query string, open bool) (map[string]any, error) {
	t0 := time.Now()
	info, fresh, err := spawnApp(id)
	if err != nil {
		return nil, err
	}
	u := appURL(info.Port, id, query)
	opened := "none"
	if open {
		opened = openWindow(u)
	}
	if appMode != id {
		who := "launcher"
		if appMode != "" {
			who = appMode
		}
		logEvent(id, "app.launch", map[string]any{"from": who, "fresh": fresh, "opened": opened, "ms": time.Since(t0).Milliseconds()}, "")
	}
	return map[string]any{"id": id, "port": info.Port, "pid": info.PID, "url": u, "opened": opened, "started": fresh, "ms": time.Since(t0).Milliseconds()}, nil
}

// ---- what each kind of process may answer ------------------------------------------------------

// scope keeps the products separate. The launcher has no capabilities of its own: converting,
// asking the model and every app's own routes exist only inside that app's process. An app's
// process answers for itself alone, and only for what its manifest declares.
func scope(r *http.Request) (int, string) {
	p := r.URL.Path
	if !strings.HasPrefix(p, "/api/") {
		return 0, ""
	}
	seg := strings.Split(strings.TrimPrefix(p, "/api/"), "/")
	if appMode == "" {
		switch {
		case seg[0] == "ask" || seg[0] == "convert" || seg[0] == "upload":
			return 409, "This runs inside an app. Open the app first; the launcher has no capabilities of its own."
		case seg[0] == "apps" && len(seg) > 2:
			return 409, seg[1] + " is not running here. Open it first; each app answers only from its own process."
		}
		return 0, ""
	}
	switch seg[0] {
	case "builder", "memory", "stop":
		return 403, "Only the launcher does this."
	case "apps":
		if r.Method == "DELETE" {
			return 403, "Only the launcher removes apps."
		}
		if len(seg) > 1 && seg[1] != appMode {
			return 403, "This process is " + appMode + " only."
		}
	case "manager":
		if len(seg) > 1 && seg[1] != appMode {
			return 403, "This process is " + appMode + " only."
		}
	case "ask":
		if !appNeeds["assistant"] {
			return 403, appMode + " does not declare the assistant capability in its manifest."
		}
	case "convert", "upload":
		if !appUses["convert"] {
			return 403, appMode + " does not declare the convert service in its manifest."
		}
	}
	return 0, ""
}

// ---- lifetime -----------------------------------------------------------------------------

func memMB() uint64 {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	return m.Sys / (1 << 20)
}

func quit(reason string) {
	who := "shell"
	if appMode != "" {
		who = appMode
		stopJobs() // before the model: a worker left alive would only start the next piece
		// stop a model only if it is this app's; another app's model is not ours to stop
		if s, err := governor("status"); err == nil {
			for _, l := range asList(s["leases"]) {
				if m, ok := l.(map[string]any); ok {
					for _, a := range asList(m["apps"]) {
						if a == appMode {
							governor("kill")
						}
					}
				}
			}
		}
		var info runInfo
		if b, err := os.ReadFile(runFile(appMode)); err == nil && json.Unmarshal(b, &info) == nil && info.PID == os.Getpid() {
			os.Remove(runFile(appMode))
		}
	}
	logEvent(who, map[bool]string{true: "app.exit", false: "server.exit"}[appMode != ""],
		map[string]any{"reason": reason, "lived_s": int(time.Since(startedAt).Seconds()), "requests": reqCount.Load(), "mb": memMB()}, "")
	os.Exit(0)
}

func asList(v any) []any {
	l, _ := v.([]any)
	return l
}

// watch ends the process when nobody is using it: a few seconds after its window says goodbye
// (a reload says goodbye too, then asks again at once, which cancels it), or after a quiet
// period if the window vanished without a word.
func watch(idleSec float64) {
	grace := int64(cfgFloat("close_grace_s", 5) * 1e9)
	for range time.Tick(time.Second) {
		if activeJobs.Load() > 0 || inflight.Load() > 0 {
			continue
		}
		now := time.Now().UnixNano()
		if b := byeAt.Load(); b > 0 && lastReq.Load() <= b && now-b > grace {
			quit("window closed")
		}
		if idleSec > 0 && float64(now-lastReq.Load())/1e9 > idleSec {
			if appMode == "" {
				logEvent("shell", "server.idle_exit", map[string]any{"after_min": idleSec / 60}, "")
			}
			quit("idle")
		}
	}
}

func serveApp(id string) {
	dir := appDir(id)
	if dir == "" {
		fmt.Fprintln(os.Stderr, "No such app:", id)
		os.Exit(2)
	}
	if info, ok := appAlive(id); ok {
		fmt.Printf("%s is already running at %s\n", id, info.URL)
		return
	}
	appMode = id
	var manifest struct {
		Needs []string  `json:"needs"`
		Uses  *[]string `json:"uses"`
	}
	if b, err := os.ReadFile(filepath.Join(dir, "mitra.app.json")); err == nil {
		json.Unmarshal(b, &manifest)
	}
	for _, n := range manifest.Needs {
		appNeeds[n] = true
	}
	if manifest.Uses != nil {
		for _, u := range *manifest.Uses {
			appUses[u] = true
		}
	} else if strings.HasPrefix(dir, filepath.Join(home, "apps")) {
		appUses["convert"] = true // an app you created before manifests said what they use: it reads files
	}
	// The same app gets the same port each time it starts, so its window is the same web origin and
	// keeps what the page stored there (theme, the conversation in Ask Mitra, the last folder).
	// A port already taken (another install, another program) falls back to any free one.
	h := fnv.New32a()
	h.Write([]byte(home + "\x00" + id))
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", 41000+int(h.Sum32()%8000)))
	if err != nil {
		ln, err = net.Listen("tcp", "127.0.0.1:0")
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	appPort = ln.Addr().(*net.TCPAddr).Port
	info, _ := json.Marshal(runInfo{ID: id, PID: os.Getpid(), Port: appPort, Started: time.Now().Format("2006-01-02T15:04:05")})
	os.WriteFile(runFile(id), info, 0o644)
	tune()
	lastReq.Store(time.Now().UnixNano())
	logEvent(id, "app.spawn", map[string]any{"pid": os.Getpid(), "port": appPort, "version": version}, "")
	go watch(cfgFloat("app_idle_exit_s", 150))
	if err := http.Serve(ln, routes()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

// ---- routes both kinds of process share ---------------------------------------------------

func processRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/ping", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"mitra": true, "version": version, "pid": os.Getpid(), "app": appMode, "port": appPort, "mb": memMB(),
			"uptime_s": int(time.Since(startedAt).Seconds())})
	})
	mux.HandleFunc("GET /api/heartbeat", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) })
	mux.HandleFunc("POST /api/bye", func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, io.LimitReader(r.Body, 1<<16))
		byeAt.Store(time.Now().UnixNano())
		w.WriteHeader(204)
	})
	mux.HandleFunc("POST /api/shutdown", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]bool{"ok": true})
		go func() { time.Sleep(150 * time.Millisecond); quit("stopped") }()
	})
	mux.HandleFunc("GET /api/running", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, runningApps()) })
	mux.HandleFunc("POST /api/launch/{id}", func(w http.ResponseWriter, r *http.Request) {
		var b struct{ Path, Query string }
		json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&b)
		if b.Path != "" {
			b.Query = "path=" + url.QueryEscape(b.Path)
		}
		res, err := launch(r.PathValue("id"), b.Query, r.URL.Query().Get("open") != "0")
		if err != nil {
			fail(w, 404, err.Error())
			return
		}
		writeJSON(w, 200, res)
	})
	mux.HandleFunc("POST /api/stop/{id}", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]bool{"stopped": stopApp(r.PathValue("id"))})
	})
	// an app's window asks for the launcher (its logo, or "Memory" in the palette)
	mux.HandleFunc("POST /api/launcher", func(w http.ResponseWriter, r *http.Request) {
		to := r.URL.Query().Get("to")
		if strings.ContainsAny(to, "/?#&") {
			to = ""
		}
		exe, _ := os.Executable()
		cmd := exec.Command(exe, "home", to)
		cmd.Env = append(os.Environ(), "MITRA_ROOT="+root, "MITRA_HOME="+home)
		detach(cmd)
		var out bytes.Buffer
		cmd.Stdout = &out
		if err := cmd.Run(); err != nil {
			fail(w, 500, "Could not open the launcher: "+err.Error())
			return
		}
		writeJSON(w, 200, map[string]any{"ok": true, "url": baseURL() + "/"})
	})
}

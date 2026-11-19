// Moving Mitra between systems.
//
// The "tunnel" is a shared folder, by default <Dropbox>/Mitra/releases, which Dropbox already
// syncs to every machine; any synced or mounted folder works (set release_dir in config.json).
// Nothing listens on the network.
//
//   push      pack this install (source, UI, apps, your own apps, this platform's binaries)
//             into a versioned zip in the shared folder
//   update    on another system: take the newest zip, verify it, install it, and delete files
//             the new version no longer has
//   install   search this system for Mitra zips (a release, or a packed app) and install them
//   releases  list what is in the shared folder; `releases prune N` keeps the newest N
//   pack APP  zip one app so another system can `install` it
package main

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"time"
)

type releaseInfo struct {
	Version string `json:"version"`
	Built   string `json:"built"` // yyyymmdd-hhmmss, sortable
	OS      string `json:"os"`
	Arch    string `json:"arch"`
	Files   int    `json:"files"`
}

var (
	packDirs  = []string{"gateway", "governor", "workers", "web", "apps", "bin", "logs/tests", "logs/scripts", "docs"}
	packFiles = []string{"catalog.json", "build.ps1", "build.sh", "install.ps1", "install.sh", "README.md", "APP_SPEC.md", "TEST_PLAN.md"}
	// folders `update` owns completely: a file here that the new release lacks is removed
	managedDirs = []string{"gateway", "governor", "workers", "web", "apps", "logs/tests"}
	releaseRx   = regexp.MustCompile(`^mitra-marketplace-(.+)-(\d{8}-\d{6})\.zip$`)
)

func releaseDir() string {
	return cfgStr("release_dir", filepath.Join(dropboxRoot(), "Mitra", "releases"))
}

func skipInPack(rel string, d fs.DirEntry) bool {
	name := d.Name()
	return name == "__pycache__" || name == "target" || name == ".git" || strings.HasSuffix(name, ".old") ||
		strings.HasSuffix(name, ".pyc") || strings.HasPrefix(rel, "logs/tests/results")
}

func addTree(zw *zip.Writer, srcDir, zipPrefix string) (int, error) {
	n := 0
	err := filepath.WalkDir(srcDir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(srcDir, p)
		rel = filepath.ToSlash(rel)
		if rel != "." && skipInPack(zipPrefix+"/"+rel, d) {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if d.IsDir() {
			return nil
		}
		if err := addFile(zw, p, zipPrefix+"/"+rel); err != nil {
			return err
		}
		n++
		return nil
	})
	return n, err
}

func addFile(zw *zip.Writer, src, name string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	st, _ := in.Stat()
	h, _ := zip.FileInfoHeader(st)
	h.Name, h.Method = name, zip.Deflate
	w, err := zw.CreateHeader(h)
	if err != nil {
		return err
	}
	_, err = io.Copy(w, in)
	return err
}

func sha256File(p string) string {
	f, err := os.Open(p)
	if err != nil {
		return ""
	}
	defer f.Close()
	h := sha256.New()
	io.Copy(h, f)
	return hex.EncodeToString(h.Sum(nil))
}

func installedRelease() releaseInfo {
	var r releaseInfo
	if b, err := os.ReadFile(filepath.Join(root, "release.json")); err == nil {
		json.Unmarshal(b, &r)
	}
	return r
}

// ---- push -------------------------------------------------------------------------------

func push() error {
	dir := releaseDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	info := releaseInfo{Version: version, Built: time.Now().Format("20060102-150405"), OS: runtime.GOOS, Arch: runtime.GOARCH}
	name := fmt.Sprintf("mitra-marketplace-%s-%s.zip", info.Version, info.Built)
	tmp := filepath.Join(dir, name+".part")
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	zw := zip.NewWriter(out)
	for _, d := range packDirs {
		if _, err := os.Stat(filepath.Join(root, filepath.FromSlash(d))); err != nil {
			continue
		}
		n, err := addTree(zw, filepath.Join(root, filepath.FromSlash(d)), d)
		if err != nil {
			zw.Close()
			out.Close()
			os.Remove(tmp)
			return err
		}
		info.Files += n
	}
	for _, f := range packFiles {
		if _, err := os.Stat(filepath.Join(root, f)); err == nil {
			if addFile(zw, filepath.Join(root, f), f) == nil {
				info.Files++
			}
		}
	}
	userApps := 0
	if entries, err := os.ReadDir(filepath.Join(home, "apps")); err == nil { // the apps you created travel too
		for _, e := range entries {
			if e.IsDir() {
				n, _ := addTree(zw, filepath.Join(home, "apps", e.Name()), "user-apps/"+e.Name())
				info.Files += n
				userApps++
			}
		}
	}
	meta, _ := json.MarshalIndent(info, "", "  ")
	w, _ := zw.Create("release.json")
	w.Write(meta)
	zw.Close()
	out.Close()
	final := filepath.Join(dir, name)
	if err := os.Rename(tmp, final); err != nil {
		return err
	}
	os.WriteFile(final+".sha256", []byte(sha256File(final)+"  "+name+"\n"), 0o644)
	for _, f := range []string{"install.ps1", "install.sh"} { // so a new system can bootstrap from the shared folder
		if b, err := os.ReadFile(filepath.Join(root, f)); err == nil {
			os.WriteFile(filepath.Join(dir, f), b, 0o755)
		}
	}
	os.WriteFile(filepath.Join(root, "release.json"), meta, 0o644) // this system now is that release
	st, _ := os.Stat(final)
	logEvent("shell", "release.push", map[string]any{"file": name, "files": info.Files, "user_apps": userApps}, "")
	fmt.Printf("Pushed %s\n  %d files, %d of your own apps, %.1f MB, binaries for %s/%s\n  to %s\n", name, info.Files, userApps,
		float64(st.Size())/(1<<20), info.OS, info.Arch, dir)
	fmt.Println("On another system: mitra-marketplace update   (first time: run install.ps1 or install.sh from that folder)")
	return nil
}

// ---- finding zips -----------------------------------------------------------------------

type foundZip struct {
	Path    string
	Kind    string // "release" or "app"
	Release releaseInfo
	AppID   string
	AppName string
	Prefix  string // folder inside the zip that holds mitra.app.json ("" or "name/")
}

func inspectZip(p string) *foundZip {
	zr, err := zip.OpenReader(p)
	if err != nil {
		return nil
	}
	defer zr.Close()
	read := func(f *zip.File, v any) bool {
		rc, err := f.Open()
		if err != nil {
			return false
		}
		defer rc.Close()
		return json.NewDecoder(io.LimitReader(rc, 1<<20)).Decode(v) == nil
	}
	for _, f := range zr.File {
		if f.Name == "release.json" {
			var r releaseInfo
			if read(f, &r) && r.Built != "" {
				return &foundZip{Path: p, Kind: "release", Release: r}
			}
		}
	}
	for _, f := range zr.File {
		if f.Name == "mitra.app.json" || (strings.Count(f.Name, "/") == 1 && strings.HasSuffix(f.Name, "/mitra.app.json")) {
			var m struct{ ID, Name string }
			if read(f, &m) && m.ID != "" {
				return &foundZip{Path: p, Kind: "app", AppID: m.ID, AppName: m.Name, Prefix: strings.TrimSuffix(f.Name, "mitra.app.json")}
			}
		}
	}
	return nil
}

// searchZips looks through the places a zip is likely to be for files named *mitra*.zip.
func searchZips() []foundZip {
	h, _ := os.UserHomeDir()
	type rootDepth struct {
		dir   string
		depth int
	}
	roots := []rootDepth{{releaseDir(), 2}, {dropboxRoot(), 3}, {filepath.Join(h, "Downloads"), 3}, {filepath.Join(h, "Desktop"), 2},
		{filepath.Join(h, "Documents"), 2}, {filepath.Join(h, "storage", "shared", "Download"), 2}, {h, 1}}
	skip := map[string]bool{"node_modules": true, ".git": true, "AppData": true, "Library": true, "target": true, "removed-apps": true}
	seen, out := map[string]bool{}, []foundZip{}
	for _, r := range roots {
		base := filepath.Clean(r.dir)
		filepath.WalkDir(base, func(p string, d fs.DirEntry, err error) error {
			if err != nil {
				return fs.SkipDir
			}
			rel, _ := filepath.Rel(base, p)
			depth := strings.Count(filepath.ToSlash(rel), "/") + 1
			if d.IsDir() {
				if rel != "." && (skip[d.Name()] || strings.HasPrefix(d.Name(), ".") || depth > r.depth) {
					return fs.SkipDir
				}
				return nil
			}
			low := strings.ToLower(d.Name())
			key := p
			if runtime.GOOS == "windows" || runtime.GOOS == "darwin" {
				key = strings.ToLower(p) // these file systems ignore case, so Dropbox\Mitra and Dropbox\MITRA are one folder
			}
			if strings.HasSuffix(low, ".zip") && strings.Contains(low, "mitra") && !seen[key] {
				seen[key] = true
				if z := inspectZip(p); z != nil {
					out = append(out, *z)
				}
			}
			return nil
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Release.Built > out[j].Release.Built })
	return out
}

// ---- extracting -------------------------------------------------------------------------

// safeJoin refuses zip entries that would land outside base.
func safeJoin(base, name string) (string, bool) {
	dst := filepath.Join(base, filepath.FromSlash(name))
	rel, err := filepath.Rel(base, dst)
	return dst, err == nil && !strings.HasPrefix(rel, "..") && !filepath.IsAbs(rel)
}

func writeEntry(f *zip.File, dst string) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	rc, err := f.Open()
	if err != nil {
		return err
	}
	defer rc.Close()
	if _, err := os.Stat(dst); err == nil && strings.Contains(filepath.ToSlash(dst), "/bin/") {
		os.Remove(dst + ".old")
		os.Rename(dst, dst+".old") // a running program cannot be overwritten, but it can be moved aside
	}
	mode := f.Mode()
	if mode == 0 {
		mode = 0o644
	}
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode|0o200)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, rc)
	return err
}

func applyRelease(z foundZip) error {
	if b, err := os.ReadFile(z.Path + ".sha256"); err == nil {
		if want := strings.Fields(string(b)); len(want) > 0 && want[0] != sha256File(z.Path) {
			return fmt.Errorf("checksum mismatch for %s; the file is incomplete or was changed. Not installed", filepath.Base(z.Path))
		}
	}
	zr, err := zip.OpenReader(z.Path)
	if err != nil {
		return err
	}
	defer zr.Close()
	if running() {
		call("POST", "/api/shutdown", map[string]any{}, 5*time.Second)
		for i := 0; i < 50 && running(); i++ {
			time.Sleep(100 * time.Millisecond)
		}
	}
	samePlatform := z.Release.OS == runtime.GOOS && z.Release.Arch == runtime.GOARCH
	kept := map[string]bool{}
	apps := 0
	for _, f := range zr.File {
		if f.FileInfo().IsDir() {
			continue
		}
		base, name := root, f.Name
		if strings.HasPrefix(name, "user-apps/") {
			base, name = filepath.Join(home, "apps"), strings.TrimPrefix(name, "user-apps/")
			if strings.HasSuffix(name, "/mitra.app.json") {
				apps++
			}
		} else if strings.HasPrefix(name, "bin/") && !samePlatform {
			continue // binaries built for another platform; this system builds its own below
		}
		dst, ok := safeJoin(base, name)
		if !ok {
			return fmt.Errorf("refusing unsafe path in zip: %s", f.Name)
		}
		if err := writeEntry(f, dst); err != nil {
			return fmt.Errorf("%s: %w", f.Name, err)
		}
		if base == root {
			kept[filepath.ToSlash(name)] = true
		}
	}
	pruned := 0
	for _, d := range managedDirs { // prune: what the new release no longer ships is removed
		base := filepath.Join(root, filepath.FromSlash(d))
		filepath.WalkDir(base, func(p string, e fs.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			rel, _ := filepath.Rel(root, p)
			rel = filepath.ToSlash(rel)
			if e.IsDir() {
				if e.Name() == "target" || e.Name() == "__pycache__" || strings.HasPrefix(rel, "logs/tests/results") {
					return fs.SkipDir
				}
				return nil
			}
			if !kept[rel] && os.Remove(p) == nil {
				pruned++
			}
			return nil
		})
	}
	logEvent("shell", "release.update", map[string]any{"version": z.Release.Version, "built": z.Release.Built, "files": len(kept), "pruned": pruned, "user_apps": apps}, "")
	fmt.Printf("Installed %s (built %s): %d files, %d removed as no longer shipped, %d of your apps.\n", z.Release.Version, z.Release.Built, len(kept), pruned, apps)
	if !samePlatform {
		fmt.Printf("That release carries binaries for %s/%s; building for %s/%s...\n", z.Release.OS, z.Release.Arch, runtime.GOOS, runtime.GOARCH)
		var cmd *exec.Cmd
		if runtime.GOOS == "windows" {
			cmd = exec.Command("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", filepath.Join(root, "build.ps1"))
		} else {
			cmd = exec.Command("sh", filepath.Join(root, "build.sh"))
		}
		cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("files are updated but the build failed (%v). Install Go and Rust, then run the build script in %s", err, root)
		}
	}
	return nil
}

func update(checkOnly bool) error {
	var newest *foundZip
	entries, _ := os.ReadDir(releaseDir())
	for _, e := range entries {
		if releaseRx.MatchString(e.Name()) {
			if z := inspectZip(filepath.Join(releaseDir(), e.Name())); z != nil && z.Kind == "release" && (newest == nil || z.Release.Built > newest.Release.Built) {
				newest = z
			}
		}
	}
	cur := installedRelease()
	if newest == nil {
		fmt.Println("No releases in", releaseDir())
		return nil
	}
	if newest.Release.Built <= cur.Built {
		fmt.Printf("Up to date: %s (built %s).\n", cur.Version, cur.Built)
		return nil
	}
	fmt.Printf("Installed: %s (built %s)\nAvailable: %s (built %s)\n", orDash(cur.Version), orDash(cur.Built), newest.Release.Version, newest.Release.Built)
	if checkOnly {
		return nil
	}
	return applyRelease(*newest)
}

func orDash(s string) string {
	if s == "" {
		return "unknown"
	}
	return s
}

// ---- apps as zips -----------------------------------------------------------------------

func packApp(id string) error {
	dir := appDir(id)
	if dir == "" {
		return fmt.Errorf("no app '%s'", id)
	}
	outDir := filepath.Join(releaseDir(), "apps")
	os.MkdirAll(outDir, 0o755)
	dst := filepath.Join(outDir, id+".mitra-app.zip")
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	zw := zip.NewWriter(out)
	n, err := addTree(zw, dir, id)
	zw.Close()
	out.Close()
	if err != nil {
		return err
	}
	fmt.Printf("Packed %s (%d files) to %s\n", id, n, dst)
	return nil
}

func installApp(z foundZip) error {
	zr, err := zip.OpenReader(z.Path)
	if err != nil {
		return err
	}
	defer zr.Close()
	if strings.ContainsAny(z.AppID, `/\.`) {
		return fmt.Errorf("app id %q is not valid", z.AppID)
	}
	dst := filepath.Join(home, "apps", z.AppID)
	if _, err := os.Stat(dst); err == nil { // replace, keeping the old copy
		trash := filepath.Join(home, "removed-apps", fmt.Sprintf("%s-%d", z.AppID, time.Now().Unix()))
		os.MkdirAll(filepath.Dir(trash), 0o755)
		if err := os.Rename(dst, trash); err != nil {
			return err
		}
	}
	n := 0
	for _, f := range zr.File {
		if f.FileInfo().IsDir() {
			continue
		}
		if !strings.HasPrefix(f.Name, z.Prefix) {
			continue // not part of the app folder
		}
		p, ok := safeJoin(dst, strings.TrimPrefix(f.Name, z.Prefix))
		if !ok {
			return fmt.Errorf("refusing unsafe path in zip: %s", f.Name)
		}
		if err := writeEntry(f, p); err != nil {
			return err
		}
		n++
	}
	logEvent("shell", "app.install", map[string]any{"id": z.AppID, "from": z.Path, "files": n}, "")
	fmt.Printf("Installed app %s (%d files). Open it with: mitra-marketplace open %s\n", z.AppID, n, z.AppID)
	return nil
}

// install searches the system; with a query it installs the matching app zip (or release).
func install(query string) error {
	if query != "" {
		if st, err := os.Stat(query); err == nil && !st.IsDir() {
			z := inspectZip(query)
			if z == nil {
				return fmt.Errorf("%s is not a Mitra release or app zip", query)
			}
			if z.Kind == "app" {
				return installApp(*z)
			}
			return applyRelease(*z)
		}
	}
	fmt.Println("Searching for Mitra zips (release folder, Dropbox, Downloads, Desktop, Documents, home)...")
	found := searchZips()
	if len(found) == 0 {
		fmt.Println("None found. A zip must have 'mitra' in its name and contain release.json or mitra.app.json.")
		return nil
	}
	cur := installedRelease()
	var newest *foundZip
	matched := false
	for i := range found {
		z := &found[i]
		if z.Kind == "release" {
			state := "older or same"
			if z.Release.Built > cur.Built {
				state = "NEWER than installed"
				if newest == nil {
					newest = z
				}
			}
			fmt.Printf("  release  %s built %s (%s/%s)  %s\n           %s\n", z.Release.Version, z.Release.Built, z.Release.OS, z.Release.Arch, state, z.Path)
		} else {
			fmt.Printf("  app      %s (%s)\n           %s\n", z.AppID, z.AppName, z.Path)
			q := strings.ToLower(query)
			if query != "" && (strings.Contains(strings.ToLower(z.AppID), q) || strings.Contains(strings.ToLower(filepath.Base(z.Path)), q)) {
				matched = true
				if err := installApp(*z); err != nil {
					return err
				}
			}
		}
	}
	switch {
	case query == "" && newest != nil:
		fmt.Println("Installing the newest release...")
		return applyRelease(*newest)
	case query == "":
		fmt.Println("This install is already the newest release found. To install an app: mitra-marketplace install APP_NAME")
	case !matched:
		return fmt.Errorf("no app zip matching %q", query)
	}
	return nil
}

func releases(pruneKeep int) error {
	dir := releaseDir()
	entries, _ := os.ReadDir(dir)
	var names []string
	for _, e := range entries {
		if releaseRx.MatchString(e.Name()) {
			names = append(names, e.Name())
		}
	}
	sort.Slice(names, func(i, j int) bool { return releaseRx.FindStringSubmatch(names[i])[2] > releaseRx.FindStringSubmatch(names[j])[2] })
	cur := installedRelease()
	fmt.Println("Release folder:", dir)
	for i, n := range names {
		st, _ := os.Stat(filepath.Join(dir, n))
		mark := ""
		if releaseRx.FindStringSubmatch(n)[2] == cur.Built {
			mark = "  <- installed here"
		}
		if pruneKeep > 0 && i >= pruneKeep {
			os.Remove(filepath.Join(dir, n))
			os.Remove(filepath.Join(dir, n+".sha256"))
			mark = "  removed"
		}
		fmt.Printf("  %s  %.1f MB%s\n", n, float64(st.Size())/(1<<20), mark)
	}
	if len(names) == 0 {
		fmt.Println("  none yet. Create one with: mitra-marketplace push")
	}
	if pruneKeep > 0 {
		logEvent("shell", "release.prune", map[string]any{"kept": pruneKeep, "had": len(names)}, "")
	}
	return nil
}

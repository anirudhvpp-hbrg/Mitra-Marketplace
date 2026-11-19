// Files and apps.
//
// Each app's manifest says which kinds of file it opens ("opens": [".pdf"]). Three things use
// that one list: a file dropped on a window goes to the app that opens it, `register` tells
// Windows the apps exist so they appear under "Open with" and in Settings > Default apps, and
// the Start menu gets one entry per app.
package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
	"unicode/utf16"
)

type appInfo struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Opens       []string `json:"opens"`
}

// installedApps reads every manifest: the built-in apps first, then the ones you created.
func installedApps() []appInfo {
	var out []appInfo
	seen := map[string]bool{}
	for _, base := range []string{filepath.Join(root, "apps"), filepath.Join(home, "apps")} {
		files, _ := filepath.Glob(filepath.Join(base, "*", "mitra.app.json"))
		sort.Strings(files)
		for _, f := range files {
			var a appInfo
			if b, err := os.ReadFile(f); err != nil || json.Unmarshal(b, &a) != nil || a.ID == "" || seen[a.ID] {
				continue
			}
			seen[a.ID] = true
			if a.Name == "" {
				a.Name = a.ID
			}
			out = append(out, a)
		}
	}
	return out
}

// opensMap is extension -> the apps that open it, in order. "*" lists the apps that take
// whatever nothing else claims.
func opensMap() map[string][]string {
	m := map[string][]string{}
	for _, a := range installedApps() {
		for _, e := range a.Opens {
			e = strings.ToLower(e)
			m[e] = append(m[e], a.ID)
		}
	}
	return m
}

func fileRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/opens", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, opensMap()) })
	// A file dropped on a window. The browser hands over the file's bytes, never its path, so
	// they are kept in the temporary folder and the app is given that copy. Dropped on the app
	// that opens it, the answer is the path; dropped anywhere else, that app is started on it.
	mux.HandleFunc("POST /api/drop/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if appDir(id) == "" {
			io.Copy(io.Discard, io.LimitReader(r.Body, 1<<20))
			fail(w, 404, "No app '"+id+"'")
			return
		}
		name := filepath.Base(filepath.FromSlash(strings.ReplaceAll(r.URL.Query().Get("name"), `\`, "/")))
		if name == "." || name == "" || name == string(filepath.Separator) {
			name = "dropped"
		}
		dst := filepath.Join(home, "tmp", fmt.Sprintf("%d-%s", time.Now().UnixMilli(), name))
		f, err := os.Create(dst)
		if err != nil {
			fail(w, 500, err.Error())
			return
		}
		n, _ := io.Copy(f, io.LimitReader(r.Body, 2<<30))
		f.Close()
		res := map[string]any{"path": dst, "name": name, "bytes": n, "app": id, "launched": false}
		if id != appMode {
			l, err := launch(id, "path="+url.QueryEscape(dst)+"&name="+url.QueryEscape(name), r.URL.Query().Get("open") != "0")
			if err != nil {
				fail(w, 500, err.Error())
				return
			}
			res["launched"], res["url"], res["opened"] = true, l["url"], l["opened"]
		}
		who := "shell"
		if appMode != "" {
			who = appMode
		}
		logEvent(who, "file.drop", map[string]any{"ext": strings.ToLower(filepath.Ext(name)), "bytes": n, "to": id}, "")
		writeJSON(w, 200, res)
	})
}

// ---- telling Windows about the apps -------------------------------------------------------

type shortcut struct{ Link, Target, Args, Icon, About string }

type assocPlan struct {
	Reg, Unreg string     // registry files: what `register` adds and what `unregister` removes
	Copies     [][2]string // handler programs to create: from, to
	Shortcuts  []shortcut
	Types      map[string][]string // app name -> file types offered
}

func handlerDir() string { return filepath.Join(home, "handlers") }

func regEsc(s string) string { return strings.ReplaceAll(strings.ReplaceAll(s, `\`, `\\`), `"`, `\"`) }

// plan works out everything `register` does, without doing it, so it can be shown and tested.
// Nothing here makes an app the default: Windows only lets the person do that. It makes the
// apps available to choose.
func plan(desktop bool) assocPlan {
	exe, _ := os.Executable()
	stub := filepath.Join(filepath.Dir(exe), "mitra-open.exe")
	ico := filepath.Join(handlerDir(), "mitra.ico")
	menu := filepath.Join(os.Getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Mitra")
	desk := filepath.Join(os.Getenv("USERPROFILE"), "Desktop")
	const classes = `HKEY_CURRENT_USER\Software\Classes\`
	p := assocPlan{Types: map[string][]string{}}
	var add, del strings.Builder
	add.WriteString("Windows Registry Editor Version 5.00\r\n")
	del.WriteString("Windows Registry Editor Version 5.00\r\n")
	key := func(k string, vals ...string) { // vals: name, value pairs; "@" is the default value
		fmt.Fprintf(&add, "\r\n[%s]\r\n", k)
		for i := 0; i+1 < len(vals); i += 2 {
			n := `"` + regEsc(vals[i]) + `"`
			if vals[i] == "@" {
				n = "@"
			}
			if vals[i+1] == "\x00" { // an empty marker value, as OpenWithProgids wants
				fmt.Fprintf(&add, "%s=hex(0):\r\n", n)
			} else {
				fmt.Fprintf(&add, "%s=\"%s\"\r\n", n, regEsc(vals[i+1]))
			}
		}
	}
	dropKey := func(k string) { fmt.Fprintf(&del, "\r\n[-%s]\r\n", k) }
	dropVal := func(k, name string) { fmt.Fprintf(&del, "\r\n[%s]\r\n\"%s\"=-\r\n", k, regEsc(name)) }

	link := func(name, args, about string) {
		p.Shortcuts = append(p.Shortcuts, shortcut{filepath.Join(menu, name+".lnk"), filepath.Join(handlerDir(), name+".exe"), args, ico, about})
		if desktop {
			p.Shortcuts = append(p.Shortcuts, shortcut{filepath.Join(desk, name+".lnk"), filepath.Join(handlerDir(), name+".exe"), args, ico, about})
		}
	}
	// The handler is a tiny windowless program that runs the command it is given. Without it,
	// opening a file from Explorer would flash a console window. Each app gets a copy under
	// its own name, because Windows lists "Open with" choices by program.
	p.Copies = append(p.Copies, [2]string{stub, filepath.Join(handlerDir(), "Mitra.exe")})
	link("Mitra", fmt.Sprintf(`"%s"`, exe), "Mitra: the welcome screen and all apps")
	for _, a := range installedApps() {
		handler := filepath.Join(handlerDir(), a.Name+".exe")
		p.Copies = append(p.Copies, [2]string{stub, handler})
		link(a.Name, fmt.Sprintf(`"%s" open %s`, exe, a.ID), a.Description)
		var exts []string
		for _, e := range a.Opens {
			if strings.HasPrefix(e, ".") && !strings.ContainsAny(e, `\/ "*`) {
				exts = append(exts, strings.ToLower(e))
			}
		}
		if len(exts) == 0 {
			continue
		}
		p.Types[a.Name] = exts
		progid := "Mitra." + a.ID
		command := fmt.Sprintf(`"%s" "%s" open %s "%%1"`, handler, exe, a.ID)
		key(classes+progid, "@", a.Name+" document")
		key(classes+progid+`\DefaultIcon`, "@", ico)
		key(classes+progid+`\Application`, "ApplicationName", a.Name, "ApplicationDescription", a.Description, "ApplicationIcon", ico)
		key(classes+progid+`\shell\open`, "FriendlyAppName", a.Name)
		key(classes+progid+`\shell\open\command`, "@", command)
		dropKey(classes + progid)
		appKey := classes + `Applications\` + a.Name + ".exe"
		key(appKey, "FriendlyAppName", a.Name)
		key(appKey+`\DefaultIcon`, "@", ico)
		key(appKey+`\shell\open\command`, "@", command)
		types := []string{}
		caps := []string{}
		for _, e := range exts {
			types = append(types, e, "")
			caps = append(caps, e, progid)
			key(classes+e+`\OpenWithProgids`, progid, "\x00")
			dropVal(classes+e+`\OpenWithProgids`, progid)
		}
		key(appKey+`\SupportedTypes`, types...)
		dropKey(appKey)
		capKey := `HKEY_CURRENT_USER\Software\Mitra\Capabilities\` + a.ID
		key(capKey, "ApplicationName", a.Name, "ApplicationDescription", a.Description, "ApplicationIcon", ico)
		key(capKey+`\FileAssociations`, caps...)
		key(`HKEY_CURRENT_USER\Software\RegisteredApplications`, a.Name, `Software\Mitra\Capabilities\`+a.ID)
		dropVal(`HKEY_CURRENT_USER\Software\RegisteredApplications`, a.Name)
	}
	dropKey(`HKEY_CURRENT_USER\Software\Mitra`)
	p.Reg, p.Unreg = add.String(), del.String()
	return p
}

// writeIcon turns the logo into a Windows icon: the PNG, centred on a transparent 256 px
// square, inside an .ico wrapper (Windows reads PNG-in-ICO).
func writeIcon(dst string) error {
	f, err := os.Open(filepath.Join(root, "web", "static", "brand", "mitra-color.png"))
	if err != nil {
		return err
	}
	defer f.Close()
	src, err := png.Decode(f)
	if err != nil {
		return err
	}
	const side, pad = 256, 10
	b := src.Bounds()
	scale := float64(side-2*pad) / float64(max(b.Dx(), b.Dy()))
	w, h := int(float64(b.Dx())*scale), int(float64(b.Dy())*scale)
	img := image.NewNRGBA(image.Rect(0, 0, side, side))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ { // each output pixel is the average of the source pixels it covers
			x0, x1 := b.Min.X+int(float64(x)/scale), b.Min.X+int(float64(x+1)/scale)
			y0, y1 := b.Min.Y+int(float64(y)/scale), b.Min.Y+int(float64(y+1)/scale)
			var r, g, bl, a, n uint64
			for sy := y0; sy <= y1 && sy < b.Max.Y; sy++ {
				for sx := x0; sx <= x1 && sx < b.Max.X; sx++ {
					cr, cg, cb, ca := src.At(sx, sy).RGBA() // premultiplied, 16 bit
					r, g, bl, a, n = r+uint64(cr), g+uint64(cg), bl+uint64(cb), a+uint64(ca), n+1
				}
			}
			if n == 0 || a == 0 {
				continue
			}
			img.SetNRGBA((side-w)/2+x, (side-h)/2+y, color.NRGBA{uint8(r * 255 / a), uint8(g * 255 / a), uint8(bl * 255 / a), uint8(a / n >> 8)})
		}
	}
	var body bytes.Buffer
	if err := png.Encode(&body, img); err != nil {
		return err
	}
	var out bytes.Buffer
	binary.Write(&out, binary.LittleEndian, []uint16{0, 1, 1})                        // icon file, one image
	out.Write([]byte{0, 0, 0, 0})                                                     // 256 x 256, no palette
	binary.Write(&out, binary.LittleEndian, []uint16{1, 32})                          // planes, bits per pixel
	binary.Write(&out, binary.LittleEndian, []uint32{uint32(body.Len()), uint32(22)}) // size, offset
	out.Write(body.Bytes())
	return os.WriteFile(dst, out.Bytes(), 0o644)
}

func regImport(text string) error {
	u := utf16.Encode([]rune(text))
	buf := make([]byte, 2+2*len(u))
	buf[0], buf[1] = 0xFF, 0xFE
	for i, c := range u {
		binary.LittleEndian.PutUint16(buf[2+2*i:], c)
	}
	f := filepath.Join(home, "tmp", fmt.Sprintf("assoc-%d.reg", time.Now().UnixNano()))
	if err := os.WriteFile(f, buf, 0o600); err != nil {
		return err
	}
	defer os.Remove(f)
	if out, err := exec.Command("reg", "import", f).CombinedOutput(); err != nil {
		return fmt.Errorf("reg import: %v %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func psQuote(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }

// refreshShell tells Explorer the associations changed, so "Open with" shows them at once.
const refreshShell = `Add-Type -Namespace Mitra -Name Shell -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, uint f, IntPtr a, IntPtr b);'; [Mitra.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)`

func powershell(script string) error {
	cmd := exec.Command("powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script)
	hide(cmd)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("%v %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func register(args []string) error {
	desktop, show := false, false
	for _, a := range args {
		desktop = desktop || a == "--desktop"
		show = show || a == "--print"
	}
	p := plan(desktop)
	if show { // what would be written, and nothing written
		fmt.Print(p.Reg)
		for _, s := range p.Shortcuts {
			fmt.Printf("\r\n; shortcut %s -> \"%s\" %s", s.Link, s.Target, s.Args)
		}
		fmt.Println()
		return nil
	}
	if runtime.GOOS != "windows" {
		return fmt.Errorf("register is for Windows. On this system, open a file with: mitra-marketplace open APP FILE")
	}
	if _, err := os.Stat(p.Copies[0][0]); err != nil {
		return fmt.Errorf("%s is missing; run build.ps1 first", p.Copies[0][0])
	}
	os.MkdirAll(handlerDir(), 0o755)
	if err := writeIcon(filepath.Join(handlerDir(), "mitra.ico")); err != nil {
		return fmt.Errorf("icon: %v", err)
	}
	for _, c := range p.Copies {
		b, err := os.ReadFile(c[0])
		if err != nil {
			return err
		}
		if err := os.WriteFile(c[1], b, 0o755); err != nil {
			return err
		}
	}
	if err := regImport(p.Reg); err != nil {
		return err
	}
	var ps strings.Builder
	ps.WriteString("$w = New-Object -ComObject WScript.Shell; ")
	for _, s := range p.Shortcuts {
		fmt.Fprintf(&ps, "New-Item -ItemType Directory -Force (Split-Path %s) | Out-Null; $l = $w.CreateShortcut(%s); $l.TargetPath = %s; $l.Arguments = %s; $l.IconLocation = %s; $l.Description = %s; $l.Save(); ",
			psQuote(s.Link), psQuote(s.Link), psQuote(s.Target), psQuote(s.Args), psQuote(s.Icon), psQuote(firstLine(s.About, 200)))
	}
	ps.WriteString(refreshShell)
	if err := powershell(ps.String()); err != nil {
		return fmt.Errorf("shortcuts: %v", err)
	}
	logEvent("shell", "system.register", map[string]any{"apps": len(p.Types), "shortcuts": len(p.Shortcuts)}, "")
	fmt.Println("Windows now knows these apps. Each is in the Start menu under Mitra and in \"Open with\":")
	names := make([]string, 0, len(p.Types))
	for n := range p.Types {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		fmt.Printf("  %-16s %s\n", n, strings.Join(p.Types[n], " "))
	}
	fmt.Println("To make one the default: right-click a file > Open with > Choose another app > pick it > Always.")
	fmt.Println("Or: Settings > Apps > Default apps, and search for the app's name. Windows lets only you make that choice.")
	fmt.Println("Undo with: mitra-marketplace unregister")
	return nil
}

func unregister() error {
	if runtime.GOOS != "windows" {
		return fmt.Errorf("unregister is for Windows")
	}
	p := plan(true)
	if err := regImport(p.Unreg); err != nil {
		return err
	}
	var ps strings.Builder
	menu := ""
	for _, s := range p.Shortcuts {
		fmt.Fprintf(&ps, "Remove-Item -LiteralPath %s -Force -ErrorAction SilentlyContinue; ", psQuote(s.Link))
		if menu == "" {
			menu = filepath.Dir(s.Link)
		}
	}
	// the Start menu folder goes only if nothing else is left in it
	fmt.Fprintf(&ps, "if ((Test-Path -LiteralPath %s) -and -not (Get-ChildItem -LiteralPath %s -Force)) { Remove-Item -LiteralPath %s -Force }; ", psQuote(menu), psQuote(menu), psQuote(menu))
	ps.WriteString(refreshShell)
	err := powershell(ps.String())
	os.RemoveAll(handlerDir())
	logEvent("shell", "system.unregister", map[string]any{}, "")
	fmt.Println("Removed Mitra's apps from \"Open with\", Default apps and the Start menu. A default you had set goes back to Windows' choice.")
	return err
}

func firstLine(s string, n int) string {
	s = strings.TrimSpace(strings.SplitN(s, "\n", 2)[0])
	if len(s) > n {
		s = s[:n]
	}
	return s
}

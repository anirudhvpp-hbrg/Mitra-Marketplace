package main

import (
	"encoding/json"
	"net/http"
	"os/exec"
	"strings"
)

// micNow lists the programs recording from a microphone right now. The recorder asks Windows'
// audio sessions (the reliable source); the list Windows keeps for its privacy page is added to it,
// because on some builds one of the two is empty.
func micNow() []string {
	names := micUsers()
	cmd := exec.Command(bin("mitra-ear"), "who")
	hide(cmd)
	if out, err := cmd.Output(); err == nil {
		var v struct {
			Using []struct{ Name string }
		}
		if json.Unmarshal(out, &v) == nil {
			for _, u := range v.Using {
				names = append(names, u.Name)
			}
		}
	}
	seen, out := map[string]bool{}, []string{}
	for _, n := range names {
		if k := strings.ToLower(n); n != "" && !seen[k] {
			seen[k] = true
			out = append(out, n)
		}
	}
	return out
}

// A meeting is "a program people hold calls in is using the microphone". Someone talking near the
// laptop is not one, and neither is a dictation tool or Mitra's own recorder.
var meetingApps = []struct{ match, label string }{
	{"teams", "Microsoft Teams"}, {"zoom", "Zoom"}, {"webex", "Webex"}, {"slack", "Slack"}, {"discord", "Discord"},
	{"whatsapp", "WhatsApp"}, {"skype", "Skype"}, {"gotomeeting", "GoTo Meeting"}, {"bluejeans", "BlueJeans"},
	{"chrome", "a call in Chrome"}, {"msedge", "a call in Edge"}, {"firefox", "a call in Firefox"}, {"brave", "a call in Brave"},
	{"opera", "a call in Opera"}, {"arc", "a call in Arc"},
}

type micUser struct {
	Name    string `json:"name"`
	Label   string `json:"label"`
	Meeting bool   `json:"meeting"`
}

func classifyMic(names []string) []micUser {
	out := []micUser{}
	for _, n := range names {
		low := strings.ToLower(n)
		if strings.Contains(low, "mitra") {
			continue // our own recorder
		}
		u := micUser{Name: n, Label: n}
		for _, m := range meetingApps {
			if strings.Contains(low, m.match) {
				u.Label, u.Meeting = m.label, true
				break
			}
		}
		out = append(out, u)
	}
	return out
}

// meetRoutes: which programs are using the microphone, for an app that declares the "meetings"
// service. It reads a list Windows keeps; it never opens the microphone itself.
func meetRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/mic", func(w http.ResponseWriter, r *http.Request) {
		if appMode == "" || !appUses["meetings"] {
			fail(w, 403, "Only an app that declares the meetings service may ask who is using the microphone.")
			return
		}
		users := classifyMic(micNow())
		meeting := ""
		for _, u := range users {
			if u.Meeting {
				meeting = u.Label
				break
			}
		}
		writeJSON(w, 200, map[string]any{"using": users, "meeting": meeting})
	})
}

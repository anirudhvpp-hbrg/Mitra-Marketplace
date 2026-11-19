//go:build windows

package main

import (
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

// Windows records, per program, when it last started and stopped using the microphone (it is what
// Settings > Privacy > Microphone shows). A program whose "stopped" time is zero is using it now.
// Reading that is how Mitra knows a meeting app is in a call, without listening to anything.
const micStore = `Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone`

func regSubkeys(k syscall.Handle) []string {
	var out []string
	for i := uint32(0); ; i++ {
		buf := make([]uint16, 512)
		n := uint32(len(buf))
		if syscall.RegEnumKeyEx(k, i, &buf[0], &n, nil, nil, nil, nil) != nil {
			return out
		}
		out = append(out, syscall.UTF16ToString(buf[:n]))
	}
}

func regQword(k syscall.Handle, name string) (uint64, bool) {
	var v uint64
	var typ uint32
	n := uint32(8)
	p, _ := syscall.UTF16PtrFromString(name)
	if syscall.RegQueryValueEx(k, p, nil, &typ, (*byte)(unsafe.Pointer(&v)), &n) != nil || n != 8 {
		return 0, false
	}
	return v, true
}

func regOpen(parent syscall.Handle, path string) (syscall.Handle, bool) {
	var k syscall.Handle
	p, _ := syscall.UTF16PtrFromString(path)
	if syscall.RegOpenKeyEx(parent, p, 0, syscall.KEY_READ, &k) != nil {
		return 0, false
	}
	return k, true
}

// micUsers lists the programs using the microphone right now, by executable or package name.
func micUsers() []string {
	root, ok := regOpen(syscall.HKEY_CURRENT_USER, micStore)
	if !ok {
		return nil
	}
	defer syscall.RegCloseKey(root)
	var out []string
	check := func(parent syscall.Handle, key, shown string) {
		k, ok := regOpen(parent, key)
		if !ok {
			return
		}
		defer syscall.RegCloseKey(k)
		start, ok1 := regQword(k, "LastUsedTimeStart")
		stop, ok2 := regQword(k, "LastUsedTimeStop")
		if ok1 && ok2 && start != 0 && stop == 0 {
			out = append(out, shown)
		}
	}
	for _, name := range regSubkeys(root) {
		if name == "NonPackaged" {
			np, ok := regOpen(root, name)
			if !ok {
				continue
			}
			for _, exe := range regSubkeys(np) { // a full path with # in place of \
				check(np, exe, filepath.Base(strings.ReplaceAll(exe, "#", `\`)))
			}
			syscall.RegCloseKey(np)
			continue
		}
		check(root, name, name) // a packaged app: its package family name
	}
	return out
}

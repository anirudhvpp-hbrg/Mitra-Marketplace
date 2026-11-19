//go:build windows

package main

import (
	"os"
	"os/exec"
	"syscall"
)

const (
	createNoWindow        = 0x08000000
	createNewProcessGroup = 0x00000200
)

// hide keeps helper processes from flashing a console window.
func hide(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
}

// detach lets a process outlive the terminal that started it.
func detach(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow | createNewProcessGroup}
}

func browserCommand(url string) *exec.Cmd {
	return exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
}

// hiddenEntry: what Explorer hides by default (hidden or system), such as AppData, NetHood or
// desktop.ini. The entry's own attributes are read, so a link that is itself hidden is left out.
func hiddenEntry(e os.DirEntry) bool {
	info, err := e.Info()
	if err != nil {
		return false
	}
	if a, ok := info.Sys().(*syscall.Win32FileAttributeData); ok {
		return a.FileAttributes&(syscall.FILE_ATTRIBUTE_HIDDEN|syscall.FILE_ATTRIBUTE_SYSTEM) != 0
	}
	return false
}

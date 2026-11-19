//go:build !windows

package main

import (
	"os"
	"os/exec"
	"runtime"
	"syscall"
)

func hide(cmd *exec.Cmd) {}

// detach lets a process outlive the terminal that started it.
func detach(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

func browserCommand(url string) *exec.Cmd {
	if p, err := exec.LookPath("termux-open-url"); err == nil { // Android
		return exec.Command(p, url)
	}
	if runtime.GOOS == "darwin" {
		return exec.Command("open", url)
	}
	return exec.Command("xdg-open", url)
}

// hiddenEntry: names starting with a dot are already left out by the caller.
func hiddenEntry(e os.DirEntry) bool { return false }

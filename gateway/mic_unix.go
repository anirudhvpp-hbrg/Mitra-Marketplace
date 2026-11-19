//go:build !windows

package main

// micUsers lists the programs using the microphone right now. Only Windows is implemented; on
// other systems a meeting is not noticed and recording is started by hand.
func micUsers() []string { return nil }

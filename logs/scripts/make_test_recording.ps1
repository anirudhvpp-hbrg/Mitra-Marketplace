# Make a spoken test recording with Windows' built-in voice, for trying TwinMind.
#   powershell -File logs\scripts\make_test_recording.ps1 [-Out <path.wav>]
# Used on 2026-11-11 for the first end-to-end audio test. Synthetic speech is clean and has a
# single voice, so it proves the pipeline runs; it does not show accuracy on a real meeting.
param([string]$Out = "$HOME\Desktop\mitra-test-standup.wav")
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToWaveFile($Out)
$s.Rate = 1
$s.Speak("Morning everyone. Quick standup. The export job is done for PDF. CSV still fails on invoices with more than two hundred line items. Sam, please fix the CSV timeout by Thursday. Decision then: the release stays on the twentieth, with the twenty fourth as fallback. Dana will clear snapshots older than thirty days this afternoon. I will send the release note draft to marketing by Wednesday.")
$s.Dispose()
Write-Host "Wrote $Out"

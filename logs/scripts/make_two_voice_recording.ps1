# Make a short test conversation with two different Windows voices, for trying diarization.
#   powershell -File logs\scripts\make_two_voice_recording.ps1 [-Out <path.wav>]
# Two synthetic voices taking turns is the easiest case a diarizer can get: no overlap, no
# noise, clearly different speakers. It shows the pipeline works, not how it does on a real room.
param([string]$Out = "$HOME\Desktop\mitra-two-voices.wav")
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }
if ($voices.Count -lt 2) { throw "Only one voice is installed ($voices); two are needed." }
$a, $b = $voices[0], $voices[1]
$lines = @(
    @($a, "Morning. Let's start with the invoice export. Where are we on the CSV problem?"),
    @($b, "PDF export is done. CSV still fails on invoices with more than two hundred line items. I can stream the rows instead of loading them all."),
    @($a, "Good. Please fix the CSV timeout by Thursday."),
    @($b, "I will. If it lands by Thursday we keep the release on the twentieth."),
    @($a, "Decision then: the release stays on the twentieth, with the twenty fourth as the fallback."),
    @($b, "One more thing. The staging database is at ninety percent disk. I will clear old snapshots this afternoon.")
)
$s.SetOutputToWaveFile($Out)
foreach ($l in $lines) { $s.SelectVoice($l[0]); $s.Speak($l[1]) }
$s.Dispose()
Write-Host "Wrote $Out with voices: $a / $b"

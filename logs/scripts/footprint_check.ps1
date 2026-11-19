# Measure what Mitra holds in memory on the real install: the server, each kind of request, and
# the model while TwinMind writes notes for a short sample meeting.
#   powershell -File logs\scripts\footprint_check.ps1
# The sample notes file is deleted afterwards. Every wait has a limit, so it cannot hang.
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$r = Split-Path (Split-Path $PSScriptRoot)
$m = "$r\bin\mitra-marketplace.exe"
$b = "http://127.0.0.1:7421"
& $m list | Out-Null

$t = "$env:TEMP\mitra-standup.txt"
@"
Priya: Morning everyone. Quick standup. Let's start with the invoice export.
Sam: The export job is done for PDF. CSV still fails on invoices with more than two hundred line items, it times out after thirty seconds.
Priya: Okay. Sam, please fix the CSV timeout by Thursday.
Dana: The new onboarding screens are in review. Two comments from design about the colour contrast on the second screen. I will address them today.
Dana: If the CSV fix lands by Thursday we keep the twentieth. If not we slip to the twenty-fourth.
Priya: Decision then: release stays on the twentieth, with the twenty-fourth as fallback.
Sam: The staging database is at ninety percent disk. Someone needs to clear old snapshots.
Dana: I will clear snapshots older than thirty days this afternoon.
Priya: I will send the release note draft to marketing by Wednesday.
"@ | Set-Content $t -Encoding utf8

Invoke-RestMethod "$b/api/apps" | Out-Null
Invoke-RestMethod "$b/api/convert?path=$([uri]::EscapeDataString("$r\README.md"))" | Out-Null
Invoke-RestMethod "$b/api/memory/report?days=7" | Out-Null

$job = Invoke-RestMethod -Method Post "$b/api/apps/twinmind/job/run" -ContentType 'application/json' `
    -Body (@{ path = $t; title = "Footprint check"; attendees = "Priya, Sam, Dana" } | ConvertTo-Json)
$j = $null
foreach ($i in 1..120) {
    Start-Sleep -Milliseconds 800
    $j = Invoke-RestMethod "$b/api/jobs/$($job.id)"
    if ($j.status -in 'done', 'failed') { break }
}
"TwinMind job: $($j.status) in $($j.seconds) s  $($j.error)"
if ($j.status -eq 'done') {
    ((Get-Content $j.result.path -Raw) -split '## Transcript')[0] -split "`n" | Select-Object -Skip 10
    Remove-Item $j.result.path -Confirm:$false
}
Remove-Item $t -Confirm:$false

"--- worker RAM per route today"
python "$r\logs\scripts\worker_ram.py" | Select-Object -First 10
$s = Invoke-RestMethod "$b/api/system"
"--- server: {0:N0} MB working set; models running now: {1}" -f ((Get-Process mitra-marketplace | Measure-Object WorkingSet64 -Sum).Sum / 1MB), $s.leases.Count
"--- last model run"
Get-Content "$env:USERPROFILE\.mitra\memory\events\$(Get-Date -Format yyyy-MM-dd).jsonl" | Select-String '"model.run"' | Select-Object -Last 1 | ForEach-Object { $_.Line }

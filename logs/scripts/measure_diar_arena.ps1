# Measures the speaker model's virtual memory reservation (commit) and working set for several
# arena settings, on a looped copy of a real recording. Prints numbers only.
#   pwsh logs/scripts/measure_diar_arena.ps1 "<recording>" [seconds]
param([string]$Recording, [int]$Seconds = 300)
$root = Split-Path (Split-Path $PSScriptRoot)
$tmp = "$HOME\.mitra\tmp"; New-Item -ItemType Directory -Force $tmp | Out-Null
$wav = "$tmp\arena-test.16k.wav"
ffmpeg -y -v error -stream_loop -1 -i $Recording -t $Seconds -ar 16000 -ac 1 -c:a pcm_s16le $wav
$model = (Get-ChildItem "$root\models", 'E:\Local AI Models' -Recurse -Filter *.gguf -ErrorAction SilentlyContinue |
  Where-Object FullName -match 'nemotron-3-diarization-audiocpp' | Select-Object -First 1).FullName
$exe = "$root\runtimes\audio.cpp\audiocpp_cli.exe"
$sets = @(
  @(),
  @('--load-option', 'graph_arena_mb=256', '--load-option', 'weight_context_mb=256'),
  @('--load-option', 'graph_arena_mb=96', '--load-option', 'weight_context_mb=128'),
  @('--load-option', 'graph_arena_mb=48', '--load-option', 'weight_context_mb=112')
)
foreach ($opt in $sets) {
  $out = "$tmp\arena-turns.json"; Remove-Item $out -ErrorAction SilentlyContinue
  $a = @('--task', 'diar', '--family', 'nemotron_3_diar', '--model', "`"$model`"", '--model-spec-override', 'embedded',
    '--backend', 'cpu', '--threads', '10', '--mode', 'streaming', '--audio', "`"$wav`"", '--turns-out', "`"$out`"") + $opt
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $p = Start-Process -FilePath $exe -ArgumentList $a -PassThru -NoNewWindow -RedirectStandardOutput "$tmp\arena-out.txt" -RedirectStandardError "$tmp\arena-err.txt"
  [long]$mp = 0; [long]$mw = 0
  while (-not $p.HasExited) {
    $p.Refresh()
    if ($p.PrivateMemorySize64 -gt $mp) { $mp = $p.PrivateMemorySize64 }
    if ($p.WorkingSet64 -gt $mw) { $mw = $p.WorkingSet64 }
    Start-Sleep -Milliseconds 150
  }
  $n = 0; $h = '-'
  if (Test-Path $out) { $n = ((Get-Content $out -Raw) -split '"speaker').Count - 1; $h = (Get-FileHash $out).Hash.Substring(0, 10) }
  "opts [$($opt -join ' ')] exit $($p.ExitCode) commit $([int]($mp/1MB)) MB ws $([int]($mw/1MB)) MB $([int]$sw.Elapsed.TotalSeconds) s turns~$n hash $h"
  if ($p.ExitCode -ne 0) { Get-Content "$tmp\arena-err.txt" -Tail 3 }
}
Remove-Item $wav, "$tmp\arena-turns.json", "$tmp\arena-out.txt", "$tmp\arena-err.txt" -ErrorAction SilentlyContinue

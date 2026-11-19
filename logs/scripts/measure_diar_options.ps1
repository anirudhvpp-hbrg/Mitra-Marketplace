# Which spelling of the arena options the speaker runtime honours: tries several on a 20-second
# clip and prints the virtual memory reserved (commit) for each. Numbers only.
#   pwsh logs/scripts/measure_diar_options.ps1 "<recording>"
param([string]$Recording)
$root = Split-Path (Split-Path $PSScriptRoot)
$tmp = "$HOME\.mitra\tmp"; New-Item -ItemType Directory -Force $tmp | Out-Null
$wav = "$tmp\opt-test.16k.wav"
ffmpeg -y -v error -i $Recording -t 20 -ar 16000 -ac 1 -c:a pcm_s16le $wav
$model = (Get-ChildItem "$root\models", 'E:\Local AI Models' -Recurse -Filter *.gguf -ErrorAction SilentlyContinue |
  Where-Object FullName -match 'nemotron-3-diarization-audiocpp' | Select-Object -First 1).FullName
$exe = "$root\runtimes\audio.cpp\audiocpp_cli.exe"
$sets = @(
  @('--session-option', 'graph_arena_mb=64', '--session-option', 'weight_context_mb=128'),
  @('--load-option', 'diar.graph_arena_mb=64', '--load-option', 'diar.weight_context_mb=128'),
  @('--session-option', 'diar.graph_arena_mb=64', '--session-option', 'diar.weight_context_mb=128'),
  @('--load-option', 'nemotron_3_diar.graph_arena_mb=64', '--load-option', 'nemotron_3_diar.weight_context_mb=128'),
  @('--request-option', 'graph_arena_mb=64'),
  @('--load-option', 'weight_context_mb=8'),
  @('--load-option', 'graph_arena_mb=1')
)
foreach ($opt in $sets) {
  $out = "$tmp\opt-turns.json"; Remove-Item $out -ErrorAction SilentlyContinue
  $a = @('--task', 'diar', '--family', 'nemotron_3_diar', '--model', "`"$model`"", '--model-spec-override', 'embedded',
    '--backend', 'cpu', '--threads', '10', '--mode', 'streaming', '--audio', "`"$wav`"", '--turns-out', "`"$out`"") + $opt
  $p = Start-Process -FilePath $exe -ArgumentList $a -PassThru -NoNewWindow -RedirectStandardOutput "$tmp\opt-out.txt" -RedirectStandardError "$tmp\opt-err.txt"
  [long]$mp = 0
  while (-not $p.HasExited) { $p.Refresh(); if ($p.PrivateMemorySize64 -gt $mp) { $mp = $p.PrivateMemorySize64 }; Start-Sleep -Milliseconds 50 }
  "[$($opt -join ' ')] exit $($p.ExitCode) commit $([int]($mp/1MB)) MB turns file: $(Test-Path $out)"
  if ($p.ExitCode -ne 0) { (Get-Content "$tmp\opt-err.txt" -Tail 2) -join ' | ' }
}
Remove-Item $wav, "$tmp\opt-turns.json", "$tmp\opt-out.txt", "$tmp\opt-err.txt" -ErrorAction SilentlyContinue

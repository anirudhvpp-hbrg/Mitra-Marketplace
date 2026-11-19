# Bring the package back under the 2 GB limit after Whisper medium (514 MB) was added (2026-11-13).
#   - audio.cpp: the server and the GGUF tool are never run by Mitra (only audiocpp_cli is)      -41 MB
#   - models/: Whisper small and Whisper tiny are no longer anyone's first choice               -212 MB
#   - models/: Whisper base (57 MB) goes in as the packaged step-down for speech                 +57 MB
# Everything removed goes to the Recycle Bin, and all three models stay in the library on E:.
$root = Split-Path (Split-Path $PSScriptRoot)
Add-Type -AssemblyName Microsoft.VisualBasic
function Recycle($p) {
  if (Test-Path $p -PathType Container) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p, 'OnlyErrorDialogs', 'SendToRecycleBin'); "to Recycle Bin: $p" }
  elseif (Test-Path $p) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p, 'OnlyErrorDialogs', 'SendToRecycleBin'); "to Recycle Bin: $p" }
}
Recycle "$root\runtimes\audio.cpp\audiocpp_server.exe"
Recycle "$root\runtimes\audio.cpp\audiocpp_gguf.exe"
Recycle "$root\models\whisper-small-q5_1-cpp"
Recycle "$root\models\whisper-tiny-en-cpp"
$src = Get-ChildItem 'E:\Local AI Models' -Recurse -Directory -Filter 'whisper-base-q5_1-cpp' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($src -and -not (Test-Path "$root\models\whisper-base-q5_1-cpp")) {
  Copy-Item $src.FullName "$root\models\whisper-base-q5_1-cpp" -Recurse
  "copied whisper-base-q5_1-cpp into the package"
}

# Build Mitra on Windows. Needs: Go, Rust (cargo), Python 3.10+.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
New-Item -ItemType Directory -Force "$root\bin" | Out-Null

Push-Location "$root\governor"
cargo build --release
Copy-Item "target\release\mitra-governor.exe" "$root\bin\" -Force
Copy-Item "target\release\mitra-open.exe" "$root\bin\" -Force   # windowless handler for files opened from Explorer
Pop-Location

Push-Location "$root\ear"
cargo build --release
Copy-Item "target\release\mitra-ear.exe" "$root\bin\" -Force     # records the microphone and system audio as two tracks
Pop-Location

Push-Location "$root\gateway"
go build -ldflags "-s -w" -o "$root\bin\mitra-marketplace.exe" .
Pop-Location

python -m pip install --user --quiet pypdf

Write-Host "Built into $root\bin"
Write-Host "To use 'mitra-marketplace' from any terminal, add $root\bin to your PATH."

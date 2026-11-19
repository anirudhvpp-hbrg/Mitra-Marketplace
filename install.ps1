# Install Mitra Marketplace on Windows from a release zip found on this system.
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Target <folder>] [-Zip <path>]
# It searches the usual places for the newest mitra-marketplace-*.zip, unpacks it, builds only
# if the zip has no Windows binaries, and puts `mitra-marketplace` on your PATH.
param([string]$Target = "$HOME\mitra-marketplace", [string]$Zip = "")
$ErrorActionPreference = "Stop"

if (-not $Zip) {
    $places = @($PSScriptRoot, "$HOME\Dropbox\Mitra\releases", "$HOME\Dropbox", "$HOME\Downloads", "$HOME\Desktop", "$HOME\Documents", $HOME) |
        Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
    Write-Host "Searching for mitra-marketplace-*.zip in: $($places -join ', ')"
    $found = foreach ($p in $places) { Get-ChildItem $p -Filter "mitra-marketplace-*.zip" -Recurse -Depth 2 -ErrorAction SilentlyContinue }
    # the name ends in yyyymmdd-hhmmss, so the newest sorts last
    $pick = $found | Sort-Object { ($_.BaseName -split '-')[-2..-1] -join '-' } | Select-Object -Last 1
    if (-not $pick) { throw "No mitra-marketplace-*.zip found. Copy one to Downloads, or pass -Zip <path>." }
    $Zip = $pick.FullName
}
Write-Host "Using $Zip"

$sha = "$Zip.sha256"
if (Test-Path $sha) {
    $want = ((Get-Content $sha -Raw) -split '\s+')[0]
    if ($want -ne (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()) { throw "Checksum mismatch: the zip is incomplete or was changed." }
    Write-Host "Checksum verified."
}

New-Item -ItemType Directory -Force $Target | Out-Null
Expand-Archive $Zip -DestinationPath $Target -Force
$rel = Get-Content "$Target\release.json" -Raw | ConvertFrom-Json
if ($rel.os -ne "windows" -or -not (Test-Path "$Target\bin\mitra-marketplace.exe")) {
    Write-Host "This zip has binaries for $($rel.os)/$($rel.arch); building for Windows (needs Go and Rust)..."
    & "$Target\build.ps1"
}
python -m pip install --user --quiet pypdf 2>$null

$bin = "$Target\bin"
$path = [Environment]::GetEnvironmentVariable("Path", "User")
if (($path -split ';') -notcontains $bin) {
    [Environment]::SetEnvironmentVariable("Path", ($path.TrimEnd(';') + ";" + $bin), "User")
    Write-Host "Added $bin to your PATH. Open a new terminal to use it."
}
Write-Host "Installed Mitra $($rel.version) (built $($rel.built)) in $Target"
Write-Host "Run: mitra-marketplace"

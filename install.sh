#!/usr/bin/env sh
# Install Mitra Marketplace on macOS, Linux or Android Termux from a release zip on this system.
#   sh install.sh [target-folder] [zip]
# It searches the usual places for the newest mitra-marketplace-*.zip, unpacks it, builds when
# the zip has no binaries for this platform (needs Go and Rust), and links the command.
#   Termux first:  pkg install python golang rust
set -e
target="${1:-$HOME/mitra-marketplace}"
zip="$2"
here="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$zip" ]; then
  echo "Searching for mitra-marketplace-*.zip ..."
  zip="$(for d in "$here" "$HOME/Dropbox/Mitra/releases" "$HOME/Dropbox" "$HOME/Downloads" "$HOME/Desktop" "$HOME/Documents" \
                 "$HOME/storage/shared/Download" "$HOME/storage/shared/Dropbox" "$HOME"; do
           [ -d "$d" ] && find "$d" -maxdepth 3 -name 'mitra-marketplace-*.zip' 2>/dev/null
         done | awk -F/ '{print $NF "\t" $0}' | sort | tail -1 | cut -f2)"
  [ -n "$zip" ] || { echo "No mitra-marketplace-*.zip found. Copy one to Downloads, or pass its path as the second argument."; exit 1; }
fi
echo "Using $zip"

if [ -f "$zip.sha256" ]; then
  want="$(cut -d' ' -f1 "$zip.sha256")"
  have="$(python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$zip")"
  [ "$want" = "$have" ] || { echo "Checksum mismatch: the zip is incomplete or was changed."; exit 1; }
  echo "Checksum verified."
fi

mkdir -p "$target"
python3 -m zipfile -e "$zip" "$target"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -o 2>/dev/null)" in Android) os=android;; esac
arch="$(uname -m)"; case "$arch" in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; esac
built_for="$(python3 -c "import json,sys;r=json.load(open(sys.argv[1]));print(r['os']+'/'+r['arch'])" "$target/release.json")"
if [ "$built_for" != "$os/$arch" ] || [ ! -f "$target/bin/mitra-marketplace" ]; then
  echo "This zip has binaries for $built_for; building for $os/$arch (needs Go and Rust)..."
  sh "$target/build.sh"
fi
chmod +x "$target/bin/"* 2>/dev/null || true
python3 -m pip install --user --quiet pypdf 2>/dev/null || echo "pypdf not installed; PDF conversion is unavailable until it is."

linkdir="${PREFIX:+$PREFIX/bin}"; linkdir="${linkdir:-$HOME/.local/bin}"
mkdir -p "$linkdir"
ln -sf "$target/bin/mitra-marketplace" "$linkdir/mitra-marketplace"
echo "Installed in $target and linked into $linkdir"
echo "Run: mitra-marketplace"

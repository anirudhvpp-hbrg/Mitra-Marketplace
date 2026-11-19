#!/usr/bin/env sh
# Build Mitra on macOS, Linux or Android Termux. Needs: Go, Rust (cargo), Python 3.10+.
#   Termux:  pkg install golang rust python
#   macOS:   brew install go rust python
set -e
root="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$root/bin"

(cd "$root/governor" && cargo build --release && cp target/release/mitra-governor "$root/bin/")
(cd "$root/gateway" && go build -ldflags "-s -w" -o "$root/bin/mitra-marketplace" .)

python3 -m pip install --user --quiet pypdf || echo "pypdf not installed: PDF conversion will be unavailable until it is."

echo "Built into $root/bin"
echo "To use 'mitra-marketplace' from any terminal: ln -s \"$root/bin/mitra-marketplace\" ~/.local/bin/  (Termux: \$PREFIX/bin/)"

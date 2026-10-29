#!/bin/sh
# Install or update rem: curl -fsSL https://raw.githubusercontent.com/<you>/rem/main/install.sh | sh
set -e
SRC="${REM_SOURCE:-https://raw.githubusercontent.com/mrlucciola/rem/main/rem}"
DIR="$HOME/.rem"
mkdir -p "$DIR"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$SRC" -o "$DIR/rem.new"
else
  wget -qO "$DIR/rem.new" "$SRC"
fi
chmod +x "$DIR/rem.new"
mv "$DIR/rem.new" "$DIR/rem"
"$DIR/rem" init

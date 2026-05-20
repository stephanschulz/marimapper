#!/bin/sh
set -e
CACHE="${MARIUVC_CACHE:-$HOME/.cache/marimapper/uvc-util}"
REPO="${UVC_UTIL_REPO:-https://github.com/jtfrey/uvc-util.git}"
SRC="$CACHE/src"
BIN="$CACHE/uvc-util"

if [ ! -d "$SRC/.git" ]; then
  mkdir -p "$CACHE"
  git clone --depth 1 "$REPO" "$SRC"
fi

cd "$SRC/src"
gcc -o "$BIN" -framework IOKit -framework Foundation \
  uvc-util.m UVCController.m UVCType.m UVCValue.m

echo "Built: $BIN"
"$BIN" --list-devices

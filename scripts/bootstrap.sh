#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo 'Current application build supports macOS on Apple Silicon.' >&2
  exit 1
fi
command -v uv >/dev/null
command -v exiftool >/dev/null
xcrun --find clang >/dev/null
# A standalone managed runtime can be embedded. Do not embed a Homebrew
# framework interpreter by copying its executable without its framework.
uv python install 3.12.13
uv venv --managed-python --python 3.12.13 --seed portable/.venv
uv pip install --python portable/.venv/bin/python -r requirements-dev.txt
sh portable/build_mac.sh

#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
sh portable/build_mac.sh
portable/.venv/bin/python scripts/build_references.py
portable/.venv/bin/python -m unittest discover -s portable/tests -p 'test_*.py' -v
portable/.venv/bin/python macos/tests/run_detail_mode_model_check.py

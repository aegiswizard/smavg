#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running Smavg release verification..."
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 -m compileall -q src tests
PYTHONPATH=src python3 -m smavg.cli plugin build --force --json >/tmp/smavg-plugin-build.json
PYTHONPATH=src python3 -m smavg.cli plugin verify --json >/tmp/smavg-plugin-verify.json
echo "Smavg release verification passed."

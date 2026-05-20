#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m smavg.cli plugin build --force
PYTHONPATH=src python3 -m smavg.cli plugin verify

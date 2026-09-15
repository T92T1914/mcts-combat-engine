#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python demo.py boss --sims 50 --seed 7 --horizon 2

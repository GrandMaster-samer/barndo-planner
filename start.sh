#!/usr/bin/env bash
# One-click start for Mac / Linux: creates a virtual env, installs, runs the app.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
pip install -q -r requirements.txt
if [ -f .env ]; then set -a; source .env; set +a; fi
python -m barndo init
echo "Open http://localhost:8000"
python -m barndo serve --port 8000

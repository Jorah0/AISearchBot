#!/usr/bin/env bash
# Lodestar runtime starter (macOS/Linux):  ./start.sh [--no-loop] [--no-ui] [--every 30] [--port 8765]
set -e
cd "$(dirname "$0")"
EVERY=30; PORT=8765; LOOP=1; UI=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-loop) LOOP=0 ;;
    --no-ui) UI=0 ;;
    --every) EVERY=$2; shift ;;
    --port) PORT=$2; shift ;;
  esac
  shift
done
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --disable-pip-version-check -e .
.venv/bin/lodestar init
.venv/bin/lodestar providers
if [ "$LOOP" = 1 ]; then
  mkdir -p ~/.lodestar
  nohup .venv/bin/lodestar run --every "$EVERY" >> ~/.lodestar/run.log 2>&1 &
  echo "monitor loop started (pid $!, log ~/.lodestar/run.log). Permanent: lodestar schedule install"
fi
if [ "$UI" = 1 ]; then .venv/bin/lodestar ui --port "$PORT"; else echo "UI skipped. Run: .venv/bin/lodestar ui"; fi

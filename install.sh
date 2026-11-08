#!/usr/bin/env bash
# Lodestar installer (macOS / Linux):  ./install.sh [--schedule] [--every 30]
# 1) .venv with Lodestar  2) ~/.lodestar data files  3) .env from .env.example  4) a desktop launcher (Linux) or
# an alias hint (macOS)  5) --schedule: a cron line that runs `lodestar run --once` every N minutes.
set -e
cd "$(dirname "$0")"
EVERY=30; SCHEDULE=0
while [ $# -gt 0 ]; do case "$1" in --schedule) SCHEDULE=1 ;; --every) EVERY=$2; shift ;; esac; shift; done
command -v python3 >/dev/null || { echo "Python 3.11+ is required"; exit 1; }
python3 -c "import sys; sys.exit(sys.version_info < (3, 11))" || { echo "Python 3.11+ is required (found $(python3 --version 2>&1))"; exit 1; }
echo "[1/5] venv";        [ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --disable-pip-version-check -e ".[pdf]"
echo "[2/5] data files"; .venv/bin/lodestar init >/dev/null
echo "[3/5] .env";        [ -f .env ] || cp .env.example .env
JB="$(pwd)/.venv/bin/lodestar"
if [ "$(uname)" = "Linux" ] && [ -d "$HOME/.local/share/applications" ]; then
  echo "[4/5] desktop launcher"
  cat > "$HOME/.local/share/applications/lodestar.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Lodestar
Comment=Job-search workbot: monitor loop + web UI
Exec=$JB app
Icon=$(pwd)/assets/lodestar.png
Terminal=true
Categories=Office;
DESK
else
  echo "[4/5] add to your shell profile:  alias lodestar='$JB'"
fi
if [ "$SCHEDULE" = 1 ]; then
  echo "[5/5] cron";  ( crontab -l 2>/dev/null | grep -v "lodestar run --once"; echo "*/$EVERY * * * * $JB run --once >> ${LODESTAR_HOME:-$HOME/.lodestar}/cron.log 2>&1" ) | crontab -
else
  echo "[5/5] background task skipped (re-run with --schedule)"
fi
echo "Installed. Next: edit ${LODESTAR_HOME:-~/.lodestar}/profile.md, then: $JB vault set ANTHROPIC_API_KEY ; $JB app"

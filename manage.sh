#!/bin/bash
# ai-leverage/manage.sh
# The menu for everything in stack/, grouped in the order the parts build on
# each other: downloaders get models onto this PC, engines run them, and
# services are what you use. Below them, the desktop apps in apps/. Start,
# stop, update and follow the logs of each engine and service, run the
# scripts a folder brings along, and install and update the apps.
# A new folder shows up on its own: a compose.yaml gives it Start/Stop, every
# executable *.sh in it becomes an entry, and an app.conf makes it an app.
#
# The menu itself is src/python/menu.py, drawn with Textual. This gets it
# ready and starts it:
#   1. moves installs from before stack/ was split into groups
#   2. sets up the menu's Python environment in src/python/.venv with uv:
#      Textual is downloaded once (about 13 MB), and again only when an
#      update of ai-leverage moves its version (src/python/uv.lock)
#   3. asks for your password for sudo, which the menu needs to read what
#      runs from Docker, before the menu fills the screen

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MENU_DIR="$BASE_DIR/src/python"

# Installs from before stack/ was split into groups keep their settings and data
# in the old folders until this moves them. It does nothing once they're moved.
"$BASE_DIR/src/bash/migrate-stack-layout.sh" || exit 1

if ! command -v uv &> /dev/null; then
  echo "The menu needs uv, which sets up its Python environment. Run ./bootstrap.sh first."
  exit 1
fi
# Offline first: nothing to download when the environment is in place
if ! uv sync --project "$MENU_DIR" --locked --offline --quiet 2> /dev/null; then
  echo "Setting up the menu: uv downloads Textual, which draws it (about 13 MB, once)..."
  if ! uv sync --project "$MENU_DIR" --locked --quiet; then
    echo "Couldn't set up the menu's Python environment. See the messages above."
    exit 1
  fi
fi

# The menu never asks for a password over its own screen, so it's asked here
if ! sudo -n -v 2> /dev/null; then
  echo "The menu reads what runs from Docker, which needs sudo."
  sudo -v || echo "Without it, the menu can't show what runs. r in the menu asks again."
fi

exec "$MENU_DIR/.venv/bin/python" -I "$MENU_DIR/menu.py"

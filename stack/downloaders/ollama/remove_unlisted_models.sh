#!/bin/bash
# ai-leverage/stack/downloaders/ollama/remove_unlisted_models.sh
# Deletes downloaded models that aren't in models.txt any more, asking about
# each one first.
#
# It's sync_models.sh --remove-unlisted, as an entry of its own in the menu,
# which runs it as a notification and asks there.
#
# menu: console   (the menu shows what it prints without leaving the menu, and asks in its notification)
exec "$(dirname "${BASH_SOURCE[0]}")/sync_models.sh" --remove-unlisted "$@"

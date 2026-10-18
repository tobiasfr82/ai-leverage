#!/bin/bash
# ai-leverage/src/bash/ask.sh
# ask_yes_no QUESTION YES NO: a yes/no question, for a script that runs both
# by hand and from the menu. Returns 0 for yes. No is the answer unless you
# say yes, so a question about something that can't be undone stays safe.
#   - In a terminal it asks there: "QUESTION (y/N): ".
#   - Run from the menu as a notification, its card turns blue and waits; you
#     answer in its log window, "Yes, YES" or "No, NO". The menu hands the
#     script a channel for that, AI_LEVERAGE_ASK_FD, apart from its output.
#   - With neither, nobody can answer: no, without asking.
# can_ask: whether a question can be answered at all, in a terminal or from
# the menu. A script that can't do its job without answers checks it first.
#
# Sourced by the scripts that ask, such as
# stack/downloaders/ollama/sync_models.sh:
#   ask_yes_no "qwen3:8b (5.2 GB) isn't in models.txt. Delete it?" "delete it" "keep it"

# Whether the menu's channel is there: set, and open in this script
menu_asks() {
    [[ "${AI_LEVERAGE_ASK_FD:-}" =~ ^[0-9]+$ ]] && { true >&"$AI_LEVERAGE_ASK_FD"; } 2>/dev/null
}

can_ask() {
    [ -t 0 ] || menu_asks
}

ask_yes_no() {
    local question=$1 yes=$2 no=$3 answer=""
    if [ -t 0 ]; then
        read -r -p "$question (y/N): " answer
    elif menu_asks; then
        # One line on the channel, its parts apart by tabs; the answer comes back as y or n
        printf 'ask\t%s\t%s\t%s\n' "${question//$'\t'/ }" "${yes//$'\t'/ }" "${no//$'\t'/ }" >&"$AI_LEVERAGE_ASK_FD"
        read -r -u "$AI_LEVERAGE_ASK_FD" answer || answer=""
    fi
    [[ $answer == [yY] ]]
}

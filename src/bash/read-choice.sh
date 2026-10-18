#!/bin/bash
# ai-leverage/src/bash/read-choice.sh
# read_choice PROMPT: reads a choice in a script's own menu, typed and ended
# with Enter, into REPLY. Esc goes back, as everywhere in ai-leverage's menu:
# then it returns 1, and so does Ctrl+D. Arrow keys and the like are ignored.
#
# Sourced by the scripts with a menu of their own in the plain terminal, such
# as src/bash/pick-huggingface-model.sh and src/bash/check-updates.sh.

read_choice() {
    local text="" key rest
    printf '%s' "$1"
    while IFS= read -rsn1 key; do
        case "$key" in
            $'\e')
                # Esc alone goes back; the arrows and other keys send more after it
                rest=""
                while IFS= read -rsn1 -t 0.05 key; do rest+=$key; done
                if [ -z "$rest" ]; then
                    echo
                    return 1
                fi
                ;;
            "")
                echo
                REPLY=$text
                return 0
                ;;
            $'\x04')
                # Ctrl+D, which reaches a key-by-key read as a key, not as the end of input
                echo
                return 1
                ;;
            $'\x7f' | $'\b')
                if [ -n "$text" ]; then
                    text=${text%?}
                    printf '\b \b'
                fi
                ;;
            [[:print:]])
                text+=$key
                printf '%s' "$key"
                ;;
        esac
    done
    echo
    return 1
}

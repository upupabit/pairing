# Sourced by start.sh, stop.sh and status.sh: this install's pAIring processes (the server and its local
# instances), found by name and by their working folder, so another pAIring install on the same machine is
# never stopped or mistaken for this one. Needs APP_DIR set.

# The kernel truncates "pAIring-server-N" to 15 bytes ("pAIring-server-"), so this matches the server and
# every instance.
PAIRING_PROCESS_NAME="pAIring-server-?"

# A process's working folder: /proc on Linux, lsof on macOS.
process_cwd() {
    if [ -e "/proc/$1/cwd" ]; then
        readlink "/proc/$1/cwd" 2>/dev/null
    else
        lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p'
    fi
}

# The pids of this install's pAIring processes, one per line.
own_pairing_pids() {
    local own pid
    own="$(cd "$APP_DIR" && pwd -P)"
    for pid in $(pgrep -x "$PAIRING_PROCESS_NAME" 2>/dev/null); do
        [ "$(process_cwd "$pid")" = "$own" ] && echo "$pid"
    done
    return 0
}

# Stops them (TERM, then KILL after 10 s); returns 1 when there were none.
stop_own_pairing() {
    local pids
    pids="$(own_pairing_pids)"
    [ -n "$pids" ] || return 1
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    for _ in $(seq 1 20); do
        [ -n "$(own_pairing_pids)" ] || return 0
        sleep 0.5
    done
    # shellcheck disable=SC2046
    kill -9 $(own_pairing_pids) 2>/dev/null || true
    return 0
}

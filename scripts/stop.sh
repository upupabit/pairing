#!/usr/bin/env bash
# Stops a pAIring server started via scripts/start.sh: SIGTERM to the PID in run/pairing.pid, then any of this
# install's instances still running (own_processes.sh). Another pAIring install on this machine is never touched.
#
# Usage: bash scripts/stop.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

# Colored like uvicorn's "INFO:" lines (plain when not a terminal).
if [ -t 1 ]; then G=$'\033[32m'; R=$'\033[31m'; N=$'\033[0m'; else G=""; R=""; N=""; fi
info() { printf '%sINFO:%s %s\n' "$G" "$N" "$*"; }
err() { printf '%sERROR:%s %s\n' "$R" "$N" "$*"; }

PID_FILE="${PAIRING_PID_FILE:-$APP_DIR/run/pairing.pid}"
# shellcheck source=own_processes.sh
source "$APP_DIR/scripts/own_processes.sh"

if [[ ! -f "$PID_FILE" ]]; then
    if stop_own_pairing; then
        info "pAIring stopped (it had no PID file - started by an older script)"
    else
        info "pAIring is not running (no pid file)"
    fi
    exit 0
fi

PID="$(cat "$PID_FILE")"

if ! kill -0 "$PID" 2>/dev/null; then
    info "pAIring is not running (stale pid file, removing it)"
    rm -f "$PID_FILE"
    stop_own_pairing && info "stopped leftover pAIring instances" || true
    exit 0
fi

kill -TERM "$PID" 2>/dev/null || true

for _ in $(seq 1 30); do
    if ! kill -0 "$PID" 2>/dev/null; then
        rm -f "$PID_FILE"
        stop_own_pairing && info "stopped leftover pAIring instances" || true
        info "pAIring stopped (pid $PID)"
        exit 0
    fi
    sleep 0.5
done

info "pAIring did not stop gracefully, sending SIGKILL"
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
stop_own_pairing && info "stopped leftover pAIring instances" || true

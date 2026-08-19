#!/usr/bin/env bash
# Quiet launcher for the overseer dashboard.
#
# Runs the preflight checks (venv, port, frontend freshness) with tick
# output, asks whether to bind local-machine-only or the local network,
# then either reuses an already-running server or execs serve.py. Any
# extra arguments are passed through to serve.py (e.g. --root, --no-browser).
#
# Bind scope:
#   - Default is LOOPBACK (127.0.0.1) — local machine only, matching the
#     dashboard's single-user / no-auth design.
#   - Local network (0.0.0.0) is opt-in: chosen at the interactive prompt,
#     or forced by passing --host explicitly (which skips the prompt).
#   - With no TTY (e.g. driven by a tool/CI) the prompt is skipped and it
#     defaults to loopback; pass --host 0.0.0.0 to expose it deliberately.
#
# Exit codes: 0 = dashboard is up (freshly launched or already running),
# 1 = a preflight check failed (e.g. missing venv, port held by a stranger).
set -euo pipefail

# --- locate repo root (this script lives in plugins/overseer/dashboard/) ---
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
cd "$root"

py=".venv/bin/python"
serve="plugins/overseer/dashboard/serve.py"

# --- tick helpers --------------------------------------------------------
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
info() { printf '  \033[36m●\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; exit 1; }

# --- parse --port / --host out of the passthrough args -------------------
# The reuse probe always hits loopback (a 0.0.0.0-bound server answers there
# too), so we only need --port here. --host presence means the caller chose
# the bind scope explicitly, so we skip the interactive question.
port="8770"; host="127.0.0.1"; host_explicit=false
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[i]}" in
    --port)   port="${args[i+1]:-$port}" ;;
    --port=*) port="${args[i]#*=}" ;;
    --host)   host_explicit=true; host="${args[i+1]:-$host}" ;;
    --host=*) host_explicit=true; host="${args[i]#*=}" ;;
  esac
done

printf '\033[1moverseer dashboard — preflight\033[0m\n'

# 1) venv / interpreter -----------------------------------------------------
[ -x "$py" ] || fail "venv missing — expected $py (create it, then retry)"
ok "venv present ($py)"

# 2) port: free, already-ours, or held by a stranger -----------------------
if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
  if curl -fs -o /dev/null "http://127.0.0.1:$port/api/board" 2>/dev/null; then
    ok "frontend build in sync (skipped — reusing running server)"
    info "already running on :$port — reusing"
    printf '\n\033[1m→\033[0m dashboard is up: \033[4mhttp://127.0.0.1:%s/\033[0m\n' "$port"
    exit 0
  fi
  fail "port $port is held by another process (not the dashboard) — free it or pass --port"
fi
ok "port $port free"

# 3) bind scope: local machine only vs local network ----------------------
# Only asked when we're actually going to launch (not on reuse), and only
# when the caller hasn't already committed to a --host.
bind_args=()
if $host_explicit; then
  info "bind scope set by --host (passed through)"
elif [ -t 0 ]; then
  printf '  \033[36m?\033[0m bind scope — [\033[1mL\033[0mocal machine only / \033[1mn\033[0metwork]: '
  read -r reply || reply=""
  case "$reply" in
    [Nn]*)
      host="0.0.0.0"; bind_args=(--host 0.0.0.0)
      warn "binding 0.0.0.0 — reachable by any device on your LAN (the board has no auth)"
      ;;
    *)
      ok "bind scope: local machine only (127.0.0.1)"
      ;;
  esac
else
  info "non-interactive — defaulting to local machine only (pass --host 0.0.0.0 to expose)"
fi

# 4) frontend freshness: uncommitted src means dist may be stale -----------
if [ -n "$(git status --porcelain plugins/overseer/dashboard/frontend/src 2>/dev/null)" ]; then
  warn "frontend/src has uncommitted changes — rebuild dist before relying on the UI"
  warn "  (cd plugins/overseer/dashboard/frontend && npm run build)"
else
  ok "frontend build in sync"
fi

# 5) launch -----------------------------------------------------------------
printf '\n\033[1m→\033[0m launching http://%s:%s/  (Ctrl-C to stop)\n\n' "$host" "$port"
exec "$py" "$serve" ${bind_args[@]+"${bind_args[@]}"} "$@"

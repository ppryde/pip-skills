#!/usr/bin/env bash
# User-level install for context-vigil-mod: lists this plugin folder in
# env.CLAUDE_CODE_PLUGIN_DIRS of the user's settings.json only
# ($CLAUDE_CONFIG_DIR, else ~/.claude). Never a repo's .claude/settings.json.
set -euo pipefail
cmd="${1:-status}"
plugin="$(cd "$(dirname "$0")/.." && pwd)"
cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
file="$cfg/settings.json"
command -v jq >/dev/null || { echo "install.sh needs jq" >&2; exit 2; }

# status reads only; install/uninstall create the file on demand (see ensure_file).
current=""
[ -f "$file" ] && current=$(jq -r '.env.CLAUDE_CODE_PLUGIN_DIRS // ""' "$file")
ensure_file() { mkdir -p "$cfg"; [ -f "$file" ] || echo '{}' > "$file"; }
# grep without -q: under pipefail, -q exiting early can SIGPIPE the writer.
has_ours() { printf '%s' "$current" | tr ':' '\n' | grep -Fx "$plugin" >/dev/null; }

write() {
  local tmp
  tmp=$(mktemp "$cfg/.settings.XXXXXX")
  trap 'rm -f "$tmp"' RETURN
  jq --arg v "$1" 'if $v == "" then (.env |= (. // {} | del(.CLAUDE_CODE_PLUGIN_DIRS))) else (.env |= ((. // {}) + {CLAUDE_CODE_PLUGIN_DIRS: $v})) end' "$file" > "$tmp"
  # cat into the existing file: keeps a dotfiles symlink and the file's mode (mv would not).
  cat "$tmp" > "$file"
}

case "$cmd" in
  install)
    ensure_file
    # Keep in step with CLASSIC in core/interlock.ts (same match, TS form). TEMPORARY: removed when classic retires.
    if jq -r '[.hooks // {} | .[]? | .[]? | .hooks[]? | .command? // ""] | .[]' "$file" | grep -E '/scripts/context-vigil"[[:space:]]+hook[[:space:]]' >/dev/null; then
      echo "classic context-vigil hooks are installed in $file — uninstall classic first, then re-run (spec §7)" >&2
      exit 3
    fi
    if has_ours; then echo "context-vigil-mod already installed in $file"; exit 0; fi
    if [ -z "$current" ]; then write "$plugin"; else write "$current:$plugin"; fi
    echo "context-vigil-mod installed in $file — start a new session, then run /vigil-setup"
    ;;
  uninstall)
    if [ ! -f "$file" ] || ! has_ours; then echo "context-vigil-mod not installed in $file — nothing to remove"; exit 0; fi
    next=$(printf '%s' "$current" | tr ':' '\n' | grep -Fxv "$plugin" | paste -sd: - || true)
    write "$next"
    echo "context-vigil-mod removed from $file"
    ;;
  status)
    if has_ours; then echo "context-vigil-mod: installed ($file)"; else echo "context-vigil-mod: not installed ($file)"; fi
    ;;
  *) echo "usage: install.sh install|uninstall|status" >&2; exit 2 ;;
esac

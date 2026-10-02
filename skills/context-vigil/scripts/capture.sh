#!/usr/bin/env bash
# context-vigil capture-only status line: records the status-line payload for
# context measurement and prints nothing, so no visible status line appears.
input=$(cat)
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf '%s' "$input" | "$here/context-vigil" ingest 2>/dev/null || true
exit 0

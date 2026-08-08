#!/usr/bin/env bash
set -euo pipefail
# Re-entrant guard: the snapshot re-push sets this so we don't loop.
if [ -n "${OVERSEER_PREPUSH_REENTRANT:-}" ]; then exit 0; fi
repo_root="$(git rev-parse --show-toplevel)"
python "${OVERSEER_CLI:-$repo_root/plugins/overseer/scripts/cli.py}" \
  --root "$repo_root" backup >/dev/null 2>&1 || exit 0
if [ -n "$(git -C "$repo_root" status --porcelain .overseer/backups)" ]; then
  git -C "$repo_root" add .overseer/backups
  git -C "$repo_root" commit -q -m "chore(overseer): board snapshot"
  OVERSEER_PREPUSH_REENTRANT=1 git push "$@"
  exit 1   # abort the original push; the re-push above carried the snapshot
fi
exit 0

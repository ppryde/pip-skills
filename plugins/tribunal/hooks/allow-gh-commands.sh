#!/bin/bash
# Pre-approve specific gh commands used by tribunal:reckoning.
# Reads the PreToolUse hook payload from stdin and outputs an allow decision
# only for the exact gh commands the skill requires — nothing broader.

# Parse the command field from the JSON payload.
# Prefer jq (fast); fall back to python3 (more universally present on macOS/Linux).
# If neither is available, bow out silently and let Claude Code default to ask.
if command -v jq >/dev/null 2>&1; then
  cmd=$(jq -r '.tool_input.command // ""')
elif command -v python3 >/dev/null 2>&1; then
  cmd=$(python3 -c 'import sys, json; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("command",""))' 2>/dev/null)
else
  exit 0
fi

# Reject state-changing REST flags — keep the allowlist read-only.
case "$cmd" in
  "gh api graphql"*) ;;  # GraphQL has its own allowlist below
  "gh api"*)
    if [[ "$cmd" == *" -X "* || "$cmd" == *" --method "* || \
          "$cmd" == *" -f "* || "$cmd" == *" --field "* || \
          "$cmd" == *" -F "* || "$cmd" == *" --input "* || \
          "$cmd" == *" -d "* || "$cmd" == *" --data "* ]]; then
      exit 0
    fi
    ;;
esac

allow() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"tribunal: pre-approved gh command for PR review workflow"}}\n'
}

case "$cmd" in
  # Auth check
  "gh auth status"*)           allow ;;

  # Repo detection and fork check
  "gh repo view "*)             allow ;;

  # PR detection, listing, branch checkout
  "gh pr view "* | "gh pr list "* | "gh pr checkout "*)  allow ;;

  # REST API — specific resource paths only
  "gh api repos/"*"/pulls/"*)   allow ;;
  "gh api repos/"*"/issues/"*)  allow ;;
  "gh api repos/"*"/commits/"*) allow ;;
  "gh api repos/"*"/contents/"*) allow ;;

  # GraphQL — inspect query body and allow only the two operations tribunal needs:
  # - reviewThreads (fetch thread resolution status)
  # - resolveReviewThread (resolve a thread after actioning)
  "gh api graphql "*)
    if [[ "$cmd" == *"reviewThreads"* ]] || [[ "$cmd" == *"resolveReviewThread"* ]]; then
      allow
    fi
    ;;
esac

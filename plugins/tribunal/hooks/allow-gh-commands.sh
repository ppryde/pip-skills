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

# Reject any state-changing REST flag — match at token boundaries with any separator.
# Catches: -X POST | -XPOST | -X=POST | --method POST | --method=POST |
#          -f key=val | -fkey=val | -F raw | -d body | -dbody | --input file | --data ...
case "$cmd" in
  "gh api graphql"*) ;;  # GraphQL handled below
  "gh api"*)
    if [[ " $cmd " =~ [[:space:]](-X|--method|-f|--field|-F|--input|-d|--data)([[:space:]]|=|[!-~]) ]]; then
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

  # GraphQL — only allow the two operation shapes tribunal:reckoning emits.
  "gh api graphql "*)
    # Read-only thread fetch: must contain pullRequest( + reviewThreads( + isResolved,
    # and must NOT contain the keyword 'mutation' anywhere.
    if [[ "$cmd" == *"pullRequest("*"reviewThreads("*"isResolved"* ]] && \
       [[ "$cmd" != *"mutation"* ]]; then
      allow
    # Single-thread resolution mutation: must contain the literal mutation header
    # and threadId, and must NOT contain the read-side reviewThreads( field.
    elif [[ "$cmd" == *"mutation { resolveReviewThread(input:"*"threadId:"* ]] && \
         [[ "$cmd" != *"reviewThreads("* ]]; then
      allow
    fi
    ;;
esac

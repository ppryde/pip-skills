#!/bin/bash
# Pre-approve specific gh commands used by tribunal:reckoning.
# Reads the PreToolUse hook payload from stdin and outputs an allow decision
# only for the exact gh commands the skill requires — nothing broader.

cmd=$(jq -r '.tool_input.command // ""')

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

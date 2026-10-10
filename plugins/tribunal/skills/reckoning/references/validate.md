## Step 5: Validate Comments

Validate by default — reading the actual code catches false positives from bot reviewers commenting on outdated context. Only skip if the user explicitly asks to skip, or if there are >50 comments (offer to validate by category type — e.g. "Would you like me to validate all, or start with blocking/logic/security categories first?" — since priority tiers are not assigned until Step 6).

If the referenced file is in a generated/vendored directory (same indicators as Step 8: `vendor/`, `generated/`, `node_modules/`, `__generated__`, "DO NOT EDIT" header, lock files), skip line-level validation and mark as "Not assessed — generated/vendored file." Still present the comment with a note that fixes should target the source. Similarly, if the referenced file is binary (images, compiled artifacts, fonts — detected by extension like `.png`, `.jpg`, `.woff`, `.so`, `.wasm`), skip line-level validation and mark as "Not assessed — binary file."

If a comment has `line: null`, `line: 0`, or a negative line number, treat it as a comment without a specific line reference — skip line-level validation and mark as "Not assessed — no valid line reference." If the comment has a `path` but no valid line, still read the file to check the broader concern but do not attempt to validate a specific line.

For each comment targeting a specific file and line:

1. **Read the current code** at the referenced location
2. **Check if the issue exists** — does the code actually have the problem described?
3. **Assign a validity assessment:**

| Validity       | Criteria                                                                     |
| -------------- | ---------------------------------------------------------------------------- |
| Valid          | The issue clearly exists in the current code                                 |
| Likely valid   | The issue appears real but requires deeper context to confirm                |
| Uncertain      | Cannot determine validity without running the code or further investigation  |
| Likely invalid | The comment appears to misunderstand the code or references outdated context |

For PR-level comments without a specific code reference, skip validation and mark as "not assessed".

If the referenced file no longer exists or the line number is beyond the file's current length, first check for renames: `git diff <commit_id>..HEAD --diff-filter=R --name-status` to detect if the file was renamed rather than deleted. If a rename is detected, validate against the new file path at the corresponding line and append "— renamed from `old_path` to `new_path`" to the file reference. If truly deleted, mark validity as "Likely invalid" with the reason "referenced file/line no longer exists in the current branch." Still present the comment to the user — it may indicate an issue that was resolved by deletion.

When a comment's `commit_id` differs from the current HEAD (stale comment), the referenced line number may no longer correspond to the same code. Use `git diff <commit_id>..HEAD -- <path>` to check if the file has been modified. If the old commit SHA is unreachable (force-push), attempt validation against the current file content using code quoted in the comment body rather than relying on the line number. If the comment quotes no code context and the line has changed, mark validity as "Uncertain — file changed since review, line reference may be stale."

Do **not** hide or auto-dismiss any comments based on validity. Always present all comments to the user with the validity assessment clearly shown, so they can make the final call.

## Notes

- **Stale comments in triage**: When processing review comments, compare each review's `commit_id` to the PR's current `headRefOid`. If they differ, note the comment as targeting an older commit — this context is useful during validation (append "— on older commit" to the file:line reference)
- **Repo-root paths**: File paths from the GitHub API are relative to the repository root. Resolve all paths via `git rev-parse --show-toplevel` rather than the current working directory. If a file is outside the agent's accessible scope, mark validation as "Not assessed — file outside current working scope."

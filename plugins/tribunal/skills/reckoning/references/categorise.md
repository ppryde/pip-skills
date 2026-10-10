## Step 4: Categorise Comments

For each comment, classify across two dimensions:

### Source

| Label   | Criteria                                                                               |
| ------- | -------------------------------------------------------------------------------------- |
| `agent` | Username matches a known agent (see list below), or ends in `[bot]`, `-bot`, or `_bot` |
| `human` | All other authors                                                                      |

#### Known Agent Usernames

Classify the following as `agent` sources automatically:

- `github-actions`, `dependabot`, `renovate`, `codecov`, `sonarcloud`, `coderabbitai`
- `codeclimate`, `snyk-bot`, `lgtm-com`, `imgbot`, `greenkeeper`, `copilot`, `cubic`, `augment`
- Any username ending in `[bot]`, `-bot`, or `_bot` (requires a separator before `bot` to avoid misclassifying human usernames like `abbot`), or starting with `cubic-` or `augment-` (case-insensitive)

### Type

| Category | Description |
|----------|-------------|
| `blocking` | Review submission (from 3c) with CHANGES_REQUESTED state AND substantive body commentary not covered by inline comments. Do not create a synthetic `blocking` item solely because the review state is CHANGES_REQUESTED — the review state is already surfaced in the Step 7 header. Meta-commentary that simply references the inline comments without adding new concerns (e.g., "Please fix the inline comments", "LGTM after addressing the above") does not count as substantive body commentary. If all inline comments from a CHANGES_REQUESTED review are categorized as non-blocking types (style, docs, etc.), note this in the header: "Changes Requested by @author — all items are style/docs-level." If inline comments include `logic`, `tests`, or `security` types, note: "Changes Requested by @author — see High-priority items below." |
| `logic` | Correctness concerns, edge cases |
| `security` | Vulnerabilities or risky patterns |
| `tests` | Missing or inadequate test coverage |
| `style` | Code style, formatting, naming |
| `docs` | Documentation gaps |
| `suggestion` | Non-blocking improvements |
| `question` | Clarification needed, no action required |
| `praise` | Positive feedback |

Review bodies from APPROVED or COMMENT-state reviews may still contain actionable concerns. Parse the review body text (from 3c) for actionable content regardless of review state. Categorize any substantive concerns found using the standard type categories above. Do not assume APPROVED means no issues remain.

# Interactive output (convene Step 6, `interactive` output)

Walk the reconciled findings one at a time (most severe first) and ask: fix /
explain / skip / accept-exception.

- **fix** → make the change, then move on.
- **explain** → say why the rule fired (the finding's `rule` and `actual`), then ask again.
- **skip** → leave it.
- **accept-exception** → write an override into `.review-panel/decisions.yml`,
  keyed by the finding's `fingerprint` (never the per-run `id`):

  ```yaml
  overrides:
    <fingerprint>: { severity: info, reason: "<why this is accepted>" }
  ```
  Create the file if absent; keep existing entries. Read the file back first so
  a re-run of an already accepted finding is not duplicated.

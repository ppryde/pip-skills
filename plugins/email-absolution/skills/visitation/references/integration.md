# Integration points and error messages: Visitation

Read when the caller asks for a pre-push hook or a PR checklist, or when scope resolution fails.

## Integration points

### Pre-push Hook
```bash
#!/bin/bash
# .git/hooks/pre-push
echo "The Visitation begins..."
# Illustrative placeholder: this only echoes and does not gate a push.
# Adapt to your tooling: run /email-absolution:visitation
```

### PR Description Template
After running visitation, offer to generate a PR checklist. Build the "Tested in" line from `stack.rendering_targets` in config, and keep the plain-text item only if the ESP needs a separate plain-text part:

```markdown
## Email Template Checklist
- [ ] No mortal sins (run `/email-absolution:visitation`)
- [ ] Tested in <stack.rendering_targets, e.g. Outlook 2019, Gmail, Apple Mail>
- [ ] Plain-text version generated (if the ESP requires it)
- [ ] Subject and preheader reviewed
- [ ] Unsubscribe link present and tested
```

## Error handling

### Not in a git repository
> "The Visitation requires a git repository to determine scope.
> Name a specific file to audit: `/email-absolution:visitation <path/to/template>`"

### PR not found
> "PR #N was not found or is not accessible.
> Check the PR number or use `/email-absolution:visitation` to audit
> the current branch's changes instead."

### Changed files include no email templates
> "This branch's changes contain no email templates in the configured paths.
> All is quiet in the sanctum — no templates to examine."

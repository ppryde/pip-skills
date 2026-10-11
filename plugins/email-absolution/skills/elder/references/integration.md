# Integration points and customization

Read when the caller asks how to wire the Elder into a hook or CI, or how to exclude files or downgrade a rule.

## Integration points

These snippets are illustrative placeholders: they only echo and do **not**
gate a send. Wire in your own `claude -p` invocation and exit-status handling.

### Pre-send Hook
```bash
#!/bin/bash
# Run before deploying compiled email templates
echo "The Elder convenes..."
# claude -p "/email-absolution:elder full" — adapt to your CI tooling
```

### GitHub Actions
```yaml
name: Email Audit
on: [pull_request]
jobs:
  email-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4.2.2
      - name: Convene the Elder
        run: echo "Run /email-absolution:elder in your Claude Code workflow"
```

## Customization

### Excluding files
```yaml
# .email-absolution/config.yml
exclude:
  - "**/dist/**"
  - "**/build/**"
  - "**/*.compiled.html"
  - "templates/email/legacy/**"   # Archived templates
```

### Downgrading rules
```yaml
# .email-absolution/decisions.yml
overrides:
  RENDER-015:
    severity: counsel
    reason: "No Outlook users in audience — VML not required"
```

# Violation table contract

Each catalog row is a contract with Inquisition:

| Column | Rule |
|--------|------|
| **ID** | 3-letter prefix + hyphen + 3-digit number; never reuse |
| **Category** | Lowercase slug with hyphens (`layer-boundary`, `event-design`) |
| **Rule** | One line, imperative ("Domain must not import from infrastructure") |
| **Default Severity** | `error` (correctness: bugs, data loss, architectural decay, e.g. layer breach, mutable events) or `warning` (quality: naming, aggregate size, missing docs) |
| **What to scan for** | Concrete pattern (import paths, class patterns, file locations, LOC thresholds), never a shell command. If you cannot describe a detectable pattern, the rule is not auditable |

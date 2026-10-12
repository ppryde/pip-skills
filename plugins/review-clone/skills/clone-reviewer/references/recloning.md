# clone-reviewer: re-clone check (Step 1, right after the alias)

The alias already exists. Read it (`python3 <plugin>/scripts/persona_io.py read --alias '<alias>'`) and ask:

> A persona `<alias>` already exists (last scanned <last_scanned_at>).
> 1. **Refresh** — pull comments since last scan, fold into existing rules
> 2. **Modify handles & re-extract** — change handles, repo or filters, discard the old scrape and re-derive
> 3. **Fork to new alias** — create a separate persona; the original is not touched

Continue only after the user picks.

- **1 Refresh** → hand off to the `review-as` skill's refresh flow; stop here.
- **2 Modify** → ask which of handles, repo, filters and window change (the rest default to the persona's values). Collect as the clone variant **without `--since`**: a full pull replaces the corpus, deleting every `raw/pr-*.json` the run did not produce, so a removed handle's comments cannot leak into the new rules (add `--fresh` to ignore an old checkpoint). Then continue from Step 3; Step 6 overwrites the persona.
- **3 Fork** → ask for the new alias (it must not exist either), reuse the old answers as defaults, and restart from the next Step 1 question. Never write to the original.

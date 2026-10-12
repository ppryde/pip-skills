# Relationships (epics, dependencies, parking)

- **Epics are emergent.** Set a card's `parent` with `set-field <id> --parent
  <epic-id>` (`--parent ""` clears). A card with children *is* an epic — the
  index shows it with a rollup (`2/4 done · 260k/900k`) and its children nested.
  Keep trees shallow; deep nesting is discouraged.
- **Dependencies gate readiness.** Record card→card ordering with
  `depends <id> --on <dep>` (`--off` to remove). A card is **ready** only when
  every `depends_on` card is `done`; the index/resume show `ready` or
  `waiting on <id>`. Use `depends`, not `blocked_on`, for card ordering —
  `blocked_on` is for human/agent blocks only (`user:`/`agent:`). Cycles are
  refused. `depends --on` targets must be live cards: you can't depend on an
  already-done (archived) card.
- **Park to shelve.** `park <id>` sets a card aside without a blocker (distinct
  from `block`, which needs a reason, and `abandon`, which is terminal). It
  preserves stage/branch/worktree; `unpark <id>` resumes it (→ in-flight if it
  had a stage, else planned).

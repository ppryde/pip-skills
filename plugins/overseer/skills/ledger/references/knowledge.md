# Knowledge base

Durable, falsifiable facts in `board.db`; `knowledge/` is a generated view.

- `add-fact --statement "<falsifiable sentence>" --tags "testing,auth" --source <card-id> [--body "..."]`
  mints the next `KB-nnn`. Only mint facts that are falsifiable — "the auth
  fixtures share a DB schema", not "auth is tricky".
- `verify-fact <id>` when a fact is relied on and still holds — bumps its
  verified date and clears any stale mark.
- `retire-fact <id> [--superseded-by <id>]` when a fact is refuted or
  superseded — retires it, never deletes it.
- `facts [--tag <t>] [--stale] [--json]` lists live facts (`facts --count` prints
  just the count and a tag histogram: pick a `--tag` from it); facts older than
  90 days show `[STALE]` and must be re-verified before they are trusted.

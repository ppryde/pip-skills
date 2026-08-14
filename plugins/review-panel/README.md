# review-panel

Composable code review. A review is built from two axes bundled into a
named **profile**:

- **Reviewers** — *what* to examine (a lens: concern + voice).
- **Strategies** — *how* to orchestrate (committee, blind, informed,
  adversarial, dual+tiebreaker).

Reviewers come from `skills/reviewers/*.md` or a review-clone persona
(`clone:<alias>`). Configure via `.review-panel/config.yml`. Run with
`/review-panel [profile]`.

See `docs/superpowers/specs/2026-08-14-review-panel-design.md`.

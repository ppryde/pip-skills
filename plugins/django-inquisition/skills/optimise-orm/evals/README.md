# Evals for `django-inquisition:optimise-orm`

Two eval sets, two purposes:

## 1. `evals.json` — task-prompt eval set (skill-creator format)

12 task prompts that point at the 12 fixtures under `../tests/fixtures/`. Each entry names the fixture and what findings the skill is expected to emit. The richer machine-readable expectations live in each fixture's `expected.json`.

**Run live tests via the existing harness:**

```bash
cd plugins/django-inquisition/skills/optimise-orm
bash tests/run.sh --live
```

(Implementation of `--live` mode is wired in `tests/run.sh` — invokes `claude` headless against each fixture, parses the report frontmatter, diffs against `expected.json`.)

## 2. `trigger_eval.json` — description-optimization eval set

20 realistic user queries, 10 should-trigger and 10 should-not-trigger. Used by `skill-creator/scripts/run_loop.py` to tune the `description` field for better triggering accuracy.

**Run the optimization loop:**

Prerequisites:
- `python3.11` or newer (PEP 604 union syntax is used in the skill-creator scripts)
- `anthropic` Python package installed for the chosen interpreter
- `ANTHROPIC_API_KEY` exported in shell
- `claude` CLI on `$PATH` (used internally for triggering tests)

```bash
# Install anthropic for python3.11 if not already
python3.11 -m pip install anthropic

# Export the API key (or use direnv)
export ANTHROPIC_API_KEY=sk-ant-…

# Locate your skill-creator install. The path varies per Claude Code version
# and OS; resolve it once and reuse. On most macOS/Linux installs:
SKILL_CREATOR=$(find ~/.claude-personal -type d -name skill-creator -path '*/skills/skill-creator' 2>/dev/null | head -1)
SKILL_REPO=$(git -C "$(pwd)" rev-parse --show-toplevel)

# Run the loop (5 iterations, train/test split, opens an HTML report at the end)
cd "$SKILL_CREATOR"
python3.11 -m scripts.run_loop \
  --eval-set "$SKILL_REPO/plugins/django-inquisition/skills/optimise-orm/evals/trigger_eval.json" \
  --skill-path "$SKILL_REPO/plugins/django-inquisition/skills/optimise-orm" \
  --model claude-opus-4-7 \
  --max-iterations 5 \
  --verbose
```

The loop will:
1. Split the 20 queries 60/40 into train/test
2. Evaluate the current `description` against the train set (3 runs per query for stability)
3. Use Claude to propose an improved description based on misses
4. Re-evaluate; iterate up to 5 times
5. Open an HTML report; the JSON output names `best_description` (selected by held-out test score, not train score, to avoid overfitting)

Apply the winner by editing the `description:` line in `../SKILL.md`.

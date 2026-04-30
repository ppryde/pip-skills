# Evals for `django:optimise-orm`

Two eval sets, two purposes:

## 1. `evals.json` — task-prompt eval set (skill-creator format)

12 task prompts that point at the 12 fixtures under `../tests/fixtures/`. Each entry names the fixture and what findings the skill is expected to emit. The richer machine-readable expectations live in each fixture's `expected.json`.

**Run live tests via the existing harness:**

```bash
cd plugins/django/skills/optimise-orm
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

# Run the loop (5 iterations, train/test split, opens an HTML report at the end)
cd ~/.claude-personal/plugins/cache/claude-plugins-official/skill-creator/unknown/skills/skill-creator
python3.11 -m scripts.run_loop \
  --eval-set /Users/philip.pryde/repos/pip-skills/plugins/django/skills/optimise-orm/evals/trigger_eval.json \
  --skill-path /Users/philip.pryde/repos/pip-skills/plugins/django/skills/optimise-orm \
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

# evals/

Eval **evidence and harnesses**, kept out of the installed plugin paths so they
don't ship to `~/.claude/plugins/<name>/` when a plugin is installed from the
marketplace. This is the eval-material sibling of the `tests/` tree.

## Layout

```
evals/
  test-crucible/   # eval evidence + harness + synthetic substrate repo for the
                   # test-suite-health skill (iterations, run outputs, eval-repo-template)
```

Note: a skill's eval **definitions** (small `evals/evals.json` describing the
eval cases) legitimately live *with the skill* under
`plugins/<plugin>/skills/<skill>/evals/` — only the bulky captured evidence and
harness are relocated here.

## test-crucible

See `evals/test-crucible/` — the synthetic `ledgerlite` substrate
(`eval-repo-template/`), the iteration run outputs, and the harness scripts.
To run them:

```bash
cd evals/test-crucible
python scripts/build_eval_repo.py <dest>
```

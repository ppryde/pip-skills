# tests/

Plugin **unit/integration test suites**, relocated out of the installed plugin
paths so they don't ship to `~/.claude/plugins/<name>/` when a plugin is
installed from the marketplace.

## Layout

```
tests/
  <plugin>/        # the plugin's pytest suite (test_*.py, conftest.py, fixtures)
  run.sh           # run every suite
  README.md        # this file
```

Currently relocated: `overseer/`, `census/`, `vigil/`, `review-clone/`.

## How a suite finds its code

Each suite is still run **from its own plugin dir**, not from here. That
plugin's `pyproject.toml` sets:

```toml
[tool.pytest.ini_options]
testpaths = ["../../tests/<plugin>"]   # collect from here
pythonpath = ["."]                      # keep the plugin's scripts/ importable
```

So `cd plugins/<plugin> && pytest` collects the relocated tests while
`from scripts import ...` still resolves against the plugin's own code. The
plugins deliberately share the generic top-level package name `scripts`, so
each suite must run in its **own** pytest session — they cannot be collected
into one shared run without renaming those packages.

## Running

```bash
./tests/run.sh                 # all suites (uses ./.venv/bin/python if present)
./tests/run.sh -k some_test    # extra args forwarded to pytest
cd plugins/overseer && ../../.venv/bin/python -m pytest   # a single suite
```

## What is NOT here (and why)

- **`plugins/overseer/dashboard/`** — the dashboard is a self-contained
  sub-application. Its backend pytest suite and its frontend Vitest tests stay
  with the app; `test_dist_freshness` is intrinsically tied to the Vite build,
  and splitting them out would fragment the dashboard's test story.
- **`plugins/email-absolution/tests/`**, **`plugins/django-inquisition/skills/optimise-orm/tests/`**
  — these are not pytest suites; they are fixtures / sample apps the skills
  operate on (django's use relative `from .models` imports), so they belong
  with their skill.

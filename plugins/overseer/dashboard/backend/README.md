# overseer dashboard backend

A FastAPI app that turns the `overseer` and `vigil` CLIs into a JSON API and
serves the (separately built) dashboard frontend. It is a pure CLIENT of both
CLIs — every read and write is a `subprocess` call to their `cli.py`; it never
imports overseer/vigil internals and never touches `.workflow/` directly, which
preserves overseer's single-writer invariant.

## Install

Deps are installed ad hoc into the shared repo-root `.venv` (this subtree has
no root-level dependency of its own):

```bash
.venv/bin/pip install fastapi "uvicorn[standard]" httpx
```

## Run the tests

```bash
.venv/bin/python -m pytest plugins/overseer/dashboard/backend/tests -q
```

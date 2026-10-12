"""The vendored pip-agents validator, loaded by path.

A skill cannot reach a dependency plugin's files, so `vendor/pip-agents/` carries a byte-identical copy of
`validate_result.py` and the contract (`tools/sync_contract.py` writes it; a drift test guards it). It is loaded under
a private module name because the plugins share the generic package name `scripts`."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "pip-agents"


def _load(stem: str):
    name = f"_review_panel_vendored_{stem}"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, VENDOR / "scripts" / f"{stem}.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def validator():
    """The `validate_result` module (parse_brief, parse_result, personas, ...)."""
    return _load("validate_result")


def batching():
    """The batch planner (BATCH_CAP, plan_batches, Unit); one definition, vendored from tools/batching.py."""
    return _load("batching")

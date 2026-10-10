"""Shared fixtures for the email-absolution suite.

rules.py and migrate_doctrines.py are loaded by path under private module names: the plugins
in this repo deliberately share the generic package name `scripts`, so a package import
would collide when several suites run in one session.
"""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "email-absolution"
DOCTRINES = PLUGIN / "doctrines"
SCRIPTS = PLUGIN / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def R():
    return _load("email_rules", SCRIPTS / "rules.py")


@pytest.fixture(scope="session")
def docs(R):
    d, problems = R.load(DOCTRINES)
    assert not problems, problems
    return d


@pytest.fixture(scope="session")
def rules(R, docs):
    return R.all_rules(docs)


@pytest.fixture(scope="session")
def by_id(rules):
    return {r.id: r for r in rules}


@pytest.fixture()
def doctrine_copy(tmp_path):
    """A writable copy of the real doctrines (never the real tree)."""
    dest = tmp_path / "doctrines"
    shutil.copytree(DOCTRINES, dest)
    return dest


@pytest.fixture(scope="session")
def migrate(R):
    # migrate_doctrines does `import rules`; make it resolve to the module already loaded.
    sys.modules["rules"] = R
    try:
        return _load("email_migrate", SCRIPTS / "migrate_doctrines.py")
    finally:
        sys.modules.pop("rules", None)

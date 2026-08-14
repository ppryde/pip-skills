import textwrap
from pathlib import Path

import pytest

from scripts.config import (
    ConfigError, ReviewerRef, ResolvedReview,
    load_config, parse_reviewer_key, resolve_profile, resolve_adhoc,
)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(textwrap.dedent(text))
    return p


def test_parse_builtin_reviewer_key():
    ref = parse_reviewer_key("general", "strict")
    assert ref == ReviewerRef("general", "builtin", "general", "strict")


def test_parse_clone_reviewer_key():
    ref = parse_reviewer_key("clone:danvk", "pragmatic")
    assert ref == ReviewerRef("clone:danvk", "clone", "danvk", "pragmatic")


def test_parse_clone_reviewer_key_empty_alias_raises():
    with pytest.raises(ConfigError, match="alias"):
        parse_reviewer_key("clone:", "strict")


def test_resolve_profile_merges_defaults_and_strictness(tmp_path):
    cfg = load_config(_write(tmp_path, """
        defaults: { strategy: committee, scope: changed }
        profiles:
          pre-merge:
            strategy: adversarial
            reviewers: { general: strict, "clone:danvk": pragmatic }
    """))
    r = resolve_profile(cfg, "pre-merge")
    assert r.strategy == "adversarial"
    assert r.scope == "changed"
    assert set(r.reviewers) == {
        ReviewerRef("general", "builtin", "general", "strict"),
        ReviewerRef("clone:danvk", "clone", "danvk", "pragmatic"),
    }


def test_resolve_profile_uses_default_profile_when_none(tmp_path):
    cfg = load_config(_write(tmp_path, """
        defaults: { strategy: committee, scope: changed, profile: quick }
        profiles:
          quick: { reviewers: { general: pragmatic } }
    """))
    r = resolve_profile(cfg, None)
    assert r.reviewers == (ReviewerRef("general", "builtin", "general", "pragmatic"),)


def test_resolve_profile_unknown_raises(tmp_path):
    cfg = load_config(_write(tmp_path, "profiles: { a: { reviewers: { general: strict } } }"))
    with pytest.raises(ConfigError, match="unknown profile"):
        resolve_profile(cfg, "nope")


def test_resolve_profile_bad_strictness_raises(tmp_path):
    cfg = load_config(_write(tmp_path, "profiles: { a: { reviewers: { general: harsh } } }"))
    with pytest.raises(ConfigError, match="strictness"):
        resolve_profile(cfg, "a")


def test_resolve_adhoc_defaults_to_committee_changed(tmp_path):
    cfg = load_config(_write(tmp_path, "defaults: {}"))
    r = resolve_adhoc(cfg, ["general", "clone:danvk"])
    assert r.strategy == "committee" and r.scope == "changed"
    assert r.output == "report"
    assert [x.name for x in r.reviewers] == ["general", "danvk"]


def test_load_config_missing_returns_empty(tmp_path):
    assert load_config(tmp_path / "absent.yml") == {}


def test_load_config_malformed_raises(tmp_path):
    bad = tmp_path / "config.yml"
    bad.write_text("profiles: [unbalanced")
    with pytest.raises(ConfigError):
        load_config(bad)


def test_load_config_non_mapping_root_raises(tmp_path):
    bad = tmp_path / "config.yml"
    bad.write_text("- a\n- b")
    with pytest.raises(ConfigError):
        load_config(bad)

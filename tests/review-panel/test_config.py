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
    assert r.output_file == ".review-panel/last-review.md"
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


_PROFILE = {"profiles": {"p": {"reviewers": {"general": "strict"}}}}


def _cfg(**spec):
    return {"profiles": {"p": {"reviewers": {"general": "strict"}, **spec}}}


@pytest.mark.parametrize("bad", ["/etc/x", "~/x", "../x", "a/../../x"])
def test_output_file_rejects_escaping_paths(bad):
    cfg = {**_PROFILE, "output": {"file": bad}}
    with pytest.raises(ConfigError):
        resolve_profile(cfg, "p")
    with pytest.raises(ConfigError):
        resolve_adhoc(cfg, ["general"])


def test_output_file_default_accepted():
    assert resolve_profile(_PROFILE, "p").output_file == ".review-panel/last-review.md"


def test_context_entries_reject_escaping_paths():
    with pytest.raises(ConfigError):
        resolve_profile(_cfg(context=["/etc/passwd"]), "p")
    with pytest.raises(ConfigError):
        resolve_profile(_cfg(context=["../secret.md"]), "p")
    assert resolve_profile(_cfg(context=["docs/spec.md"]), "p").context == ("docs/spec.md",)


@pytest.mark.parametrize("key", ["../x", "a/b", "clone:../x", "clone:a/b", "-x", ".hidden"])
def test_reviewer_key_rejects_hostile_names(key):
    with pytest.raises(ConfigError):
        parse_reviewer_key(key, "strict")


def test_reviewer_key_accepts_normal_names():
    assert parse_reviewer_key("clone:dan.vk-2", "strict").name == "dan.vk-2"
    assert parse_reviewer_key("my_rev", "strict").name == "my_rev"


def test_targets_string_is_one_item_not_characters():
    assert resolve_profile(_cfg(targets="src/**"), "p").targets == ("src/**",)


def test_targets_non_list_rejected():
    with pytest.raises(ConfigError):
        resolve_profile(_cfg(targets={"a": 1}), "p")


def test_profile_not_a_mapping_rejected():
    with pytest.raises(ConfigError):
        resolve_profile({"profiles": {"p": ["general"]}}, "p")


def test_none_strictness_rejected_clearly():
    with pytest.raises(ConfigError, match="strictness"):
        resolve_profile({"profiles": {"p": {"reviewers": {"general": None}}}}, "p")


def test_trailing_newline_names_rejected():
    with pytest.raises(ConfigError):
        parse_reviewer_key("general\n", "strict")
    with pytest.raises(ConfigError):
        parse_reviewer_key("clone:dan\n", "strict")


def test_null_output_file_uses_default():
    cfg = {**_PROFILE, "output": {"file": None}}
    assert resolve_profile(cfg, "p").output_file == ".review-panel/last-review.md"
    assert resolve_adhoc(cfg, ["general"]).output_file == ".review-panel/last-review.md"


def test_context_rejects_tilde():
    with pytest.raises(ConfigError):
        resolve_profile(_cfg(context=["~/notes.md"]), "p")

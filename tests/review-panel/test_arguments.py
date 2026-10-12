"""RP-11: one token space, one precedence; overrides are parameters."""
import pytest

from scripts.arguments import Request, parse_arguments
from scripts.config import ConfigError, resolve_adhoc, resolve_profile

CFG = {"profiles": {"pre-merge": {"reviewers": {"general": "pragmatic"}},
                    "general": {"reviewers": {"general": "strict"}}},
       "defaults": {"profile": "pre-merge"}}
REV = ["general"]


def P(*t, cfg=CFG):
    return parse_arguments(list(t), cfg, REV)


def test_empty_is_default_profile():
    assert P() == Request()


def test_profile_with_modifiers():
    assert P("pre-merge", "full", "inline") == Request(profile="pre-merge", scope="full", output="inline")
    assert P("full") == Request(scope="full")


def test_listing_words():
    assert P("reviewers").list == "reviewers"
    assert P("strategies").list == "strategies"
    with pytest.raises(ConfigError):
        P("reviewers", "full")


def test_profile_name_beats_reviewer_key():
    assert P("general").profile == "general"


def test_reviewer_keys_adhoc_and_clone():
    cfg = {"profiles": {"pre-merge": {}}}
    assert P("general", "clone:jen", cfg=cfg) == Request(reviewers=("general", "clone:jen"))
    # a profile that shares a reviewer's name wins, so mixing it is refused
    with pytest.raises(ConfigError, match="not both"):
        P("general", "clone:jen")


def test_profile_and_reviewer_do_not_mix():
    with pytest.raises(ConfigError, match="not both"):
        P("pre-merge", "clone:jen")


def test_unknown_lists_valid_values():
    with pytest.raises(ConfigError) as e:
        P("nope")
    msg = str(e.value)
    assert "pre-merge" in msg and "general" in msg and "clone:<alias>" in msg and "inline" in msg


def test_reserved_word_shadows_a_profile_of_that_name():
    cfg = {"profiles": {"full": {"reviewers": {"general": "strict"}}}}
    assert P("full", cfg=cfg) == Request(scope="full")


def test_both_outputs_refused():
    with pytest.raises(ConfigError):
        P("inline", "interactive")


@pytest.mark.parametrize("tok", ["$(id)", "a;b", "a b", "-x", "`x`", "../x", "x" * 80, "", "a'b"])
def test_tokens_are_validated_before_use(tok):
    with pytest.raises(ConfigError):
        P(tok)


def test_missing_profiles_key_or_junk_is_tolerated():
    assert P("general", cfg={}) == Request(reviewers=("general",))
    assert P("general", cfg={"profiles": ["x"]}) == Request(reviewers=("general",))


def test_overrides_are_parameters_not_replace():
    r = resolve_profile(CFG, "pre-merge", scope="full", output="inline")
    assert (r.scope, r.output) == ("full", "inline")
    r = resolve_profile(CFG, "pre-merge")
    assert (r.scope, r.output) == ("changed", "report")
    r = resolve_adhoc({}, ["general"], scope="full", output="interactive")
    assert (r.scope, r.output, r.reviewers[0].strictness) == ("full", "interactive", "pragmatic")
    with pytest.raises(ConfigError):
        resolve_profile(CFG, "pre-merge", scope="everything")
    with pytest.raises(ConfigError):
        resolve_adhoc({}, ["general"], output="slack")

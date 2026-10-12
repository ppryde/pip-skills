from scripts import modes


def test_default_is_shadow() -> None:
    assert modes.get_mode("s", "repo") == "shadow"


def test_session_flag_beats_repo_default() -> None:
    modes.set_mode("inject", None, "repo")
    assert modes.get_mode("s", "repo") == "inject"
    modes.set_mode("shadow", "s", "repo")
    assert modes.get_mode("s", "repo") == "shadow"
    assert modes.get_mode("other", "repo") == "inject"

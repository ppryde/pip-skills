"""Install questions as AskUserQuestion cards: shape limits and flag round-trips."""
from __future__ import annotations

import pytest
from context_vigil import cards, cli


def _all_cards(mods: bool) -> list:
    data = cards.install_cards(mods)
    return [data["card1"], *data["followups"].values(), cards.last_light_card()]


@pytest.mark.parametrize("mods", [True, False])
def test_cards_respect_ask_user_question_limits(mods: bool) -> None:
    for card in _all_cards(mods):
        assert 1 <= len(card["questions"]) <= 4
        for q in card["questions"]:
            assert len(q["header"]) <= 12
            assert q["question"].endswith("?")
            assert 2 <= len(q["options"]) <= 4
            assert q["options"][0]["label"].endswith("(Recommended)")
            assert q["multiSelect"] is False


def test_bar_question_only_with_mods() -> None:
    headers = lambda m: [q["header"] for q in cards.install_cards(m)["card1"]["questions"]]
    assert "🎛️ Vigil bar" in headers(True)
    assert "🎛️ Vigil bar" not in headers(False)


def test_every_option_maps_to_a_valid_install_flag() -> None:
    data = cards.install_cards(True)
    parser = cli.build_parser()
    for card in [data["card1"], data["followups"]["last_light_threshold"]]:
        for q in card["questions"]:
            for opt in q["options"]:
                flag = data["flags"][opt["label"]]
                parser.parse_args(["install", *flag.split()])   # raises SystemExit if invalid

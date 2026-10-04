"""User-facing strings and the one JSON emitter the Stop path uses."""
from __future__ import annotations

import json

import pytest
from context_vigil import messages


def test_system_message_is_one_json_object_with_only_system_message() -> None:
    out = messages.system_message('say "hand over" \\ now\n🕯️')
    data = json.loads(out)
    assert list(data) == ["systemMessage"]
    assert data["systemMessage"] == 'say "hand over" \\ now\n🕯️'


def test_system_message_caps_length() -> None:
    data = json.loads(messages.system_message("x" * 5000))
    assert len(data["systemMessage"]) == messages.MAX_LEN


@pytest.mark.parametrize("template", [messages.NOTICE_FIRST, messages.NOTICE_REPEAT])
def test_notices_format_ints_and_fit(template: str) -> None:
    text = template.format(pct=41, threshold=35)
    assert "41%" in text and len(text) <= messages.MAX_LEN
    assert "{" not in text


def test_strings_lead_with_emoji() -> None:
    for text in (messages.NOTICE_FIRST, messages.SAVED_TYPE_CLEAR,
                 messages.SAVED_DIALOG_OPEN, messages.LAST_LIGHT_PREPARED):
        assert not text[0].isascii()

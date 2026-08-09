"""Concurrent session behaviour, group a."""

import pytest

from ledgerlite.session import Session


@pytest.fixture
def setup_session():
    def _make(user):
        session = Session(user)
        assert session.open
        return session

    return _make


@pytest.fixture
def two_sessions(setup_session):
    first = setup_session("alice")
    second = setup_session("bob")
    yield first, second
    first.close()
    second.close()


@pytest.fixture
def race_ids(two_sessions):
    first, second = two_sessions
    return sorted((first.id, second.id))


def test_sessions_get_distinct_ids_a(two_sessions):
    first, second = two_sessions
    assert first.id != second.id


def test_race_ids_are_ordered_a(race_ids):
    assert race_ids == sorted(race_ids)


def test_closing_one_leaves_the_other_open_a(two_sessions):
    first, second = two_sessions
    first.close()
    assert not first.open
    assert second.open

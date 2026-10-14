from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app, make_require_token


def test_make_require_token_inert_when_none():
    dep = make_require_token(None)
    assert dep(None) is None            # no token in effect -> allow
    assert dep("anything") is None


def test_make_require_token_rejects_wrong_token():
    import pytest
    from fastapi import HTTPException

    dep = make_require_token("secret")
    assert dep("secret") is None        # correct -> allow
    with pytest.raises(HTTPException) as ei:
        dep("wrong")
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException):
        dep(None)


def test_mount_frontend_false_has_no_catch_all(root: Path):
    app = create_app(root, mount_frontend=False)
    client = TestClient(app)
    # /api/board still works...
    assert client.get("/api/board").status_code == 200
    # ...but an unknown non-API path is a real 404, not the SPA placeholder/dist.
    assert client.get("/definitely-not-a-route").status_code == 404


def test_mount_frontend_true_still_serves_catch_all(root: Path):
    app = create_app(root, mount_frontend=True, dist_dir=Path("/nonexistent-dist"))
    client = TestClient(app)
    # dist absent -> placeholder catch-all answers 200 (unchanged behaviour).
    assert client.get("/some-spa-path").status_code == 200


def test_make_require_exec_token_fails_closed_when_no_token():
    """No token configured must mean REFUSE EVERYONE, not allow everyone.

    This is the inverse of make_require_token's inert mode. /api/exec runs
    arbitrary overseer verbs on the host; if this ever returns None for an
    unconfigured token, every create_app() in the suite becomes unauthenticated
    remote code execution.
    """
    import pytest
    from fastapi import HTTPException

    from app.main import make_require_exec_token

    for unset in (None, ""):
        dep = make_require_exec_token(unset)
        for supplied in (None, "", "anything"):
            with pytest.raises(HTTPException) as ei:
                dep(supplied)
            assert ei.value.status_code == 503
    dep = make_require_exec_token(None)
    for supplied in (None, "", "anything"):
        with pytest.raises(HTTPException) as ei:
            dep(supplied)
        assert ei.value.status_code == 503


def test_make_require_exec_token_rejects_missing_or_wrong_token():
    import pytest
    from fastapi import HTTPException

    from app.main import make_require_exec_token

    dep = make_require_exec_token("secret")
    for supplied in (None, "", "wrong"):
        with pytest.raises(HTTPException) as ei:
            dep(supplied)
        assert ei.value.status_code == 401


def test_make_require_exec_token_allows_matching_token():
    from app.main import make_require_exec_token

    dep = make_require_exec_token("secret")
    assert dep("secret") is None


def test_make_require_exec_token_non_ascii_header_is_401_not_500():
    """hmac.compare_digest on str raises TypeError for non-ASCII; that must be a 401."""
    import pytest
    from fastapi import HTTPException

    from app.main import make_require_exec_token

    dep = make_require_exec_token("secret")
    with pytest.raises(HTTPException) as ei:
        dep("s\u00e9cret")
    assert ei.value.status_code == 401


def test_make_require_token_none_is_still_inert():
    from app.main import make_require_token

    assert make_require_token(None)() is None

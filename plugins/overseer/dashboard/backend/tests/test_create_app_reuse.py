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

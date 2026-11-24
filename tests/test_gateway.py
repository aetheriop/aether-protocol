import io
import json
from contextlib import closing
from urllib.error import URLError

import pytest

from gateway.api import MAX_REQUEST, completion_provider, create_app
from gateway.auth import connect, issue_key, lookup_key, revoke_key
from gateway.meter import Tariff, charge_for_usage, record_usage

MODEL = "test-model"
PAYLOAD = {"model": MODEL, "messages": [{"role": "user", "content": "A test task"}]}
USAGE = {"prompt_tokens": 500, "completion_tokens": 250}


def invoke(app, token, payload=PAYLOAD, *, method="POST", path="/v1/chat/completions", length=None):
    captured = []
    raw = json.dumps(payload).encode()
    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(length if length is not None else len(raw)),
        "wsgi.input": io.BytesIO(raw),
        "HTTP_AUTHORIZATION": "Bearer " + token,
    }
    body = b"".join(app(env, lambda *response: captured.extend(response)))
    return int(captured[0].split()[0]), dict(captured[1]), json.loads(body)


@pytest.fixture
def gateway(tmp_path):
    calls = []
    path = tmp_path / "gateway.sqlite"

    def provider(payload):
        calls.append(payload)
        return {"model": MODEL, "choices": [{"message": {"content": "A test result"}}], "usage": USAGE}

    app = create_app(path, {MODEL: Tariff(1_000_000, 2_000_000)}, provider)
    with closing(connect(path)) as db, db:
        key_id, token = issue_key(db)
    return path, app, key_id, token, calls


def test_auth_uses_digest_and_recognizes_revocation(gateway):
    path, _, key_id, token, _ = gateway
    with closing(connect(path)) as db, db:
        assert db.execute("SELECT length(digest) FROM client_keys").fetchone()[0] == 32
        assert lookup_key(db, "Bearer " + token) == key_id
        assert revoke_key(db, key_id)
        assert not revoke_key(db, key_id)
        assert lookup_key(db, "Bearer " + token) is None


def test_metered_completion(gateway):
    path, app, key_id, token, calls = gateway
    code, headers, result = invoke(app, token)
    assert code == 200 and calls == [PAYLOAD] and result["usage"] == USAGE
    with closing(connect(path)) as db:
        assert db.execute("""
            SELECT key_id, input_tokens, output_tokens, charge_micros
            FROM usage_entries WHERE request_id = ?
        """, (headers["X-Request-ID"],)).fetchone() == (key_id, 500, 250, 1000)


def test_invalid_auth_never_calls_provider(gateway):
    _, app, _, _, calls = gateway
    code, headers, _ = invoke(app, "invalid")
    assert code == 401 and headers["WWW-Authenticate"] == "Bearer"
    assert calls == []


def test_revoked_key_never_calls_provider(gateway):
    path, app, key_id, token, calls = gateway
    with closing(connect(path)) as db, db:
        revoke_key(db, key_id)
    assert invoke(app, token)[0] == 401
    assert calls == []


@pytest.mark.parametrize("payload", [
    {"model": "unlisted", "messages": PAYLOAD["messages"]},
    {"model": MODEL, "messages": []},
    {"model": MODEL, "messages": ["invalid"]},
    {**PAYLOAD, "stream": True},
    {**PAYLOAD, "stream": "false"},
])
def test_bad_requests_are_not_forwarded(gateway, payload):
    _, app, _, token, calls = gateway
    assert invoke(app, token, payload)[0] == 400
    assert calls == []


@pytest.mark.parametrize("kwargs,status", [
    ({"method": "GET"}, 405),
    ({"path": "/v1/other"}, 404),
    ({"length": MAX_REQUEST + 1}, 413),
    ({"length": 0}, 400),
])
def test_http_validation(gateway, kwargs, status):
    _, app, _, token, calls = gateway
    assert invoke(app, token, **kwargs)[0] == status
    assert calls == []


def test_missing_usage_is_not_charged(gateway):
    path, _, _, token, _ = gateway
    app = create_app(path, {MODEL: Tariff(1, 1)}, lambda _: {"choices": []})
    assert invoke(app, token)[0] == 502
    with closing(connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM usage_entries").fetchone()[0] == 0


def test_provider_error_is_generic(gateway):
    path, _, _, token, _ = gateway

    def failed(_):
        raise URLError("private upstream detail")

    app = create_app(path, {MODEL: Tariff(1, 1)}, failed)
    code, _, result = invoke(app, token)
    assert code == 502
    assert "private upstream detail" not in str(result)


@pytest.mark.parametrize("url", [
    "http://example.test/v1",
    "https://user:password@example.test/v1",
    "https://example.test/v1?extra=1",
])
def test_provider_requires_a_fixed_https_endpoint(url):
    with pytest.raises(ValueError):
        completion_provider(url, "test")


@pytest.mark.parametrize("usage", [
    None, {}, {"prompt_tokens": -1, "completion_tokens": 1},
    {"prompt_tokens": True, "completion_tokens": 1},
])
def test_invalid_usage_cannot_be_charged(usage):
    with pytest.raises(ValueError):
        charge_for_usage(usage, Tariff(1, 1))


def test_fractional_microdollar_is_rounded_up():
    assert charge_for_usage({"prompt_tokens": 1, "completion_tokens": 0}, Tariff(1, 0))[2] == 1


def test_metering_retry_is_idempotent(gateway):
    path, _, key_id, _, _ = gateway
    with closing(connect(path)) as db:
        for _ in range(2):
            assert record_usage(db, "retry", key_id, MODEL, USAGE, Tariff(1, 1)) == 1
        assert db.execute("SELECT COUNT(*) FROM usage_entries").fetchone()[0] == 1
        with pytest.raises(ValueError):
            record_usage(db, "retry", key_id, MODEL, USAGE, Tariff(1_000_000, 1_000_000))

"""Small WSGI gateway for the non-streaming OpenAI chat completion format."""

import json
import os
import sqlite3
import uuid
from contextlib import closing
from http import HTTPStatus
from http.client import HTTPException
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from wsgiref.simple_server import make_server

from gateway.auth import connect, init_keys, lookup_key
from gateway.meter import Tariff, init_meter, record_usage

MAX_REQUEST = 1_000_000
MAX_RESPONSE = 4_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, message, headers, newurl):
        return None


def completion_provider(base_url, provider_key, timeout=30):
    url = urlsplit(base_url)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("Provider base URL must be a fixed HTTPS endpoint")
    endpoint = base_url.rstrip("/") + "/chat/completions"
    client = build_opener(NoRedirect())

    def complete(payload):
        request = Request(endpoint, data=json.dumps(payload).encode(), headers={
            "Authorization": "Bearer " + provider_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        with client.open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError("Upstream response is too large")
        return json.loads(body)

    return complete


def read_payload(environ, tariffs):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError as error:
        raise ValueError("Invalid request length") from error
    if length > MAX_REQUEST:
        raise OverflowError("Request is too large")
    if length <= 0:
        raise ValueError("Request body is required")
    data = json.loads(environ["wsgi.input"].read(length))
    if not isinstance(data, dict) or not isinstance(data.get("model"), str) or data["model"] not in tariffs:
        raise ValueError("Select an available model")
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages or any(
        not isinstance(message, dict) or not isinstance(message.get("role"), str) for message in messages
    ):
        raise ValueError("A nonempty messages list is required")
    if data.get("stream", False) is not False:
        raise ValueError("This gateway supports non-streaming requests")
    return data


def create_app(database, tariffs, complete):
    tariffs = dict(tariffs)
    with closing(connect(database)) as db:
        init_keys(db)
        init_meter(db)

    def app(environ, start_response):
        def respond(status, body, more_headers=()):
            data = json.dumps(body).encode()
            headers = [("Content-Type", "application/json"), ("Content-Length", str(len(data))),
                       ("Cache-Control", "no-store"), *more_headers]
            start_response(f"{status} {HTTPStatus(status).phrase}", headers)
            return [data]

        def error(status, message, headers=()):
            return respond(status, {"error": {"message": message}}, headers)

        if environ.get("PATH_INFO") != "/v1/chat/completions":
            return error(404, "Unknown endpoint")
        if environ.get("REQUEST_METHOD") != "POST":
            return error(405, "Use POST", (("Allow", "POST"),))

        try:
            with closing(connect(database)) as db:
                key_id = lookup_key(db, environ.get("HTTP_AUTHORIZATION", ""))
                if key_id is None:
                    return error(401, "Invalid API credential", (("WWW-Authenticate", "Bearer"),))
                try:
                    payload = read_payload(environ, tariffs)
                except OverflowError:
                    return error(413, "Request is too large")
                except (ValueError, UnicodeError):
                    return error(400, "Invalid model, message list or streaming option")
                try:
                    result = complete(payload)
                    if not isinstance(result, dict) or not isinstance(result.get("choices"), list):
                        raise ValueError("Invalid upstream completion")
                    request_id = uuid.uuid4().hex
                    record_usage(db, request_id, key_id, payload["model"], result.get("usage"), tariffs[payload["model"]])
                except (OSError, HTTPException, ValueError):
                    return error(502, "The provider did not return a metered completion")
                return respond(200, result, (("X-Request-ID", request_id),))
        except sqlite3.Error:
            return error(503, "Usage storage is temporarily unavailable")

    return app


def main():
    os.umask(0o077)
    rate_config = json.loads(os.environ["AETHER_MODEL_TARIFFS"])
    tariffs = {model: Tariff(*rates) for model, rates in rate_config.items()}
    provider = completion_provider(os.environ["AETHER_PROVIDER_URL"], os.environ["AETHER_PROVIDER_KEY"])
    app = create_app(os.environ.get("AETHER_GATEWAY_DB", "gateway.sqlite"), tariffs, provider)
    with make_server("127.0.0.1", 8080, app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()

"""HTTP-level API tests: routing, validation, and status-code mapping."""

import pytest

pytest.importorskip("httpx")  # TestClient needs httpx (see requirements-dev.txt)

from fastapi.testclient import TestClient  # noqa: E402

import app.main as api  # noqa: E402
from query_service import SQLQualityError  # noqa: E402
from sql_generator import DEFAULT_MODEL, ModelNotFoundError, ModelUnavailableError  # noqa: E402

client = TestClient(api.app)


def _raise(exc):
    def fail(*args, **kwargs):
        raise exc

    return fail


def test_health_over_http():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_page_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "QueryPilot" in response.text


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "x" * 2001}])
def test_invalid_request_bodies_are_rejected_by_validation(body):
    assert client.post("/api/query", json=body).status_code == 422


def test_successful_query_returns_service_payload(monkeypatch):
    payload = {"sql": "SELECT 1 AS a", "columns": ["a"], "rows": [[1]], "truncated": False}
    monkeypatch.setattr(api.service, "ask", lambda question, model: payload)

    response = client.post("/api/query", json={"question": "One?"})

    assert response.status_code == 200
    assert response.json()["rows"] == [[1]]


def test_model_outside_the_allow_list_is_rejected(monkeypatch):
    monkeypatch.delenv("QUERYPILOT_ALLOWED_MODELS", raising=False)
    monkeypatch.setattr(api.service, "ask", _raise(AssertionError("must not be called")))

    response = client.post("/api/query", json={"question": "Hi", "model": "other:70b"})

    assert response.status_code == 400


def test_allow_list_can_be_extended_by_environment(monkeypatch):
    monkeypatch.setenv("QUERYPILOT_ALLOWED_MODELS", f"{DEFAULT_MODEL},other:7b")
    monkeypatch.setattr(api.service, "ask", lambda question, model: {"model": model})

    response = client.post("/api/query", json={"question": "Hi", "model": "other:7b"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "exception, status",
    [
        (ModelNotFoundError("not installed"), 503),
        (ModelUnavailableError("ollama down"), 503),
        (SQLQualityError(["bad ordering"]), 422),
        (ValueError("Only SELECT or WITH queries are allowed."), 400),
        (RuntimeError("Ollama returned an unexpected response format."), 502),
        (KeyError("boom"), 500),
    ],
)
def test_service_errors_map_to_the_right_status(monkeypatch, exception, status):
    monkeypatch.setattr(api.service, "ask", _raise(exception))

    response = client.post("/api/query", json={"question": "Anything"})

    assert response.status_code == status


def test_sqlite_errors_do_not_leak_internal_details(monkeypatch):
    import sqlite3

    monkeypatch.setattr(api.service, "ask", _raise(sqlite3.OperationalError("no such column: secret_col")))

    response = client.post("/api/query", json={"question": "Anything"})

    assert response.status_code == 422
    assert "secret_col" not in response.text


def test_unexpected_errors_do_not_leak_internal_details(monkeypatch):
    monkeypatch.setattr(api.service, "ask", _raise(KeyError("internal_detail")))

    response = client.post("/api/query", json={"question": "Anything"})

    assert response.status_code == 500
    assert "internal_detail" not in response.text

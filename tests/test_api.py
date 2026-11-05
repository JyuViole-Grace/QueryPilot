import pytest
from fastapi import HTTPException

import app.main as api


def test_health_endpoint():
    assert api.health() == {"status": "ok"}


def test_query_endpoint_returns_service_result(monkeypatch):
    monkeypatch.setattr(api.service, "ask", lambda question, model: {
        "sql": "SELECT 1 AS answer",
        "columns": ["answer"],
        "rows": [[1]],
        "truncated": False,
        "execution_time_seconds": 0.001,
        "context_used": True,
    })
    response = api.query(api.QueryRequest(question="How many?"))
    assert response["rows"] == [[1]]


def test_query_endpoint_turns_service_validation_error_into_http_error(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("Empty question")

    monkeypatch.setattr(api.service, "ask", fail)
    with pytest.raises(HTTPException) as error:
        api.query(api.QueryRequest(question="Test"))

    assert error.value.status_code == 400

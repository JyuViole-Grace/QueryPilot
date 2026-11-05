import io
import json
from urllib.error import HTTPError, URLError

import pytest

import sql_generator as generator
from sql_generator import ModelNotFoundError, extract_sql, generate_sql


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def reply(text: str) -> FakeResponse:
    return FakeResponse(json.dumps({"message": {"content": text}}).encode("utf-8"))


def with_urlopen(fake):
    original = generator.urlopen
    generator.urlopen = fake
    return original


def test_extract_sql_accepts_plain_fenced_and_commented_queries():
    assert extract_sql("SELECT 1") == "SELECT 1"
    assert extract_sql("  SELECT 1  ") == "SELECT 1"
    assert extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert extract_sql("```\nWITH a AS (SELECT 1) SELECT * FROM a\n```").startswith("WITH")
    assert extract_sql("-- comment\nSELECT 1").startswith("-- comment")


def test_extract_sql_rejects_empty_and_non_select_answers():
    for bad in ["", "   ", "```sql\n```", "DROP TABLE customers",
                "Here is the query: SELECT 1", "12345", "-- only a comment"]:
        with pytest.raises(ValueError):
            extract_sql(bad)


def test_generate_sql_sends_a_deterministic_request_with_the_schema():
    seen = {}

    def fake(request, timeout):
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return reply("```sql\nSELECT COUNT(*) FROM customers\n```")

    original = with_urlopen(fake)

    try:
        sql = generate_sql("How many customers?", model="demo-model")
    finally:
        generator.urlopen = original

    payload = seen["payload"]
    assert sql == "SELECT COUNT(*) FROM customers"
    assert payload["model"] == "demo-model"
    assert payload["options"]["temperature"] == 0
    assert "CREATE TABLE" in payload["messages"][1]["content"]  # schema was included
    assert "How many customers?" in payload["messages"][1]["content"]
    assert "Repair previous SQL" not in payload["messages"][1]["content"]


def test_generate_sql_includes_feedback_only_when_correcting():
    seen = {}

    def fake(request, timeout):
        seen["prompt"] = json.loads(request.data.decode("utf-8"))["messages"][1]["content"]
        return reply("SELECT 1")

    original = with_urlopen(fake)

    try:
        generate_sql("Question", previous_sql="SELECT bad", error_feedback="FEEDBACK_MARKER", attempt=1)
    finally:
        generator.urlopen = original

    assert "Repair previous SQL" in seen["prompt"]
    assert "SELECT bad" in seen["prompt"]
    assert "FEEDBACK_MARKER" in seen["prompt"]


def test_generate_sql_validates_arguments_before_any_network_call():
    def fail(request, timeout):
        raise AssertionError("network must not be touched")

    original = with_urlopen(fail)

    try:
        for kwargs in [{"question": "  "}, {"question": "q", "model": " "}, {"question": "q", "attempt": -1}]:
            with pytest.raises(ValueError):
                generate_sql(**kwargs)
    finally:
        generator.urlopen = original


def test_missing_model_raises_a_dedicated_error_with_the_pull_command():
    def fake(request, timeout):
        raise HTTPError("http://x", 404, "Not Found", {}, io.BytesIO(b'{"error":"model not found"}'))

    original = with_urlopen(fake)

    try:
        with pytest.raises(ModelNotFoundError) as error:
            generate_sql("Question", model="qwen2.5:14b")
    finally:
        generator.urlopen = original

    assert "ollama pull qwen2.5:14b" in str(error.value)
    assert isinstance(error.value, RuntimeError)


def test_other_http_errors_connection_errors_and_bad_replies_become_runtime_errors():
    cases = {
        "http500": lambda r, timeout: (_ for _ in ()).throw(HTTPError("http://x", 500, "Err", {}, io.BytesIO(b"boom"))),
        "offline": lambda r, timeout: (_ for _ in ()).throw(URLError("refused")),
        "not_json": lambda r, timeout: FakeResponse(b"<html>"),
        "wrong_shape": lambda r, timeout: FakeResponse(b'{"unexpected": 1}'),
    }

    for name, fake in cases.items():
        original = with_urlopen(fake)

        try:
            with pytest.raises(RuntimeError) as error:
                generate_sql("Question")
        finally:
            generator.urlopen = original

        assert not isinstance(error.value, ModelNotFoundError), name


def test_connection_failures_and_timeouts_are_reported_as_unavailable():
    from sql_generator import ModelUnavailableError

    cases = {
        "offline": lambda r, timeout: (_ for _ in ()).throw(URLError("refused")),
        "timeout": lambda r, timeout: (_ for _ in ()).throw(TimeoutError("timed out")),
    }

    for name, fake in cases.items():
        original = with_urlopen(fake)

        try:
            with pytest.raises(ModelUnavailableError):
                generate_sql("Question")
        finally:
            generator.urlopen = original

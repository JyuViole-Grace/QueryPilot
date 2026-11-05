
from query_service import QueryService, SQLQualityError


def make_execution_result():
    return {
        "columns": ["total"],
        "rows": [(1,)],
        "truncated": False,
        "execution_time_seconds": 0.01,
    }


def test_service_returns_serializable_query_result():
    events = []

    def generator(question: str, **kwargs) -> str:
        assert question == "How many customers?"
        assert "context" in kwargs
        return "SELECT 1 AS total"

    def executor(sql: str) -> dict:
        assert sql == "SELECT 1 AS total"
        return make_execution_result()

    service = QueryService(
        generator=generator,
        executor=executor,
        event_writer=events.append,
    )

    result = service.ask("  How many customers?  ")

    assert result["rows"] == [[1]]
    assert result["columns"] == ["total"]
    assert events[0]["success"] is True
    assert "question" not in events[0]


def test_service_logs_failure_without_the_question_contents():
    events = []

    def generator(*args, **kwargs):
        raise RuntimeError("Ollama unavailable")

    service = QueryService(
        generator=generator,
        event_writer=events.append,
    )

    try:
        service.ask("secret question")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected generator error")

    assert events[0]["success"] is False
    assert "secret question" not in str(events[0])


def test_service_rejects_wrong_price_sorting_before_execution():
    events = []
    executor_calls = []

    def generator(question: str, **kwargs) -> str:
        return (
            "SELECT product_id, name, price_cents "
            "FROM products "
            "WHERE is_active = 1 "
            "ORDER BY price_cents DESC "
            "LIMIT 10"
        )

    def executor(sql: str) -> dict:
        executor_calls.append(sql)
        return make_execution_result()

    service = QueryService(
        generator=generator,
        executor=executor,
        event_writer=events.append,
    )

    try:
        service.ask("Show the 10 cheapest active products.")
    except SQLQualityError as exc:
        assert any("ascending" in issue for issue in exc.issues)
    else:
        raise AssertionError("Expected SQL quality validation to fail")

    assert executor_calls == []
    assert events[0]["success"] is False


def test_service_rejects_wrong_limit_before_execution():
    events = []
    executor_calls = []

    def generator(question: str, **kwargs) -> str:
        return (
            "SELECT product_id, name, price_cents "
            "FROM products "
            "WHERE is_active = 1 "
            "ORDER BY price_cents ASC "
            "LIMIT 5"
        )

    def executor(sql: str) -> dict:
        executor_calls.append(sql)
        return make_execution_result()

    service = QueryService(
        generator=generator,
        executor=executor,
        event_writer=events.append,
    )

    try:
        service.ask("Show the 10 cheapest active products.")
    except SQLQualityError as exc:
        assert any("LIMIT 10" in issue for issue in exc.issues)
    else:
        raise AssertionError("Expected SQL quality validation to fail")

    assert executor_calls == []
    assert events[0]["success"] is False


def test_service_executes_sql_when_quality_checks_pass():
    events = []
    executor_calls = []

    expected_sql = (
        "SELECT product_id, name, price_cents "
        "FROM products "
        "WHERE is_active = 1 "
        "ORDER BY price_cents ASC, product_id ASC "
        "LIMIT 10"
    )

    def generator(question: str, **kwargs) -> str:
        return expected_sql

    def executor(sql: str) -> dict:
        executor_calls.append(sql)
        return {
            "columns": ["product_id", "name", "price_cents"],
            "rows": [(1, "Keyboard", 2500)],
            "truncated": False,
            "execution_time_seconds": 0.02,
        }

    service = QueryService(
        generator=generator,
        executor=executor,
        event_writer=events.append,
    )

    result = service.ask("Show the 10 cheapest active products.")

    assert executor_calls == [expected_sql]
    assert result["columns"] == ["product_id", "name", "price_cents"]
    assert result["rows"] == [[1, "Keyboard", 2500]]
    assert result["quality_repair_attempts"] == 0
    assert events[0]["success"] is True
    assert events[0]["quality_repair_attempts"] == 0


def test_service_repairs_sql_quality_issue_before_execution():
    events = []
    generator_calls = []
    executor_calls = []

    invalid_sql = (
        "SELECT product_id, name, price_cents "
        "FROM products "
        "WHERE is_active = 1 "
        "ORDER BY price_cents DESC "
        "LIMIT 10"
    )

    corrected_sql = (
        "SELECT product_id, name, price_cents "
        "FROM products "
        "WHERE is_active = 1 "
        "ORDER BY price_cents ASC, product_id ASC "
        "LIMIT 10"
    )

    def generator(question: str, **kwargs) -> str:
        generator_calls.append(kwargs.copy())

        if kwargs.get("previous_sql"):
            assert kwargs.get("error_feedback")
            assert kwargs.get("attempt") == 1
            return corrected_sql

        return invalid_sql

    def executor(sql: str) -> dict:
        executor_calls.append(sql)
        return {
            "columns": ["product_id", "name", "price_cents"],
            "rows": [(1, "Keyboard", 2500)],
            "truncated": False,
            "execution_time_seconds": 0.02,
        }

    service = QueryService(
        generator=generator,
        executor=executor,
        event_writer=events.append,
    )

    result = service.ask("Show the 10 cheapest active products.")

    assert len(generator_calls) == 2
    assert generator_calls[0].get("previous_sql") is None
    assert generator_calls[1]["previous_sql"] == invalid_sql
    assert generator_calls[1]["error_feedback"]
    assert generator_calls[1]["attempt"] == 1

    assert executor_calls == [corrected_sql]
    assert result["sql"] == corrected_sql
    assert result["quality_repair_attempts"] == 1
    assert result["rows"] == [[1, "Keyboard", 2500]]

    assert events[0]["success"] is True
    assert events[0]["quality_repair_attempts"] == 1


def test_service_stops_after_maximum_repair_attempts():
    events = []
    generator_calls = []
    executor_calls = []

    invalid_sql = (
        "SELECT product_id, name, price_cents "
        "FROM products "
        "WHERE is_active = 1 "
        "ORDER BY price_cents DESC "
        "LIMIT 10"
    )

    def generator(question: str, **kwargs) -> str:
        generator_calls.append(kwargs.copy())
        # The generator deliberately returns invalid sorting every time.
        return invalid_sql

    def executor(sql: str) -> dict:
        executor_calls.append(sql)
        return make_execution_result()

    service = QueryService(
        generator=generator,
        executor=executor,
        event_writer=events.append,
        max_repair_attempts=2,
    )

    try:
        service.ask("Show the 10 cheapest active products.")
    except SQLQualityError as exc:
        assert any("ascending" in issue for issue in exc.issues)
    else:
        raise AssertionError("Expected SQLQualityError after repair attempts")

    # One initial generation plus two repair attempts.
    assert len(generator_calls) == 3
    assert generator_calls[0].get("previous_sql") is None
    assert generator_calls[1]["previous_sql"] == invalid_sql
    assert generator_calls[1]["attempt"] == 1
    assert generator_calls[2]["previous_sql"] == invalid_sql
    assert generator_calls[2]["attempt"] == 2

    # Invalid SQL must never reach the executor.
    assert executor_calls == []

    # Failure and the number of repair attempts must be logged.
    assert events[0]["success"] is False
    assert events[0]["quality_repair_attempts"] == 2
    assert "SQLQualityError" in events[0]["error"]

def test_service_repairs_unrequested_shipment_status_filter():
    events = []
    generator_calls = []
    executor_calls = []

    question = (
        "Which carriers shipped returned orders? "
        "Show each carrier name only once."
    )

    invalid_sql = """
        SELECT DISTINCT s.carrier
        FROM shipments s
        JOIN orders o ON s.order_id = o.order_id
        WHERE o.status = 'returned'
          AND s.status IN ('shipped', 'in_transit', 'delivered')
    """

    corrected_sql = """
        SELECT DISTINCT s.carrier
        FROM shipments s
        JOIN orders o ON s.order_id = o.order_id
        WHERE o.status = 'returned'
        ORDER BY s.carrier
    """

    def generator(question: str, **kwargs) -> str:
        generator_calls.append(kwargs.copy())

        if kwargs.get("previous_sql"):
            assert kwargs.get("error_feedback")
            assert "shipment status" in kwargs["error_feedback"].lower()
            return corrected_sql

        return invalid_sql

    def executor(sql: str) -> dict:
        executor_calls.append(sql)
        return {
            "columns": ["carrier"],
            "rows": [("Meest",), ("Nova Post",), ("Ukrposhta",)],
            "truncated": False,
            "execution_time_seconds": 0.01,
        }

    service = QueryService(
        generator=generator,
        executor=executor,
        event_writer=events.append,
    )

    result = service.ask(question)

    assert len(generator_calls) == 2
    assert generator_calls[1]["previous_sql"] == invalid_sql
    assert executor_calls == [corrected_sql]
    assert result["quality_repair_attempts"] == 1
    assert result["rows"] == [
        ["Meest"],
        ["Nova Post"],
        ["Ukrposhta"],
    ]
    assert events[0]["success"] is True
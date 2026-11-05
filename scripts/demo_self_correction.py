
"""Test SQL self-correction using the real local Ollama model."""

from query_service import QueryService, SQLQualityError
from sql_generator import DEFAULT_MODEL, generate_sql
from sql_safety import execute_read_only


QUESTION = "Show the 10 cheapest active products."

# Deliberately incorrect: DESC returns the most expensive products first.
INVALID_SQL = """
SELECT product_id, name, price_cents
FROM products
WHERE is_active = 1
ORDER BY price_cents DESC
LIMIT 10
"""


def initial_generator(question: str, **kwargs) -> str:
    """Return intentionally invalid SQL for the first generation."""
    print("\n[TEST] Supplying intentionally incorrect SQL.")
    return INVALID_SQL


def main() -> None:
    service = QueryService(
        generator=initial_generator,
        repairer=generate_sql,
        executor=execute_read_only,
        max_repair_attempts=2,
    )

    print(f"Model: {DEFAULT_MODEL}")
    print(f"Question: {QUESTION}")
    print("\nRunning self-correction test...")

    try:
        result = service.ask(QUESTION, model=DEFAULT_MODEL)

    except SQLQualityError as exc:
        print("\n[FAIL] The model did not fix the SQL quality issues.")
        for issue in exc.issues:
            print(f" - {issue}")
        raise SystemExit(1)

    except Exception as exc:
        print(f"\n[ERROR] {type(exc).__name__}: {exc}")
        raise SystemExit(1)

    print("\n[RESULT] Final SQL:")
    print(result["sql"])

    print("\n[RESULT] Rows returned:")
    for row in result["rows"]:
        print(row)

    print(
        "\nRepair attempts:",
        result["quality_repair_attempts"],
    )

    if result["quality_repair_attempts"] < 1:
        print(
            "\n[FAIL] No repair was performed; "
            "the test did not exercise self-correction."
        )
        raise SystemExit(1)

    print("\n[PASS] The real model corrected the SQL quality issue.")


if __name__ == "__main__":
    main()

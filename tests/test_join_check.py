import json
from pathlib import Path

import pytest

from join_check import find_invalid_join_keys, foreign_keys, join_key_hints

TESTS_DIR = Path(__file__).resolve().parent
DATASETS = (
    "golden_questions.json",
    "heldout_questions.json",
    "heldout_v3_questions.json",
    "heldout_v4_questions.json",
)


def test_foreign_keys_are_read_from_the_schema():
    keys = foreign_keys()

    assert ("orders", "customer_id", "customers", "customer_id") in keys
    assert ("order_items", "order_id", "orders", "order_id") in keys
    assert "orders.customer_id = customers.customer_id" in join_key_hints()


@pytest.mark.parametrize("sql", [
    # Real mistakes made by qwen2.5:7b on heldout_v3 (v3_10 and v3_28).
    "WITH d AS (SELECT customer_id FROM orders) SELECT 1 FROM d JOIN order_items i ON d.customer_id = i.order_id",
    "SELECT 1 FROM categories c LEFT JOIN active_products a ON c.category_id = a.product_id",
    "SELECT 1 FROM orders o JOIN products p ON o.order_id = p.product_id",
])
def test_equating_different_key_columns_is_flagged(sql):
    issues = find_invalid_join_keys(sql)

    assert len(issues) == 1
    assert "foreign-key" in issues[0]


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM orders o JOIN customers c ON o.customer_id = c.customer_id",
    "SELECT 1 FROM order_items oi JOIN orders o ON oi.order_id = o.order_id",
    "SELECT 1 FROM orders o WHERE o.total_cents = o.discount_cents",        # not key columns
    "SELECT 1 FROM orders o WHERE o.status = 'a.customer_id = b.order_id'",  # inside a string
    "SELECT 1 FROM orders o -- o.customer_id = o.order_id\nWHERE 1 = 1",     # inside a comment
    "SELECT 1 FROM orders o WHERE o.customer_id = 5",                        # literal, not a column
])
def test_valid_or_irrelevant_equalities_are_not_flagged(sql):
    assert find_invalid_join_keys(sql) == []


def test_same_issue_is_reported_once():
    sql = "SELECT 1 FROM a JOIN b ON a.customer_id = b.order_id AND a.customer_id = b.order_id"
    assert len(find_invalid_join_keys(sql)) == 1


def test_missing_schema_disables_the_check(tmp_path: Path):
    missing = str(tmp_path / "nope.sql")
    assert find_invalid_join_keys("SELECT 1 FROM a JOIN b ON a.customer_id = b.order_id", missing) == []


@pytest.mark.parametrize("dataset", DATASETS)
def test_no_reference_sql_is_flagged(dataset):
    """Regression guard against false positives on known-correct queries."""
    data = json.loads((TESTS_DIR / dataset).read_text(encoding="utf-8"))
    tests = data["tests"] if isinstance(data, dict) else data

    flagged = [t["id"] for t in tests if find_invalid_join_keys(t["reference_sql"])]

    assert flagged == []

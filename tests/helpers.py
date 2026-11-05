"""Shared test helpers: a small database and a reference test case."""

import sqlite3
import tempfile
from pathlib import Path

from sql_safety import execute_read_only


def make_db() -> Path:
    """Create a small SQLite database in a temporary directory."""
    path = Path(tempfile.mkdtemp(prefix="qp_test_")) / "test.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        INSERT INTO customers VALUES
            (1, 'Anna', 'Lviv'), (2, 'Boris', 'Kyiv'), (3, 'Clara', 'Lviv');
        """
    )
    connection.commit()
    connection.close()

    return path


def count_customers(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    finally:
        connection.close()


def executor_for(path: Path):
    return lambda sql: execute_read_only(sql, database_path=path)


def make_test(**overrides) -> dict:
    """A golden_questions.json test asking for customer counts by city."""
    test = {
        "id": "t1",
        "category": "aggregation",
        "question": "How many customers live in each city?",
        "reference_sql": "SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city",
        "expected_columns": ["city", "customer_count"],
        "expected_result": [
            {"city": "Lviv", "customer_count": 2},
            {"city": "Kyiv", "customer_count": 1},
        ],
        "order_sensitive": False,
    }
    test.update(overrides)

    return test


GOOD_SQL = "SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city"
GOOD_SQL_OTHER_ALIAS = "SELECT city, COUNT(*) AS n FROM customers GROUP BY city"
WRONG_SQL = "SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city HAVING COUNT(*) > 5"
BROKEN_SQL = "SELECT missing_column FROM customers"

import sqlite3
import time

import pytest

from helpers import count_customers, make_db
from sql_safety import ALLOWED_ACTIONS, execute_read_only, is_read_query

FORBIDDEN_STATEMENTS = [
    "DELETE FROM customers",
    "UPDATE customers SET city = 'X'",
    "INSERT INTO customers VALUES (9, 'Eve', 'Odesa')",
    "DROP TABLE customers",
    "CREATE TABLE evil (id INTEGER)",
    "ALTER TABLE customers ADD COLUMN age INTEGER",
    "ATTACH DATABASE 'other.db' AS other",
    "PRAGMA table_info(customers)",
    "VACUUM",
    "REPLACE INTO customers VALUES (1, 'X', 'Y')",
]


def test_select_with_and_recursive_queries_are_allowed():
    path = make_db()

    result = execute_read_only("SELECT city, COUNT(*) FROM customers GROUP BY city", database_path=path)
    assert sorted(result["rows"]) == [("Kyiv", 1), ("Lviv", 2)]
    assert result["columns"] == ["city", "COUNT(*)"]

    cte = execute_read_only(
        "WITH big AS (SELECT * FROM customers WHERE city = 'Lviv') SELECT COUNT(*) FROM big",
        database_path=path,
    )
    assert cte["rows"] == [(2,)]

    recursive = execute_read_only(
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 5) SELECT SUM(x) FROM c",
        database_path=path,
    )
    assert recursive["rows"] == [(15,)]


def test_every_destructive_statement_is_rejected_and_data_is_untouched():
    path = make_db()
    before = count_customers(path)

    for statement in FORBIDDEN_STATEMENTS:
        with pytest.raises((ValueError, sqlite3.Error)):
            execute_read_only(statement, database_path=path)

    assert count_customers(path) == before


def test_write_hidden_behind_with_is_stopped_by_the_database_layers():
    """is_read_query allows WITH, so the authorizer and read-only mode are tested here."""
    path = make_db()
    sql = "WITH x AS (SELECT 1) DELETE FROM customers"

    assert is_read_query(sql) is True

    with pytest.raises(sqlite3.Error):
        execute_read_only(sql, database_path=path)

    assert count_customers(path) == 3


def test_multiple_statements_are_not_executed():
    path = make_db()

    with pytest.raises(sqlite3.Error):
        execute_read_only("SELECT 1; DELETE FROM customers", database_path=path)

    assert count_customers(path) == 3


def test_authorizer_is_an_allow_list():
    assert sqlite3.SQLITE_SELECT in ALLOWED_ACTIONS
    assert sqlite3.SQLITE_READ in ALLOWED_ACTIONS

    for action in (sqlite3.SQLITE_DELETE, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE,
                   sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_PRAGMA,
                   sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_ALTER_TABLE):
        assert action not in ALLOWED_ACTIONS


def test_is_read_query_edge_cases():
    assert is_read_query("select 1")
    assert is_read_query("  \n WITH a AS (SELECT 1) SELECT * FROM a")
    assert is_read_query("-- note\nSELECT 1")
    assert is_read_query("/* note */ SELECT 1")

    assert not is_read_query("")
    assert not is_read_query("   ")
    assert not is_read_query("DROP TABLE customers")
    assert not is_read_query("/* hide */ DROP TABLE customers")
    assert not is_read_query("-- only a comment")
    assert not is_read_query("/* never closed SELECT 1")


def test_result_is_truncated_at_the_row_limit():
    path = make_db()
    sql = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 50) SELECT x FROM c"

    result = execute_read_only(sql, database_path=path, max_rows=10)

    assert len(result["rows"]) == 10
    assert result["truncated"] is True

    small = execute_read_only("SELECT 1", database_path=path, max_rows=10)
    assert small["truncated"] is False


def test_runaway_query_is_interrupted_by_the_timeout():
    path = make_db()
    infinite = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"
    started = time.monotonic()

    with pytest.raises(sqlite3.OperationalError):
        execute_read_only(infinite, database_path=path, timeout_seconds=0.3)

    assert time.monotonic() - started < 5


def test_huge_strings_are_refused():
    with pytest.raises(sqlite3.Error):
        execute_read_only("SELECT hex(zeroblob(5000000))", database_path=make_db())

    with pytest.raises(sqlite3.Error):
        execute_read_only(
            "WITH RECURSIVE s(v) AS (SELECT 'xxxxxxxxxx' UNION ALL "
            "SELECT v || v FROM s WHERE length(v) < 5000000) "
            "SELECT length(v) FROM s ORDER BY 1 DESC LIMIT 1",
            database_path=make_db(),
        )


@pytest.mark.parametrize("function", ["randomblob(10)", "zeroblob(10)"])
def test_memory_bomb_functions_are_denied(function):
    with pytest.raises(sqlite3.Error):
        execute_read_only(f"SELECT {function}", database_path=make_db())


@pytest.mark.parametrize("table", ["sqlite_master", "sqlite_schema", "sqlite_sequence"])
def test_internal_sqlite_tables_cannot_be_read(table):
    with pytest.raises(sqlite3.Error):
        execute_read_only(f"SELECT * FROM {table}", database_path=make_db())


def test_ordinary_queries_still_work_with_the_stricter_authorizer():
    result = execute_read_only(
        "SELECT COUNT(*) AS n, upper('ok') AS word FROM customers",
        database_path=make_db(),
    )
    assert result["columns"] == ["n", "word"]


def test_missing_database_is_a_configuration_error():
    path = make_db().parent / "does_not_exist.db"

    with pytest.raises(FileNotFoundError):
        execute_read_only("SELECT 1", database_path=path)

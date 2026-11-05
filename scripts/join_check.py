"""Schema-derived check for impossible join conditions.

Every foreign key in ``sql/schema.sql`` joins two columns with the *same*
name (``orders.customer_id = customers.customer_id``). A model-written
condition that equates two different key columns, such as
``d.customer_id = i.order_id`` or ``c.category_id = a.product_id``, can never
be a valid relationship in this schema and silently returns wrong rows.

The check is deliberately small and dependency-free: it looks only at
qualified equalities ``alias.column = alias.column`` where both columns look
like keys (``id`` or ``*_id``). It does not resolve aliases, so it works the
same inside CTEs and subqueries. It cannot detect every wrong join (for
example a valid key pair joined through the wrong table), so it is a guard,
not a proof.
"""

from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"

_EQUALITY = re.compile(
    r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b"
)
_STRING = re.compile(r"'(?:[^']|'')*'")
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


@lru_cache(maxsize=4)
def foreign_keys(schema_path: str = str(SCHEMA_PATH)) -> tuple[tuple[str, str, str, str], ...]:
    """Return (child_table, child_column, parent_table, parent_column) tuples.

    The schema is loaded into an in-memory SQLite database, so SQLite itself
    parses the FOREIGN KEY clauses. A missing or unreadable schema yields ().
    """
    try:
        script = Path(schema_path).read_text(encoding="utf-8")
        connection = sqlite3.connect(":memory:")
    except (OSError, sqlite3.Error):
        return ()

    try:
        connection.executescript(script)
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        result = []

        for table in tables:
            for row in connection.execute(f'PRAGMA foreign_key_list("{table}")'):
                # row: id, seq, parent_table, from_column, to_column, ...
                result.append((table, row[3], row[2], row[4]))

        return tuple(result)
    except sqlite3.Error:
        return ()
    finally:
        connection.close()


def _is_key_column(name: str) -> bool:
    lowered = name.casefold()
    return lowered == "id" or lowered.endswith("_id")


def _allowed_pairs(schema_path: str) -> frozenset[frozenset[str]]:
    return frozenset(
        frozenset({child_col.casefold(), parent_col.casefold()})
        for _, child_col, _, parent_col in foreign_keys(schema_path)
    )


def join_key_hints(schema_path: str = str(SCHEMA_PATH)) -> list[str]:
    """Human-readable valid join conditions, e.g. ``orders.customer_id = customers.customer_id``."""
    return [
        f"{child}.{child_col} = {parent}.{parent_col}"
        for child, child_col, parent, parent_col in foreign_keys(schema_path)
    ]


def find_invalid_join_keys(sql: str, schema_path: str = str(SCHEMA_PATH)) -> list[str]:
    """Return one issue per equality that compares two different key columns."""
    allowed = _allowed_pairs(schema_path)

    if not allowed:  # no schema available: do not guess
        return []

    cleaned = _BLOCK_COMMENT.sub(" ", sql)
    cleaned = _LINE_COMMENT.sub(" ", cleaned)
    cleaned = _STRING.sub("''", cleaned)

    issues: list[str] = []
    seen: set[str] = set()

    for left_alias, left_col, right_alias, right_col in _EQUALITY.findall(cleaned):
        if not (_is_key_column(left_col) and _is_key_column(right_col)):
            continue

        if left_col.casefold() == right_col.casefold():
            continue

        if frozenset({left_col.casefold(), right_col.casefold()}) in allowed:
            continue

        condition = f"{left_alias}.{left_col} = {right_alias}.{right_col}"

        if condition in seen:
            continue

        seen.add(condition)
        issues.append(
            f"The join condition {condition} compares different key columns "
            "and is not a foreign-key relationship in this schema. "
            "Join only on matching foreign keys, for example "
            "orders.customer_id = customers.customer_id or "
            "order_items.order_id = orders.order_id."
        )

    return issues

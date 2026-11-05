"""Build small, relevant context for text-to-SQL generation.

The full schema remains the source of truth.  This module adds a compact
retrieval layer: it identifies likely tables from an English question and
supplies safe value hints from the local database.  It never executes model
SQL and is deliberately heuristic, so it can be used without embeddings.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from join_check import join_key_hints
from sql_safety import DATABASE_PATH

# Bump when the grounding text changes: reports record it, because changing
# the context changes results even when the system prompt is unchanged.
#   1 - relevant tables + known values
#   2 - adds the list of valid join conditions
CONTEXT_VERSION = 2

JOIN_HINTS_ENV = "QUERYPILOT_JOIN_HINTS"


def join_hints_enabled() -> bool:
    """Join-condition grounding is on unless QUERYPILOT_JOIN_HINTS is 0/false/off/no.

    The switch exists for ablation runs: the effect of the hints on accuracy
    is measured by running with and without them.
    """
    return os.getenv(JOIN_HINTS_ENV, "1").strip().lower() not in {"0", "false", "off", "no"}


def context_version() -> int:
    """Grounding version actually used now (1 when join hints are disabled)."""
    return CONTEXT_VERSION if join_hints_enabled() else 1


TABLE_HINTS: dict[str, tuple[str, ...]] = {
    "customers": ("customer", "buyer", "client", "city", "registered"),
    "products": ("product", "item", "price", "stock", "inventory"),
    "categories": ("category",),
    "suppliers": ("supplier", "manufacturer", "country"),
    "orders": ("order", "discount"),
    "order_items": ("item", "unit", "quantity", "sold", "sales"),
    "payments": ("payment", "paid"),
    "shipments": ("shipment", "delivery", "shipping", "carrier"),
    "reviews": ("review", "rating"),
    "coupons": ("coupon", "promo"),
}


def relevant_tables(question: str,) -> list[str]:
    """Return likely table names, in deterministic relevance order."""
    normalized = question.lower()

    ranked = []

    for table, hints in TABLE_HINTS.items():
        score = 0

        for hint in hints:
            variants = [hint]

            if hint.endswith("y"):
                variants.append(hint[:-1] + "ies")
            else:
                variants.extend((hint + "s", hint + "es"))

            pattern = (
                rf"(?<![a-z])(?:{'|'.join(re.escape(v) for v in variants)})"
                rf"(?![a-z])"
            )

            score += len(re.findall(pattern, normalized))

        ranked.append((score, table))

    matches = [table for score, table in ranked if score > 0]
    return matches


def _distinct_values(connection: sqlite3.Connection, table: str, column: str) -> list[str]:
    rows = connection.execute(
        f"SELECT DISTINCT {column} FROM {table} "
        f"WHERE {column} IS NOT NULL ORDER BY {column} LIMIT 20"
    ).fetchall()
    return [str(row[0]) for row in rows]


def build_context(question: str, database_path: Path | str = DATABASE_PATH) -> str:
    """Return compact schema/value grounding text for a user question.

    A missing database is non-fatal: generation still receives the schema and
    simply proceeds without value hints.
    """
    tables = relevant_tables(question)
    lines = []
    if tables:
        lines.append("Likely relevant tables: " + ", ".join(tables) + ".")

    hints = join_key_hints() if join_hints_enabled() else []
    if hints:
        lines.append(
            "Valid join conditions (use only these; never equate different "
            "key columns such as customer_id = order_id): "
            + "; ".join(hints) + "."
        )

    path = Path(database_path)
    if not path.exists():
        return "\n".join(lines)

    value_sources = (
        ("orders", "status", "order statuses"),
        ("payments", "status", "payment statuses"),
        ("shipments", "status", "shipment statuses"),
        ("customers", "city", "customer cities"),
        ("suppliers", "country", "supplier countries"),
    )
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            for table, column, label in value_sources:
                if table in tables or re.search(
                        r"status|city|delivery|shipment|payment|country|countries|"
                        r"poland|germany|taiwan|ukraine|czechia",
                        question,
                        re.I,
                ):
                    try:
                        values = _distinct_values(connection, table, column)
                    except sqlite3.Error:
                        # Test/minimal databases may not contain every domain table.
                        continue
                    if values:
                        lines.append(f"Known {label}: " + ", ".join(values) + ".")
        finally:
            connection.close()
    except sqlite3.Error:
        # Context is an optional quality improvement, never a new failure mode.
        pass

    return "\n".join(lines)

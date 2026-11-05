"""Build the held-out benchmark question set.

Rules that keep this benchmark independent:

1. Questions and reference queries are written before running the model on them.
2. The prompt is not tuned on these questions. This dataset is for evaluation only.
3. The reference is unambiguous: when row order is meaningful, the sort key
   is unique, including at the top-N boundary (rows N and N+1 differ).
4. Empty results and excessively large result sets are excluded.

Run: python scripts/build_heldout_dataset.py
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from evaluate_sql import prompt_fingerprint
from scoring import order_required

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "database" / "querypilot.db"
OUTPUT_PATH = PROJECT_ROOT / "tests" / "heldout_questions.json"

MAX_EXPECTED_ROWS = 60

# order_key is needed only when row order is part of the question:
# the output columns used for sorting.
TEST_CASES: list[dict[str, Any]] = [
    # ---------------- filtering ----------------
    {
        "category": "filtering",
        "question": "Which products are currently inactive? Show the ID, name, and price, sorted by product ID in ascending order.",
        "reference_sql": """
            SELECT product_id, name, price_cents
            FROM products
            WHERE is_active = 0
            ORDER BY product_id
        """,
        "order_key": ["product_id"],
    },
    {
        "category": "filtering",
        "question": "Which customers from the city stored as «Odesa» registered after July 1, 2024? Show their IDs and names.",
        "reference_sql": """
            SELECT customer_id, full_name
            FROM customers
            WHERE city = 'Odesa' AND registered_at > '2024-07-01'
            ORDER BY customer_id
        """,
    },
    {
        "category": "filtering",
        "question": "How many payments over 1,000 UAH failed?",
        "reference_sql": """
            SELECT COUNT(*) AS failed_payment_count
            FROM payments
            WHERE status = 'failed' AND amount_cents > 100000
        """,
    },
    # ---------------- aggregation ----------------
    {
        "category": "aggregation",
        "question": "What is the average product price in each category? Show the category name and average price in kopecks, rounded to the nearest integer.",
        "reference_sql": """
            SELECT c.name, ROUND(AVG(p.price_cents)) AS average_price_cents
            FROM categories AS c
            JOIN products AS p ON p.category_id = c.category_id
            GROUP BY c.category_id, c.name
            ORDER BY c.name
        """,
    },
    {
        "category": "aggregation",
        "question": "How many units of stock are there in each category? Show the category name and total quantity.",
        "reference_sql": """
            SELECT c.name, SUM(p.stock_quantity) AS total_stock
            FROM categories AS c
            JOIN products AS p ON p.category_id = c.category_id
            GROUP BY c.category_id, c.name
            ORDER BY c.name
        """,
    },
    {
        "category": "aggregation",
        "question": "What is the total order discount for each coupon? Show the coupon code and discount total in kopecks, only for coupons that were used.",
        "reference_sql": """
            SELECT cp.code, SUM(o.discount_cents) AS total_discount_cents
            FROM coupons AS cp
            JOIN orders AS o ON o.coupon_id = cp.coupon_id
            GROUP BY cp.coupon_id, cp.code
            ORDER BY cp.code
        """,
    },
    {
        "category": "aggregation",
        "question": "How many product units were sold in delivered orders?",
        "reference_sql": """
            SELECT SUM(oi.quantity) AS units_sold
            FROM order_items AS oi
            JOIN orders AS o ON o.order_id = oi.order_id
            WHERE o.status = 'delivered'
        """,
    },
    {
        "category": "aggregation",
        "question": "What is the average number of product line items per order? Round to two decimal places.",
        "reference_sql": """
            SELECT ROUND(AVG(item_count), 2) AS average_items_per_order
            FROM (
                SELECT COUNT(*) AS item_count
                FROM order_items
                GROUP BY order_id
            )
        """,
    },
    {
        "category": "aggregation",
        "question": "What are the minimum, maximum, and average prices of active products? Round the average to the nearest integer. Show all three values in kopecks.",
        "reference_sql": """
            SELECT
                MIN(price_cents) AS min_price_cents,
                MAX(price_cents) AS max_price_cents,
                ROUND(AVG(price_cents)) AS average_price_cents
            FROM products
            WHERE is_active = 1
        """,
    },
    {
        "category": "aggregation",
        "question": "How many distinct products received at least one review with a rating of 1 or 2?",
        "reference_sql": """
            SELECT COUNT(DISTINCT product_id) AS product_count
            FROM reviews
            WHERE rating <= 2
        """,
    },
    {
        "category": "aggregation",
        "question": "What is the total value of all order line items (quantity × line-item price) across all orders? Return a single number in kopecks.",
        "reference_sql": """
            SELECT SUM(quantity * unit_price_cents) AS total_cents
            FROM order_items
        """,
    },
    {
        "category": "aggregation",
        "question": "How many customers have submitted at least one review?",
        "reference_sql": """
            SELECT COUNT(DISTINCT customer_id) AS reviewer_count
            FROM reviews
        """,
    },
    # ---------------- joins ----------------
    {
        "category": "joins",
        "question": "Show the product ID, product name, and supplier name for suppliers from Poland. Sort by product ID.",
        "reference_sql": """
            SELECT p.product_id, p.name AS product_name, s.name AS supplier_name
            FROM products AS p
            JOIN suppliers AS s ON s.supplier_id = p.supplier_id
            WHERE s.country = 'Poland'
            ORDER BY p.product_id
        """,
        "order_key": ["product_id"],
    },
    {
        "category": "joins",
        "question": "Show the order ID, customer name, and city for every returned order.",
        "reference_sql": """
            SELECT o.order_id, c.full_name, c.city
            FROM orders AS o
            JOIN customers AS c ON c.customer_id = o.customer_id
            WHERE o.status = 'returned'
            ORDER BY o.order_id
        """,
    },
    {
        "category": "joins",
        "question": "How many orders has each customer from the city stored as «Kyiv» placed, including customers with no orders? Show the name and count.",
        "reference_sql": """
            SELECT c.full_name, COUNT(o.order_id) AS order_count
            FROM customers AS c
            LEFT JOIN orders AS o ON o.customer_id = c.customer_id
            WHERE c.city = 'Kyiv'
            GROUP BY c.customer_id, c.full_name
            ORDER BY c.customer_id
        """,
    },
    {
        "category": "joins",
        "question": "Which carriers shipped returned orders? Show each carrier name only once.",
        "reference_sql": """
            SELECT DISTINCT s.carrier
            FROM shipments AS s
            JOIN orders AS o ON o.order_id = s.order_id
            WHERE o.status = 'returned'
            ORDER BY s.carrier
        """,
    },
    {
        "category": "joins",
        "question": "Show the five most recent deliveries: order ID, carrier, and delivery date.",
        "reference_sql": """
            SELECT order_id, carrier, delivered_at
            FROM shipments
            WHERE delivered_at IS NOT NULL
            ORDER BY delivered_at DESC, shipment_id DESC
            LIMIT 5
        """,
        "order_key": ["delivered_at"],
    },
    # ---------------- subqueries ----------------
    {
        "category": "subqueries",
        "question": "Which products cost more than the average price of all products? Show the ID, name, and price.",
        "reference_sql": """
            SELECT product_id, name, price_cents
            FROM products
            WHERE price_cents > (SELECT AVG(price_cents) FROM products)
            ORDER BY product_id
        """,
    },
    {
        "category": "subqueries",
        "question": "How many customers have not submitted any reviews?",
        "reference_sql": """
            SELECT COUNT(*) AS customer_count
            FROM customers AS c
            WHERE NOT EXISTS (
                SELECT 1 FROM reviews AS r WHERE r.customer_id = c.customer_id
            )
        """,
    },
    {
        "category": "subqueries",
        "question": "How many orders contain at least one product from the category named «Laptops?",
        "reference_sql": """
            SELECT COUNT(*) AS order_count
            FROM orders AS o
            WHERE EXISTS (
                SELECT 1
                FROM order_items AS oi
                JOIN products AS p ON p.product_id = oi.product_id
                JOIN categories AS c ON c.category_id = p.category_id
                WHERE oi.order_id = o.order_id AND c.name = 'Laptops'
            )
        """,
    },
    {
        "category": "subqueries",
        "question": "How many customers have at least one cancelled order but no delivered orders?",
        "reference_sql": """
            SELECT COUNT(*) AS customer_count
            FROM customers AS c
            WHERE EXISTS (
                SELECT 1 FROM orders AS o
                WHERE o.customer_id = c.customer_id AND o.status = 'cancelled'
            )
            AND NOT EXISTS (
                SELECT 1 FROM orders AS o
                WHERE o.customer_id = c.customer_id AND o.status = 'delivered'
            )
        """,
    },
    # ---------------- sorting ----------------
    {
        "category": "sorting",
        "question": "Show the five cheapest active products: ID, name, and price.",
        "reference_sql": """
            SELECT product_id, name, price_cents
            FROM products
            WHERE is_active = 1
            ORDER BY price_cents, product_id
            LIMIT 5
        """,
        "order_key": ["price_cents"],
    },
    {
        "category": "sorting",
        "question": "Show the five orders with the highest total line-item value (quantity × line-item price): order ID and total.",
        "reference_sql": """
            SELECT order_id, SUM(quantity * unit_price_cents) AS items_total_cents
            FROM order_items
            GROUP BY order_id
            ORDER BY items_total_cents DESC, order_id
            LIMIT 5
        """,
        "order_key": ["items_total_cents"],
    },
    {
        "category": "sorting",
        "question": "Show the five most expensive successful payments: payment ID, order ID, and amount.",
        "reference_sql": """
            SELECT payment_id, order_id, amount_cents
            FROM payments
            WHERE status = 'successful'
            ORDER BY amount_cents DESC, payment_id
            LIMIT 5
        """,
        "order_key": ["amount_cents"],
    },
    # ---------------- multi_table_aggregation ----------------
    {
        "category": "multi_table_aggregation",
        "question": "How many product units were purchased by customers in each city in delivered orders? Show the city and quantity.",
        "reference_sql": """
            SELECT c.city, SUM(oi.quantity) AS units_sold
            FROM customers AS c
            JOIN orders AS o ON o.customer_id = c.customer_id
            JOIN order_items AS oi ON oi.order_id = o.order_id
            WHERE o.status = 'delivered'
            GROUP BY c.city
            ORDER BY c.city
        """,
    },
    {
        "category": "multi_table_aggregation",
        "question": "What is the average rating of products from each supplier? Show the supplier name and rating, rounded to two decimal places.",
        "reference_sql": """
            SELECT s.name, ROUND(AVG(r.rating), 2) AS average_rating
            FROM suppliers AS s
            JOIN products AS p ON p.supplier_id = s.supplier_id
            JOIN reviews AS r ON r.product_id = p.product_id
            GROUP BY s.supplier_id, s.name
            ORDER BY s.name
        """,
    },
    {
        "category": "multi_table_aggregation",
        "question": "How many distinct customers purchased products from each category in delivered orders? Show the category name and customer count.",
        "reference_sql": """
            SELECT c.name, COUNT(DISTINCT o.customer_id) AS buyer_count
            FROM categories AS c
            JOIN products AS p ON p.category_id = c.category_id
            JOIN order_items AS oi ON oi.product_id = p.product_id
            JOIN orders AS o ON o.order_id = oi.order_id
            WHERE o.status = 'delivered'
            GROUP BY c.category_id, c.name
            ORDER BY c.name
        """,
    },
    # ---------------- date_filtering ----------------
    {
        "category": "date_filtering",
        "question": "How many orders were placed in the first quarter of 2026?",
        "reference_sql": """
            SELECT COUNT(*) AS order_count
            FROM orders
            WHERE ordered_at >= '2026-01-01' AND ordered_at < '2026-04-01'
        """,
    },
    {
        "category": "date_filtering",
        "question": "Which payments were successfully processed in June 2025? Show the payment ID, order ID, and amount.",
        "reference_sql": """
            SELECT payment_id, order_id, amount_cents
            FROM payments
            WHERE status = 'successful'
              AND paid_at >= '2025-06-01' AND paid_at < '2025-07-01'
            ORDER BY payment_id
        """,
    },
    # ---------------- date_aggregation ----------------
    {
        "category": "date_aggregation",
        "question": "How many orders were placed in each month of 2025? Show the month in YYYY-MM format and the count.",
        "reference_sql": """
            SELECT strftime('%Y-%m', ordered_at) AS month, COUNT(*) AS order_count
            FROM orders
            WHERE ordered_at >= '2025-01-01' AND ordered_at < '2026-01-01'
            GROUP BY month
            ORDER BY month
        """,
    },
]


def execute_reference_query(
        connection: sqlite3.Connection,
        sql: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    cursor = connection.execute(sql)
    columns = [column[0] for column in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return columns, rows


def check_order_is_unambiguous(
        connection: sqlite3.Connection,
        test: dict[str, Any],
) -> list[str]:
    """Check that row order is determined by the question, not an arbitrary tie-breaker.

    For top-N questions, inspect row N+1: sort keys for all these rows must
    differ; otherwise, the selected N rows may be arbitrary.
    """
    if not order_required(test):
        return []

    key = test.get("order_key")

    if not key:
        return ["row order is required, but order_key is missing"]

    sql = test["reference_sql"]
    limit = re.search(r"\bLIMIT\s+(\d+)\b", sql, re.IGNORECASE)

    if limit:
        sql = sql[:limit.start()] + f"LIMIT {int(limit.group(1)) + 1}" + sql[limit.end():]

    cursor = connection.execute(sql)
    columns = [column[0] for column in cursor.description]
    rows = cursor.fetchall()

    missing = [name for name in key if name not in columns]

    if missing:
        return [f"order_key columns are missing from the result: {missing}"]

    indexes = [columns.index(name) for name in key]
    values = [tuple(row[index] for index in indexes) for row in rows]

    if len(set(values)) != len(values):
        return [f"sort key {key} contains duplicates (including the top-N boundary)"]

    return []


def build_dataset() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DATABASE_PATH}")

    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    problems: list[str] = []
    tests = []

    try:
        for number, case in enumerate(TEST_CASES, start=1):
            test_id = f"h{number:02d}"
            sql = case["reference_sql"].strip()

            columns, rows = execute_reference_query(connection, sql)

            test = {
                "id": test_id,
                "question": case["question"],
                "category": case["category"],
                "reference_sql": sql,
                "expected_columns": columns,
                "expected_result": rows,
            }

            if "order_key" in case:
                test["order_key"] = case["order_key"]

            # Strict scoring requires order only when it is part of the question meaning.
            test["order_sensitive"] = order_required(test)

            if not rows:
                problems.append(f"{test_id}: empty result")

            if len(rows) > MAX_EXPECTED_ROWS:
                problems.append(f"{test_id}: result is too large ({len(rows)} rows)")

            for problem in check_order_is_unambiguous(connection, test):
                problems.append(f"{test_id}: {problem}")

            tests.append(test)
    finally:
        connection.close()

    if problems:
        raise SystemExit("Dataset creation failed:\n  " + "\n  ".join(problems))

    dataset = {
        "project": "QueryPilot",
        "role": "heldout",
        "version": 2,
        "database": "SQLite",
        "language": "en",
        "test_count": len(tests),
        "created_with_prompt_sha256_prefix": prompt_fingerprint(),
        "tests": tests,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    counts: dict[str, int] = {}

    for test in tests:
        counts[test["category"]] = counts.get(test["category"], 0) + 1

    print(f"Heldout dataset created: {len(tests)} questions -> {OUTPUT_PATH}")

    for name, count in sorted(counts.items()):
        print(f"  {name:26} {count}")


if __name__ == "__main__":
    build_dataset()

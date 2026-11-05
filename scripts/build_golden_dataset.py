
from pathlib import Path
import json
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "database" / "querypilot.db"
OUTPUT_PATH = PROJECT_ROOT / "tests" / "golden_questions.json"


# Benchmark questions and reference SQL are authored manually; questions are in English.
# Expected results are computed from the current test database.
TEST_CASES = [
    {
        "id": "q01",
        "question": "Which active products cost less than 500 UAH? Show the first 10.",
        "category": "filtering",
        "reference_sql": """
            SELECT product_id, name, price_cents
            FROM products
            WHERE is_active = 1 AND price_cents < 50000
            ORDER BY price_cents, product_id
            LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "id": "q02",
        "question": "How many customers live in each city?",
        "category": "aggregation",
        "reference_sql": """
            SELECT city, COUNT(*) AS customer_count
            FROM customers
            GROUP BY city
            ORDER BY customer_count DESC, city
        """,
        "order_sensitive": True,
    },
    {
        "id": "q03",
        "question": "How many customers have not placed any orders?",
        "category": "joins",
        "reference_sql": """
            SELECT COUNT(*) AS customers_without_orders
            FROM customers AS c
            WHERE NOT EXISTS (
                SELECT 1
                FROM orders AS o
                WHERE o.customer_id = c.customer_id
            )
        """,
        "order_sensitive": False,
    },
    {
        "id": "q04",
        "question": "How many products have never appeared in any order?",
        "category": "subqueries",
        "reference_sql": """
            SELECT COUNT(*) AS products_never_ordered
            FROM products AS p
            WHERE NOT EXISTS (
                SELECT 1
                FROM order_items AS oi
                WHERE oi.product_id = p.product_id
            )
        """,
        "order_sensitive": False,
    },
    {
        "id": "q05",
        "question": "Which products have not been sold in delivered orders?",
        "category": "subqueries",
        "reference_sql": """
            SELECT p.product_id, p.name
            FROM products AS p
            WHERE NOT EXISTS (
                SELECT 1
                FROM order_items AS oi
                JOIN orders AS o ON o.order_id = oi.order_id
                WHERE oi.product_id = p.product_id
                  AND o.status = 'delivered'
            )
            ORDER BY p.product_id
        """,
        "order_sensitive": True,
    },
    {
        "id": "q06",
        "question": "Show the 10 most expensive products, with their names and prices.",
        "category": "sorting",
        "reference_sql": """
            SELECT product_id, name, price_cents
            FROM products
            ORDER BY price_cents DESC, product_id
            LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "id": "q07",
        "question": "How many orders are there for each status?",
        "category": "aggregation",
        "reference_sql": """
            SELECT status, COUNT(*) AS order_count
            FROM orders
            GROUP BY status
            ORDER BY status
        """,
        "order_sensitive": True,
    },
    {
        "id": "q08",
        "question": "What is the monthly revenue from delivered orders after discounts?",
        "category": "aggregation",
        "reference_sql": """
            SELECT
                substr(o.ordered_at, 1, 7) AS month,
                SUM(
                    order_totals.item_total - o.discount_cents
                ) AS revenue_cents
            FROM orders AS o
            JOIN (
                SELECT
                    order_id,
                    SUM(quantity * unit_price_cents) AS item_total
                FROM order_items
                GROUP BY order_id
            ) AS order_totals ON order_totals.order_id = o.order_id
            WHERE o.status = 'delivered'
            GROUP BY substr(o.ordered_at, 1, 7)
            ORDER BY month
        """,
        "order_sensitive": True,
    },
    {
        "id": "q09",
        "question": "Which categories have the highest gross value of products sold in delivered orders before discounts? Show all categories.",
        "category": "multi_table_aggregation",
        "reference_sql": """
            SELECT
                c.name AS category_name,
                SUM(oi.quantity * oi.unit_price_cents) AS gross_sales_cents
            FROM categories AS c
            JOIN products AS p ON p.category_id = c.category_id
            JOIN order_items AS oi ON oi.product_id = p.product_id
            JOIN orders AS o ON o.order_id = oi.order_id
            WHERE o.status = 'delivered'
            GROUP BY c.category_id, c.name
            ORDER BY gross_sales_cents DESC, c.name
        """,
        "order_sensitive": True,
    },
    {
        "id": "q10",
        "question": "Show the 10 products with the highest average rating, considering only products with at least five reviews.",
        "category": "aggregation",
        "reference_sql": """
            SELECT
                p.product_id,
                p.name,
                ROUND(AVG(r.rating), 2) AS average_rating,
                COUNT(*) AS review_count
            FROM products AS p
            JOIN reviews AS r ON r.product_id = p.product_id
            GROUP BY p.product_id, p.name
            HAVING COUNT(*) >= 5
            ORDER BY average_rating DESC, review_count DESC, p.product_id
            LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "id": "q11",
        "question": "Which customers have placed more than three orders? Show the first 10, ordered by order count.",
        "category": "aggregation",
        "reference_sql": """
            SELECT
                c.customer_id,
                c.full_name,
                COUNT(o.order_id) AS order_count
            FROM customers AS c
            JOIN orders AS o ON o.customer_id = c.customer_id
            GROUP BY c.customer_id, c.full_name
            HAVING COUNT(o.order_id) > 3
            ORDER BY order_count DESC, c.customer_id
            LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "id": "q12",
        "question": "Show the 10 most expensive orders after discounts are applied.",
        "category": "subqueries",
        "reference_sql": """
            SELECT
                o.order_id,
                o.status,
                (
                    SELECT SUM(oi.quantity * oi.unit_price_cents)
                    FROM order_items AS oi
                    WHERE oi.order_id = o.order_id
                ) - o.discount_cents AS total_cents
            FROM orders AS o
            ORDER BY total_cents DESC, o.order_id
            LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "id": "q13",
        "question": "How many orders used each coupon? Also show coupons that were never used.",
        "category": "joins",
        "reference_sql": """
            SELECT
                c.coupon_id,
                c.code,
                COUNT(o.order_id) AS usage_count
            FROM coupons AS c
            LEFT JOIN orders AS o ON o.coupon_id = c.coupon_id
            GROUP BY c.coupon_id, c.code
            ORDER BY usage_count DESC, c.coupon_id
        """,
        "order_sensitive": True,
    },
    {
        "id": "q14",
        "question": "How many orders have no payment record?",
        "category": "subqueries",
        "reference_sql": """
            SELECT COUNT(*) AS orders_without_payments
            FROM orders AS o
            WHERE NOT EXISTS (
                SELECT 1
                FROM payments AS p
                WHERE p.order_id = o.order_id
            )
        """,
        "order_sensitive": False,
    },
    {
        "id": "q15",
        "question": "What is the total amount of successful payments by month?",
        "category": "aggregation",
        "reference_sql": """
            SELECT
                substr(p.paid_at, 1, 7) AS month,
                SUM(p.amount_cents) AS successful_amount_cents
            FROM payments AS p
            WHERE p.status = 'successful'
              AND p.paid_at IS NOT NULL
            GROUP BY substr(p.paid_at, 1, 7)
            ORDER BY month
        """,
        "order_sensitive": True,
    },
    {
        "id": "q16",
        "question": "How many products does each supplier provide, including suppliers with no products?",
        "category": "joins",
        "reference_sql": """
            SELECT
                s.supplier_id,
                s.name AS supplier_name,
                COUNT(p.product_id) AS product_count
            FROM suppliers AS s
            LEFT JOIN products AS p ON p.supplier_id = s.supplier_id
            GROUP BY s.supplier_id, s.name
            ORDER BY product_count DESC, s.supplier_id
        """,
        "order_sensitive": True,
    },
    {
        "id": "q17",
        "question": "How many products currently have zero stock?",
        "category": "filtering",
        "reference_sql": """
            SELECT COUNT(*) AS out_of_stock_count
            FROM products
            WHERE stock_quantity = 0
        """,
        "order_sensitive": False,
    },
    {
        "id": "q18",
        "question": "How many reviews are there for each rating from 1 to 5?",
        "category": "aggregation",
        "reference_sql": """
            SELECT rating, COUNT(*) AS review_count
            FROM reviews
            GROUP BY rating
            ORDER BY rating
        """,
        "order_sensitive": True,
    },
    {
        "id": "q19",
        "question": "Show the 10 most recently registered customers.",
        "category": "sorting",
        "reference_sql": """
            SELECT customer_id, full_name, city, registered_at
            FROM customers
            ORDER BY registered_at DESC, customer_id
            LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "id": "q20",
        "question": "How many products are in each category?",
        "category": "joins",
        "reference_sql": """
            SELECT
                c.name AS category_name,
                COUNT(p.product_id) AS product_count
            FROM categories AS c
            LEFT JOIN products AS p ON p.category_id = c.category_id
            GROUP BY c.category_id, c.name
            ORDER BY c.category_id
        """,
        "order_sensitive": True,
    },
    {
        "id": "q21",
        "question": "Which five products were purchased in the largest quantities in delivered orders?",
        "category": "multi_table_aggregation",
        "reference_sql": """
            SELECT
                p.product_id,
                p.name,
                SUM(oi.quantity) AS units_sold
            FROM products AS p
            JOIN order_items AS oi ON oi.product_id = p.product_id
            JOIN orders AS o ON o.order_id = oi.order_id
            WHERE o.status = 'delivered'
            GROUP BY p.product_id, p.name
            ORDER BY units_sold DESC, p.product_id
            LIMIT 5
        """,
        "order_sensitive": True,
    },
    {
        "id": "q22",
        "question": "Show the 10 most recent orders that used a coupon.",
        "category": "joins",
        "reference_sql": """
            SELECT
                o.order_id,
                o.ordered_at,
                c.code AS coupon_code,
                o.discount_cents
            FROM orders AS o
            JOIN coupons AS c ON c.coupon_id = o.coupon_id
            ORDER BY o.ordered_at DESC, o.order_id DESC
            LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "id": "q23",
        "question": "How many orders of each status were placed in 2026?",
        "category": "date_filtering",
        "reference_sql": """
            SELECT status, COUNT(*) AS order_count
            FROM orders
            WHERE ordered_at >= '2026-01-01'
              AND ordered_at < '2027-01-01'
            GROUP BY status
            ORDER BY status
        """,
        "order_sensitive": True,
    },
    {
        "id": "q24",
        "question": "How many customers registered in each year?",
        "category": "date_aggregation",
        "reference_sql": """
            SELECT
                substr(registered_at, 1, 4) AS registration_year,
                COUNT(*) AS customer_count
            FROM customers
            GROUP BY substr(registered_at, 1, 4)
            ORDER BY registration_year
        """,
        "order_sensitive": True,
    },
    {
        "id": "q25",
        "question": "Which products have an average rating above 4 and at least three reviews? Show the first 10.",
        "category": "aggregation",
        "reference_sql": """
            SELECT
                p.product_id,
                p.name,
                ROUND(AVG(r.rating), 2) AS average_rating,
                COUNT(*) AS review_count
            FROM products AS p
            JOIN reviews AS r ON r.product_id = p.product_id
            GROUP BY p.product_id, p.name
            HAVING AVG(r.rating) > 4 AND COUNT(*) >= 3
            ORDER BY average_rating DESC, p.product_id
            LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "id": "q26",
        "question": "How many orders contain at least three distinct product line items?",
        "category": "aggregation",
        "reference_sql": """
            SELECT COUNT(*) AS orders_with_three_or_more_items
            FROM (
                SELECT order_id
                FROM order_items
                GROUP BY order_id
                HAVING COUNT(*) >= 3
            )
        """,
        "order_sensitive": False,
    },
    {
        "id": "q27",
        "question": "How many payments are there for each status?",
        "category": "aggregation",
        "reference_sql": """
            SELECT status, COUNT(*) AS payment_count
            FROM payments
            GROUP BY status
            ORDER BY status
        """,
        "order_sensitive": True,
    },
    {
        "id": "q28",
        "question": "How many shipments are there for each carrier?",
        "category": "aggregation",
        "reference_sql": """
            SELECT carrier, COUNT(*) AS shipment_count
            FROM shipments
            GROUP BY carrier
            ORDER BY shipment_count DESC, carrier
        """,
        "order_sensitive": True,
    },
    {
        "id": "q29",
        "question": "How many cancelled orders have no shipment record?",
        "category": "joins",
        "reference_sql": """
            SELECT COUNT(*) AS cancelled_without_shipment
            FROM orders AS o
            WHERE o.status = 'cancelled'
              AND NOT EXISTS (
                  SELECT 1
                  FROM shipments AS s
                  WHERE s.order_id = o.order_id
              )
        """,
        "order_sensitive": False,
    },
    {
        "id": "q30",
        "question": "Show the 10 orders with the largest discounts, including order ID, status, and discount amount.",
        "category": "sorting",
        "reference_sql": """
            SELECT order_id, status, discount_cents
            FROM orders
            WHERE discount_cents > 0
            ORDER BY discount_cents DESC, order_id
            LIMIT 10
        """,
        "order_sensitive": True,
    },
]


def execute_reference_query(
        connection: sqlite3.Connection,
        sql: str,
) -> tuple[list[str], list[dict]]:
    """Execute the reference query and return its columns and rows."""
    cursor = connection.execute(sql)

    if cursor.description is None:
        raise ValueError("The query returned no columns.")

    columns = [column[0] for column in cursor.description]
    rows = [
        dict(row)
        for row in cursor.fetchall()
    ]

    return columns, rows


def build_dataset() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}. "
            "Run scripts/init_db.py first "
            "and scripts/seed_data.py."
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    database_uri = DATABASE_PATH.resolve().as_uri() + "?mode=ro"

    results = []

    with sqlite3.connect(database_uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row

        # Additional check: the database must contain
        # all ten expected tables.
        existing_tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        required_tables = {
            "customers",
            "categories",
            "suppliers",
            "products",
            "coupons",
            "orders",
            "order_items",
            "payments",
            "shipments",
            "reviews",
        }

        missing_tables = required_tables - existing_tables

        if missing_tables:
            raise RuntimeError(
                "Missing database tables: "
                + ", ".join(sorted(missing_tables))
            )

        for test_case in TEST_CASES:
            try:
                columns, expected_result = execute_reference_query(
                    connection,
                    test_case["reference_sql"],
                )
            except sqlite3.Error as error:
                raise RuntimeError(
                    f"Reference query failed "
                    f"{test_case['id']}: {error}"
                ) from error

            results.append({
                "id": test_case["id"],
                "question": test_case["question"],
                "category": test_case["category"],
                "reference_sql": test_case["reference_sql"].strip(),
                "expected_columns": columns,
                "expected_result": expected_result,
                "order_sensitive": test_case["order_sensitive"],
            })

    dataset = {
        "project": "QueryPilot",
        "version": 2,
        "database": "SQLite",
        "language": "en",
        "test_count": len(results),
        "tests": results,
    }

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(
            dataset,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")

    print("Golden benchmark dataset created successfully.")
    print(f"Test count: {len(results)}")
    print(f"Path: {OUTPUT_PATH}")
    print("\nCategories:")

    category_counts = {}

    for test_case in results:
        category = test_case["category"]
        category_counts[category] = (
                category_counts.get(category, 0) + 1
        )

    for category, count in sorted(category_counts.items()):
        print(f"  {category}: {count}")

    print("\nAll reference queries executed successfully.")


if __name__ == "__main__":
    build_dataset()

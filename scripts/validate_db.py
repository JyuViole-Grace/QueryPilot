
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "querypilot.db"


CHECKS = {
    "Customers without orders": """
        SELECT COUNT(*)
        FROM customers c
        WHERE NOT EXISTS (
            SELECT 1 FROM orders o
            WHERE o.customer_id = c.customer_id
        )
    """,
    "Products not sold in delivered orders": """
        SELECT COUNT(*)
        FROM products p
        WHERE NOT EXISTS (
            SELECT 1
            FROM order_items oi
            JOIN orders o ON o.order_id = oi.order_id
            WHERE oi.product_id = p.product_id
              AND o.status IN ('shipped', 'delivered')
        )
    """,
    "Orders placed before customer registration": """
        SELECT COUNT(*)
        FROM orders o
        JOIN customers c ON c.customer_id = o.customer_id
        WHERE date(o.ordered_at) < date(c.registered_at)
    """,
    "Discounts exceeding line-item totals": """
        SELECT COUNT(*)
        FROM orders o
        JOIN (
            SELECT order_id,
                   SUM(quantity * unit_price_cents) AS total_cents
            FROM order_items
            GROUP BY order_id
        ) t ON t.order_id = o.order_id
        WHERE o.discount_cents > t.total_cents
    """,
    "Coupon used outside its validity period": """
        SELECT COUNT(*)
        FROM orders o
        JOIN coupons c ON c.coupon_id = o.coupon_id
        WHERE date(o.ordered_at) < date(c.valid_from)
           OR date(o.ordered_at) > date(c.valid_until)
    """,
    "Reviews dated before customer registration": """
        SELECT COUNT(*)
        FROM reviews r
        JOIN customers c ON c.customer_id = r.customer_id
        WHERE date(r.created_at) < date(c.registered_at)
    """,
    "Foreign-key violations": """
        PRAGMA foreign_key_check
    """,
}


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    # Read-only mode: the audit must not modify the database.
    uri = DB_PATH.as_uri() + "?mode=ro"

    with sqlite3.connect(uri, uri=True) as con:
        print("QueryPilot database audit")
        print("=" * 55)

        print("\nOrder statuses:")
        for status, count in con.execute("""
            SELECT status, COUNT(*)
            FROM orders
            GROUP BY status
            ORDER BY status
        """):
            print(f"  {status}: {count}")

        print("\nValidation results:")

        for title, sql in CHECKS.items():
            result = con.execute(sql).fetchall()

            if title == "Foreign-key violations":
                count = len(result)
                print(f"  {title}: {count}")
                if result:
                    print(f"    Examples: {result[:5]}")
            else:
                count = result[0][0]
                print(f"  {title}: {count}")

        print("\nRow counts:")
        for table in (
                "customers", "categories", "suppliers",
                "products", "coupons", "orders", "order_items",
                "payments", "shipments", "reviews",
        ):
            count = con.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            print(f"  {table}: {count}")


if __name__ == "__main__":
    main()

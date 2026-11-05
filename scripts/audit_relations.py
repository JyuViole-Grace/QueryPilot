
from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "database" / "querypilot.db"


def main() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DATABASE_PATH}")

    # Open the database in read-only mode.
    database_uri = DATABASE_PATH.as_uri() + "?mode=ro"

    with sqlite3.connect(database_uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row

        print("Audit order, payment, and shipment relationships")
        print("=" * 55)

        print("\n1. Payment statuses by order status:")

        rows = connection.execute(
            """
            SELECT
                o.status AS order_status,
                p.status AS payment_status,
                COUNT(*) AS records
            FROM orders AS o
            JOIN payments AS p ON p.order_id = o.order_id
            GROUP BY o.status, p.status
            ORDER BY o.status, p.status
            """
        ).fetchall()

        for row in rows:
            print(
                f"  Order: {row['order_status']:<12} "
                f"Payment: {row['payment_status']:<10} "
                f"Records: {row['records']}"
            )

        print("\n2. Orders without payments:")

        rows = connection.execute(
            """
            SELECT o.order_id, o.status
            FROM orders AS o
            LEFT JOIN payments AS p ON p.order_id = o.order_id
            WHERE p.payment_id IS NULL
            ORDER BY o.order_id
            """
        ).fetchall()

        print(f"  Count: {len(rows)}")
        if rows:
            print("  Examples:", [
                (row["order_id"], row["status"])
                for row in rows[:10]
            ])

        print("\n3. Shipment statuses by order status:")

        rows = connection.execute(
            """
            SELECT
                o.status AS order_status,
                s.status AS shipment_status,
                COUNT(*) AS records
            FROM orders AS o
            JOIN shipments AS s ON s.order_id = o.order_id
            GROUP BY o.status, s.status
            ORDER BY o.status, s.status
            """
        ).fetchall()

        for row in rows:
            print(
                f"  Order: {row['order_status']:<12} "
                f"Shipment: {row['shipment_status']:<10} "
                f"Records: {row['records']}"
            )

        print("\n4. Shipment date validation:")

        invalid_dates = connection.execute(
            """
            SELECT shipment_id, shipped_at, delivered_at
            FROM shipments
            WHERE delivered_at IS NOT NULL
              AND delivered_at < shipped_at
            """
        ).fetchall()

        print(f"  Shipment before dispatch: {len(invalid_dates)}")

        missing_delivery_date = connection.execute(
            """
            SELECT shipment_id, status
            FROM shipments
            WHERE status = 'delivered'
              AND delivered_at IS NULL
            """
        ).fetchall()

        print(
            "  Delivered shipments without a delivery timestamp: "
            f"{len(missing_delivery_date)}"
        )

        print("\n5. Orders with delivered status but no shipment:")

        missing_shipments = connection.execute(
            """
            SELECT o.order_id
            FROM orders AS o
            LEFT JOIN shipments AS s ON s.order_id = o.order_id
            WHERE o.status = 'delivered'
              AND s.shipment_id IS NULL
            """
        ).fetchall()

        print(f"  Count: {len(missing_shipments)}")


if __name__ == "__main__":
    main()

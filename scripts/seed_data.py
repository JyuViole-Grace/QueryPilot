
from pathlib import Path
import random
import sqlite3
from datetime import date, timedelta


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "database" / "querypilot.db"

# Fixed random seed for reproducibility.
RANDOM_SEED = 42

START_DATE = date(2025, 1, 1)
END_DATE = date(2026, 9, 30)

# Registration history starts before order history.
REGISTRATION_START = date(2023, 1, 1)
REGISTRATION_END = date(2024, 12, 31)

# Products 79 and 80 will remain unsold.
UNSOLD_PRODUCT_IDS = {79, 80}


def random_date(rng: random.Random) -> str:
    """Return a random date within the store history period."""
    days = (END_DATE - START_DATE).days
    return (
            START_DATE + timedelta(days=rng.randint(0, days))
    ).isoformat()


def random_registration_date(rng: random.Random) -> str:
    """Return a registration date before order history begins."""
    days = (REGISTRATION_END - REGISTRATION_START).days
    return (
            REGISTRATION_START + timedelta(days=rng.randint(0, days))
    ).isoformat()


def seed_database() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}. "
            "Run scripts/init_db.py first"
        )

    rng = random.Random(RANDOM_SEED)

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")

        # Clear tables in foreign-key-safe order.
        for table in (
                "reviews",
                "shipments",
                "payments",
                "order_items",
                "orders",
                "products",
                "coupons",
                "suppliers",
                "categories",
                "customers",
        ):
            connection.execute(f"DELETE FROM {table}")

        # -----------------------------------------------------
        # 1. Customers
        # -----------------------------------------------------
        cities = [
            "Lviv", "Kyiv", "Odesa", "Kharkiv",
            "Dnipro", "Vinnytsia", "Poltava", "Cherkasy",
        ]

        first_names = [
            "Oleksandr", "Maria", "Dmytro", "Anna",
            "Maksym", "Sofia", "Artem", "Olena",
            "Ivan", "Daria", "Nikita", "Viktoria",
        ]

        last_names = [
            "Kovalenko", "Bondarenko", "Tkachenko",
            "Melnyk", "Shevchenko", "Kravchenko",
            "Oliinyk", "Polishchuk", "Boiko", "Moroz",
        ]

        customers = []

        for customer_id in range(1, 101):
            full_name = (
                f"{rng.choice(first_names)} "
                f"{rng.choice(last_names)}"
            )

            customers.append((
                customer_id,
                full_name,
                f"customer{customer_id}@example.com",
                rng.choice(cities),
                random_registration_date(rng),
            ))

        connection.executemany(
            """
            INSERT INTO customers
                (customer_id, full_name, email, city, registered_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            customers,
        )

        # -----------------------------------------------------
        # 2. Categories
        # -----------------------------------------------------
        category_names = [
            "Laptops",
            "Smartphones",
            "Monitors",
            "Components",
            "Peripherals",
            "Audio",
            "Networking Equipment",
            "Accessories",
        ]

        connection.executemany(
            "INSERT INTO categories (category_id, name) VALUES (?, ?)",
            list(enumerate(category_names, start=1)),
        )

        # -----------------------------------------------------
        # 3. Suppliers
        # -----------------------------------------------------
        supplier_names = [
            "TechNova", "DigitalCore", "NextWave",
            "ElectroHub", "SmartSupply", "ByteWorks",
            "GlobalTech", "NovaParts", "DeviceWorld",
            "PrimeSystems", "MegaElectro", "FutureGear",
        ]

        countries = [
            "Ukraine", "Poland", "Germany",
            "Czechia", "China", "Taiwan",
        ]

        suppliers = [
            (i, name, rng.choice(countries))
            for i, name in enumerate(supplier_names, start=1)
        ]

        connection.executemany(
            """
            INSERT INTO suppliers (supplier_id, name, country)
            VALUES (?, ?, ?)
            """,
            suppliers,
        )

        # -----------------------------------------------------
        # 4. Coupons
        # -----------------------------------------------------
        coupons = []

        for coupon_id in range(1, 11):
            start = date(2025, 1, 1) + timedelta(
                days=(coupon_id - 1) * 30
            )
            end = min(start + timedelta(days=180), END_DATE)

            coupons.append((
                coupon_id,
                f"SALE{coupon_id:02d}",
                rng.choice([5, 10, 15, 20, 25]),
                start.isoformat(),
                end.isoformat(),
                1 if coupon_id <= 7 else 0,
            ))

        connection.executemany(
            """
            INSERT INTO coupons
                (coupon_id, code, discount_percent,
                 valid_from, valid_until, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            coupons,
        )

        # Index coupons for discount calculations.
        coupon_by_id = {
            coupon[0]: coupon
            for coupon in coupons
        }

        # -----------------------------------------------------
        # 5. Products
        # -----------------------------------------------------
        product_prefixes = [
            "Nova", "Hyper", "Quantum", "Vertex",
            "Pulse", "Titan", "Orbit", "Zenith",
            "Aero", "Vector",
        ]

        product_types = [
            "Pro", "Ultra", "Air", "Max",
            "Core", "Plus", "Elite", "X",
        ]

        products = []

        for product_id in range(1, 81):
            category_id = (product_id - 1) % 8 + 1
            supplier_id = (product_id - 1) % 12 + 1

            # Store prices as integer cents.
            price_cents = rng.randrange(5000, 250000, 100)

            products.append((
                product_id,
                f"{rng.choice(product_prefixes)} "
                f"{rng.choice(product_types)} {product_id:02d}",
                category_id,
                supplier_id,
                price_cents,
                rng.randint(0, 100),
                0 if product_id % 13 == 0 else 1,
            ))

        connection.executemany(
            """
            INSERT INTO products
                (product_id, name, category_id, supplier_id,
                 price_cents, stock_quantity, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            products,
        )

        # -----------------------------------------------------
        # 6. Orders
        # -----------------------------------------------------
        order_statuses = [
            "pending", "processing", "shipped",
            "delivered", "cancelled", "returned",
        ]

        orders = []

        for order_id in range(1, 301):
            # Customers 86–100 will have no orders.
            customer_id = rng.randint(1, 85)

            status = rng.choices(
                order_statuses,
                weights=[8, 12, 20, 42, 12, 6],
                k=1,
            )[0]

            ordered_at = random_date(rng)

            # Select only active coupons
            # valid on the order date.
            eligible_coupons = [
                coupon
                for coupon in coupons
                if coupon[5] == 1
                   and coupon[3] <= ordered_at <= coupon[4]
            ]

            coupon_id = (
                rng.choice(eligible_coupons)[0]
                if eligible_coupons and rng.random() < 0.3
                else None
            )

            # Calculate discounts after order items are created.
            discount_cents = 0

            orders.append((
                order_id,
                customer_id,
                ordered_at,
                status,
                coupon_id,
                discount_cents,
            ))

        connection.executemany(
            """
            INSERT INTO orders
                (order_id, customer_id, ordered_at, status,
                 coupon_id, discount_cents)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            orders,
        )

        # -----------------------------------------------------
        # 7. Order items
        # A product appears at most once per order.
        # -----------------------------------------------------
        order_items = []
        order_item_id = 1

        # Avoid iterating over all order items again
        # for every order when calculating totals.
        order_totals = {}

        for order_id in range(1, 301):
            item_count = rng.randint(1, 4)

            # Products 79 and 80 are excluded from sales.
            selected_products = rng.sample(
                range(1, 79),
                k=item_count,
            )

            item_total = 0

            for product_id in selected_products:
                # Preserve the historical purchase price.
                catalog_price = products[product_id - 1][4]
                adjustment_percent = rng.randint(-10, 10)

                # Use integer arithmetic instead of float.
                unit_price_cents = max(
                    1,
                    catalog_price
                    * (100 + adjustment_percent)
                    // 100,
                    )

                quantity = rng.randint(1, 3)

                order_items.append((
                    order_item_id,
                    order_id,
                    product_id,
                    quantity,
                    unit_price_cents,
                ))

                item_total += quantity * unit_price_cents
                order_item_id += 1

            order_totals[order_id] = item_total

        connection.executemany(
            """
            INSERT INTO order_items
                (order_item_id, order_id, product_id,
                 quantity, unit_price_cents)
            VALUES (?, ?, ?, ?, ?)
            """,
            order_items,
        )

        # -----------------------------------------------------
        # 8. Discount calculations
        # Calculate the discount from the order line-item total.
        # -----------------------------------------------------
        updated_orders = []

        for (
                order_id,
                customer_id,
                ordered_at,
                status,
                coupon_id,
                _,
        ) in orders:
            discount_cents = 0

            if coupon_id is not None:
                coupon = coupon_by_id[coupon_id]
                discount_percent = coupon[2]

                discount_cents = (
                        order_totals[order_id]
                        * discount_percent
                        // 100
                )

            updated_orders.append((
                order_id,
                customer_id,
                ordered_at,
                status,
                coupon_id,
                discount_cents,
            ))

            connection.execute(
                """
                UPDATE orders
                SET discount_cents = ?
                WHERE order_id = ?
                """,
                (discount_cents, order_id),
            )

        # Payments and shipments reference existing orders.
        orders = updated_orders


        # -----------------------------------------------------
        # 9. Payments
        # Select payment statuses based on order status.
        # -----------------------------------------------------
        payments = []
        payment_id = 1

        for (
                order_id,
                _,
                ordered_at,
                order_status,
                _,
                discount_cents,
        ) in orders:

            # Cancelled orders usually have no payment.
            if order_status == "cancelled":
                if rng.random() < 0.8:
                    continue

                payment_status = rng.choice(["failed", "refunded"])

            elif order_status == "pending":
                payment_status = rng.choices(
                    ["pending", "failed"],
                    weights=[65, 35],
                    k=1,
                )[0]

            elif order_status == "processing":
                payment_status = rng.choices(
                    ["successful", "pending", "failed"],
                    weights=[70, 20, 10],
                    k=1,
                )[0]

            elif order_status in ("shipped", "delivered"):
                payment_status = "successful"

            elif order_status == "returned":
                payment_status = rng.choices(
                    ["refunded", "successful"],
                    weights=[85, 15],
                    k=1,
                )[0]

            else:
                raise ValueError(
                    f"Unknown order status: {order_status}"
                )

            amount_cents = max(
                0,
                order_totals[order_id] - discount_cents,
                )

            paid_at = (
                ordered_at
                if payment_status in ("successful", "refunded")
                else None
            )

            payments.append((
                payment_id,
                order_id,
                amount_cents,
                payment_status,
                paid_at,
            ))
            payment_id += 1

            # Add an extra failed payment attempt.
            # This is possible only for orders
            # that have not shipped or been delivered.
            if (
                    order_status in ("pending", "processing")
                    and rng.random() < 0.08
            ):
                payments.append((
                    payment_id,
                    order_id,
                    amount_cents,
                    "failed",
                    None,
                ))
                payment_id += 1

        connection.executemany(
            """
            INSERT INTO payments
                (payment_id, order_id, amount_cents, status, paid_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            payments,
        )


        # -----------------------------------------------------
        # 10. Shipments
        # -----------------------------------------------------
        shipments = []
        shipment_id = 1

        carriers = [
            "Nova Post", "Ukrposhta", "Meest",
        ]

        for (
                order_id,
                _,
                ordered_at,
                status,
                _,
                _,
        ) in orders:
            if status not in ("shipped", "delivered", "returned"):
                continue

            shipped_date = (
                    date.fromisoformat(ordered_at)
                    + timedelta(days=rng.randint(1, 5))
            )

            if status in ("delivered", "returned"):
                delivered_date = shipped_date + timedelta(
                    days=rng.randint(1, 7)
                )
                shipment_status = "delivered"
            else:
                delivered_date = None
                shipment_status = rng.choice(
                    ["shipped", "in_transit"]
                )

            shipments.append((
                shipment_id,
                order_id,
                rng.choice(carriers),
                shipment_status,
                shipped_date.isoformat(),
                (
                    delivered_date.isoformat()
                    if delivered_date
                    else None
                ),
            ))

            shipment_id += 1

        connection.executemany(
            """
            INSERT INTO shipments
                (shipment_id, order_id, carrier, status,
                 shipped_at, delivered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            shipments,
        )

        # -----------------------------------------------------
        # 11. Reviews
        # Review dates occur after customer registration dates.
        # -----------------------------------------------------
        reviews = []
        review_id = 1
        reviewed_pairs = set()

        while len(reviews) < 200:
            customer_id = rng.randint(1, 100)
            product_id = rng.randint(1, 80)

            pair = (customer_id, product_id)

            if pair in reviewed_pairs:
                continue

            reviewed_pairs.add(pair)

            reviews.append((
                review_id,
                customer_id,
                product_id,
                rng.choices(
                    [1, 2, 3, 4, 5],
                    weights=[3, 5, 12, 30, 50],
                    k=1,
                )[0],
                random_date(rng),
            ))

            review_id += 1

        connection.executemany(
            """
            INSERT INTO reviews
                (review_id, customer_id, product_id,
                 rating, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            reviews,
        )

        # -----------------------------------------------------
        # 12. Integrity checks
        # -----------------------------------------------------
        fk_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if fk_errors:
            raise RuntimeError(
                f"Foreign-key violations found: {fk_errors}"
            )

        print("Test data created successfully.")
        print(f"Seed: {RANDOM_SEED}")
        print("\nRow counts:")

        for table in (
                "customers", "categories", "suppliers",
                "products", "coupons", "orders", "order_items",
                "payments", "shipments", "reviews",
        ):
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

            print(f"  {table}: {count}")

        print("\nForeign-key check: no errors.")


if __name__ == "__main__":
    seed_database()

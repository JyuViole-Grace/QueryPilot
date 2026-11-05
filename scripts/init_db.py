
from pathlib import Path
import sqlite3


# Project root directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Schema file and target database path
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
DATABASE_PATH = PROJECT_ROOT / "database" / "querypilot.db"


def initialize_database() -> None:
    """Create the database and validate its table structure."""

    # Check whether the schema file exists.
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"Schema file not found: {SCHEMA_PATH}"
        )

    # Create the database directory if needed.
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Read the SQL file as UTF-8.
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # Connect to SQLite.
    # SQLite creates the database file if it does not exist.
    with sqlite3.connect(DATABASE_PATH) as connection:
        # Enable foreign-key enforcement for this connection.
        connection.execute("PRAGMA foreign_keys = ON")

        # Apply the SQL schema.
        connection.executescript(schema_sql)

        # Verify that SQLite enforces foreign keys.
        foreign_keys_enabled = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

        if foreign_keys_enabled != 1:
            raise RuntimeError(
                "Could not enable foreign-key enforcement"
            )

        # Get the list of user tables.
        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        table_names = [row[0] for row in tables]

        # Validate the expected table count.
        expected_tables = {
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

        actual_tables = set(table_names)

        missing_tables = expected_tables - actual_tables
        unexpected_tables = actual_tables - expected_tables

        if missing_tables or unexpected_tables:
            raise RuntimeError(
                f"Database schema validation failed.\n"
                f"Missing: {sorted(missing_tables)}\n"
                f"Unexpected: {sorted(unexpected_tables)}"
            )

        # Check existing foreign-key integrity.
        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if foreign_key_errors:
            raise RuntimeError(
                f"Foreign-key violations detected: "
                f"{foreign_key_errors}"
            )

    print("Database initialized successfully.")
    print(f"Path: {DATABASE_PATH}")
    print(f"Table count: {len(table_names)}")
    print("Foreign keys: enabled and verified")
    print("\nCreated tables:")

    for table_name in table_names:
        print(f"  - {table_name}")


if __name__ == "__main__":
    initialize_database()

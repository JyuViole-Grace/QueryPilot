
from sql_quality import validate_sql_quality


def test_sorted_product_list_requires_order_by():
    question = "Show the 10 cheapest active products."

    sql = """
        SELECT product_id, name, price_cents
        FROM products
        WHERE is_active = 1
        LIMIT 10
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("ORDER BY" in issue for issue in result["issues"])


def test_top_n_request_requires_matching_limit():
    question = "Show the 10 cheapest active products."

    sql = """
        SELECT product_id, name, price_cents
        FROM products
        WHERE is_active = 1
        ORDER BY price_cents ASC, product_id ASC
        LIMIT 5
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("LIMIT" in issue for issue in result["issues"])


def test_correct_sorted_product_list_passes():
    question = "Show the 10 cheapest active products."

    sql = """
        SELECT product_id, name, price_cents
        FROM products
        WHERE is_active = 1
        ORDER BY price_cents ASC, product_id ASC
        LIMIT 10
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []


def test_question_without_explicit_sorting_requirement_passes():
    question = "How many customers are in the database?"

    sql = "SELECT COUNT(*) AS customer_count FROM customers"

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_cheapest_products_require_ascending_price_order():
    question = "Show the 10 cheapest active products."

    sql = """
        SELECT product_id, name, price_cents
        FROM products
        WHERE is_active = 1
        ORDER BY price_cents DESC, product_id ASC
        LIMIT 10
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("ASC" in issue or "ascending" in issue.lower()
               for issue in result["issues"])


def test_most_expensive_products_require_descending_price_order():
    question = "Show the 10 most expensive active products."

    sql = """
        SELECT product_id, name, price_cents
        FROM products
        WHERE is_active = 1
        ORDER BY price_cents ASC, product_id ASC
        LIMIT 10
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("DESC" in issue or "descending" in issue.lower()
               for issue in result["issues"])


def test_price_sorted_products_pass_with_correct_direction():
    question = "Show the 10 cheapest active products."

    sql = """
        SELECT product_id, name, price_cents
        FROM products
        WHERE is_active = 1
        ORDER BY price_cents ASC, product_id ASC
        LIMIT 10
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_customer_city_filter_in_left_join_on_is_rejected():
    question = (
        "How many orders has each customer from the city Kyiv placed, "
        "including customers with no orders? Show the name and count."
    )

    sql = """
        SELECT c.full_name, COUNT(o.order_id) AS order_count
        FROM customers c
        LEFT JOIN orders o
            ON c.customer_id = o.customer_id
            AND c.city = 'Kyiv'
        GROUP BY c.customer_id, c.full_name
        ORDER BY order_count DESC
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("LEFT JOIN ON clause" in issue for issue in result["issues"])


def test_customer_city_filter_in_where_with_left_join_passes():
    question = (
        "How many orders has each customer from the city Kyiv placed, "
        "including customers with no orders? Show the name and count."
    )

    sql = """
        SELECT c.full_name, COUNT(o.order_id) AS order_count
        FROM customers c
        LEFT JOIN orders o
            ON c.customer_id = o.customer_id
        WHERE c.city = 'Kyiv'
        GROUP BY c.customer_id, c.full_name
        ORDER BY order_count DESC
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_customer_without_delivered_orders_rejects_status_inequality():
    question = (
            "How many customers have at least one cancelled order "
            "but no delivered orders?"
    )

    sql = """
        WITH cancelled_orders AS (
            SELECT customer_id
            FROM orders
            WHERE status = 'cancelled'
        ),
        no_delivered_orders AS (
            SELECT customer_id
            FROM orders
            WHERE status != 'delivered'
        )
        SELECT COUNT(DISTINCT co.customer_id) AS customer_count
        FROM cancelled_orders co
        JOIN no_delivered_orders nd
            ON co.customer_id = nd.customer_id
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any(
        "delivered orders" in issue.lower()
        for issue in result["issues"]
    )
def test_customer_without_delivered_orders_with_not_exists_passes():
    question = (
        "How many customers have at least one cancelled order "
        "but no delivered orders?"
    )

    sql = """
        SELECT COUNT(*) AS customer_count
        FROM customers AS c
        WHERE EXISTS (
            SELECT 1
            FROM orders AS o
            WHERE o.customer_id = c.customer_id
              AND o.status = 'cancelled'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM orders AS o
            WHERE o.customer_id = c.customer_id
              AND o.status = 'delivered'
        )
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_orders_not_delivered_allows_status_inequality():
    question = "How many orders are not delivered?"

    sql = """
        SELECT COUNT(*) AS order_count
        FROM orders
        WHERE status != 'delivered'
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_customer_without_delivered_orders_allows_nested_status_inequality():
    question = (
        "How many customers have at least one cancelled order "
        "but no delivered orders?"
    )

    sql = """
        SELECT COUNT(*) AS customer_count
        FROM customers AS c
        WHERE EXISTS (
            SELECT 1
            FROM orders AS cancelled
            WHERE cancelled.customer_id = c.customer_id
              AND cancelled.status = 'cancelled'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM orders AS delivered
            WHERE delivered.customer_id = c.customer_id
              AND delivered.status = 'delivered'
              AND delivered.status != 'returned'
        )
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_city_aggregation_rejects_customer_level_grouping():
    question = (
        "How many product units were purchased by customers "
        "in each city in delivered orders? Show the city and quantity."
    )

    sql = """
        SELECT c.city, SUM(oi.quantity) AS quantity
        FROM customers c
        JOIN orders o ON o.customer_id = c.customer_id
        JOIN order_items oi ON oi.order_id = o.order_id
        WHERE o.status = 'delivered'
        GROUP BY o.customer_id, c.city
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("city" in issue.lower() for issue in result["issues"])


def test_city_aggregation_accepts_grouping_by_city():
    question = (
        "How many product units were purchased by customers "
        "in each city in delivered orders? Show the city and quantity."
    )

    sql = """
        SELECT c.city, SUM(oi.quantity) AS units_sold
        FROM customers AS c
        JOIN orders AS o ON o.customer_id = c.customer_id
        JOIN order_items AS oi ON oi.order_id = o.order_id
        WHERE o.status = 'delivered'
        GROUP BY c.city
        ORDER BY c.city
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []




def test_money_threshold_rejects_incorrect_uah_to_cents_conversion():
    question = "How many payments over 1,000 UAH failed?"

    sql = """
        SELECT COUNT(*) AS failed_payment_count
        FROM payments
        WHERE status = 'failed'
          AND amount_cents > 10000
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any(
        "100000" in issue
        for issue in result["issues"]
    )


def test_money_threshold_accepts_correct_uah_to_cents_conversion():
    question = "How many payments over 1,000 UAH failed?"

    sql = """
        SELECT COUNT(*) AS failed_payment_count
        FROM payments
        WHERE status = 'failed'
          AND amount_cents > 100000
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []




def test_failed_payment_count_accepts_expected_output_name():
    question = "How many payments over 1,000 UAH failed?"

    sql = """
        SELECT COUNT(*) AS failed_payment_count
        FROM payments
        WHERE amount_cents > 100000
          AND status = 'failed'
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []



def test_category_average_accepts_exact_output_names():
    question = (
        "What is the average product price in each category? "
        "Show the category name and average price in kopecks, "
        "rounded to the nearest integer."
    )
    sql = """
        SELECT
            c.name,
            ROUND(AVG(p.price_cents)) AS average_price_cents
        FROM categories c
        JOIN products p ON p.category_id = c.category_id
        GROUP BY c.category_id, c.name
    """
    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []


def test_active_product_price_accepts_average_price_cents():
    question = (
            "What are the minimum, maximum, and average prices of active products? "
            "Round the average to the nearest integer. Show all three values in kopecks."
        )
    sql = """
        SELECT
            MIN(price_cents) AS min_price_cents,
            MAX(price_cents) AS max_price_cents,
            ROUND(AVG(price_cents)) AS average_price_cents
        FROM products
        WHERE is_active = 1
    """
    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []


def test_order_line_items_total_accepts_total_cents():
    question = (
        "What is the total value of all order line items "
        "(quantity × line-item price) across all orders? "
        "Return a single number in kopecks."
    )
    sql = """
        SELECT SUM(quantity * unit_price_cents) AS total_cents
        FROM order_items
    """
    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []


def test_reviewers_count_accepts_reviewer_count():
    question = "How many customers have submitted at least one review?"
    sql = """
        SELECT COUNT(DISTINCT customer_id) AS reviewer_count
        FROM reviews
    """
    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []


def test_supplier_average_rating_accepts_correct_output_names():
    question = "What is the average rating of products from each supplier?"

    sql = """
        SELECT
            s.name,
            ROUND(AVG(r.rating), 2) AS average_rating
        FROM suppliers AS s
        JOIN products AS p ON p.supplier_id = s.supplier_id
        JOIN reviews AS r ON r.product_id = p.product_id
        GROUP BY s.supplier_id, s.name
        ORDER BY s.name
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []






def test_june_payments_accepts_correct_query():
    question = "Which payments were successfully processed in June 2025?"

    sql = """
        SELECT payment_id, order_id, amount_cents
        FROM payments
        WHERE status = 'successful'
          AND paid_at >= '2025-06-01'
          AND paid_at < '2025-07-01'
        ORDER BY payment_id
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []


def test_monthly_orders_accepts_correct_query():
    question = "How many orders were placed in each month of 2025?"
    sql = """
        SELECT strftime('%Y-%m', ordered_at) AS month,
               COUNT(*) AS order_count
        FROM orders
        WHERE ordered_at >= '2025-01-01'
          AND ordered_at < '2026-01-01'
        GROUP BY strftime('%Y-%m', ordered_at)
        ORDER BY month
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_city_sales_rejects_missing_group_by():
    question = (
        "How many product units were purchased by customers in each city?"
    )
    sql = """
        SELECT c.city AS city,
               SUM(oi.quantity) AS units_sold
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        JOIN order_items oi ON o.order_id = oi.order_id
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("GROUP BY city" in issue for issue in result["issues"])


def test_city_sales_rejects_grouping_without_city():
    question = (
        "How many product units were purchased by customers in each city?"
    )
    sql = """
        SELECT c.city AS city,
               SUM(oi.quantity) AS units_sold
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY c.customer_id
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("GROUP BY city" in issue for issue in result["issues"])


def test_city_sales_rejects_grouping_by_city_and_customer():
    question = (
        "How many product units were purchased by customers in each city?"
    )
    sql = """
        SELECT c.city AS city,
               SUM(oi.quantity) AS units_sold
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY c.city, c.customer_id
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any("customer_id" in issue for issue in result["issues"])


def test_city_sales_accepts_grouping_by_city():
    question = (
        "How many product units were purchased by customers in each city?"
    )
    sql = """
        SELECT c.city AS city,
               SUM(oi.quantity) AS units_sold
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY c.city
        ORDER BY units_sold DESC
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_customer_without_delivered_orders_rejects_inverted_not_in():
    question = (
        "How many customers have at least one cancelled order "
        "but no delivered orders?"
    )

    sql = """
        WITH cancelled_orders AS (
            SELECT customer_id
            FROM orders
            WHERE status = 'cancelled'
        ),
        no_delivered_orders AS (
            SELECT customer_id
            FROM orders
            WHERE NOT EXISTS (
                SELECT 1
                FROM orders o
                WHERE o.customer_id = orders.customer_id
                  AND o.status = 'delivered'
            )
        )
        SELECT COUNT(DISTINCT c.customer_id) AS customer_count
        FROM customers c
        LEFT JOIN cancelled_orders co
            ON c.customer_id = co.customer_id
        WHERE co.customer_id IS NOT NULL
          AND c.customer_id NOT IN (
              SELECT customer_id
              FROM no_delivered_orders
          )
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is False
    assert any(
        "delivered orders" in issue.lower()
        for issue in result["issues"]
    )

def test_customer_without_delivered_orders_with_left_join_passes():
    question = (
        "How many customers have at least one cancelled order "
        "but no delivered orders?"
    )

    sql = """
        WITH cancelled_orders AS (
            SELECT DISTINCT customer_id
            FROM orders
            WHERE status = 'cancelled'
        )
        SELECT COUNT(*) AS customer_count
        FROM customers c
        LEFT JOIN cancelled_orders co
            ON c.customer_id = co.customer_id
        WHERE co.customer_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM orders o
              WHERE o.customer_id = c.customer_id
                AND o.status = 'delivered'
          )
    """

    result = validate_sql_quality(question, sql)

    assert result["valid"] is True
    assert result["issues"] == []

def test_join_on_different_key_columns_is_reported():
    question = "For each category, show the minimum and maximum product prices."
    sql = """
        WITH active_products AS (SELECT product_id FROM products WHERE is_active = 1)
        SELECT c.category_id, MIN(p.price_cents) AS min_price_cents
        FROM categories c
        LEFT JOIN active_products a ON c.category_id = a.product_id
        LEFT JOIN products p ON a.product_id = p.product_id
        GROUP BY c.category_id
    """

    result = validate_sql_quality(question, sql)

    assert not result["valid"]
    assert any("different key columns" in issue for issue in result["issues"])


def test_join_on_matching_foreign_keys_is_not_reported():
    question = "How many orders does each customer have?"
    sql = """
        SELECT c.customer_id, COUNT(o.order_id) AS order_count
        FROM customers c
        LEFT JOIN orders o ON o.customer_id = c.customer_id
        GROUP BY c.customer_id
    """

    result = validate_sql_quality(question, sql)

    assert not any("different key columns" in issue for issue in result["issues"])

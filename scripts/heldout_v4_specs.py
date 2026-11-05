"""Question specifications for heldout_v4 (see build_heldout_v4.py).

Each spec: category, question, sql (reference), optional order_key (needed when
the question requires a row order) and optional ``wrong`` (plausible incorrect
SQL that the metric MUST reject).

Question-writing rules: state statuses and units explicitly (money is in
cents), say when a float is "rounded to two decimals", ask only for the
columns that should be returned, and mention IDs only when IDs are wanted.
"""

SPECS: list[dict] = []


def add(category, question, sql, wrong=None, order_key=None):
    spec = {"category": category, "question": question, "sql": sql}
    if wrong:
        spec["wrong"] = wrong
    if order_key:
        spec["order_key"] = order_key
    SPECS.append(spec)


# ============================== aggregation ==============================
add("aggregation",
    "How many customers live in each city? Show the city and the number of customers, only for cities with more than 10 customers.",
    "SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city HAVING COUNT(*) > 10",
    wrong=["SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city"])

add("aggregation",
    "What is the average product price in cents for each category? Show the category name and the average price rounded to two decimals.",
    """SELECT c.name AS category_name, ROUND(AVG(p.price_cents), 2) AS avg_price_cents
       FROM categories c JOIN products p ON p.category_id = c.category_id
       GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, ROUND(AVG(oi.unit_price_cents), 2) AS avg_price_cents
              FROM categories c JOIN products p ON p.category_id = c.category_id
              JOIN order_items oi ON oi.product_id = p.product_id GROUP BY c.category_id, c.name"""])

add("aggregation",
    "How many orders were placed in each calendar year? Show the year as a four-digit text value and the number of orders.",
    "SELECT strftime('%Y', ordered_at) AS order_year, COUNT(*) AS order_count FROM orders GROUP BY strftime('%Y', ordered_at)",
    wrong=["""SELECT strftime('%Y', o.ordered_at) AS order_year, COUNT(*) AS order_count FROM orders o
              JOIN order_items oi ON oi.order_id = o.order_id GROUP BY strftime('%Y', o.ordered_at)"""])

add("aggregation",
    "How many units were sold in total in orders with status 'delivered'? Count item quantities. Show a single value named units_sold.",
    """SELECT SUM(oi.quantity) AS units_sold FROM order_items oi
       JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 'delivered'""",
    wrong=["""SELECT COUNT(*) AS units_sold FROM order_items oi
              JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 'delivered'"""])

add("aggregation",
    "For each supplier country, how many products do the suppliers from that country provide? Show the country and the number of products.",
    """SELECT s.country, COUNT(p.product_id) AS product_count FROM suppliers s
       JOIN products p ON p.supplier_id = s.supplier_id GROUP BY s.country""",
    wrong=["""SELECT s.country, COUNT(DISTINCT s.supplier_id) AS product_count FROM suppliers s
              JOIN products p ON p.supplier_id = s.supplier_id GROUP BY s.country"""])

add("aggregation",
    "What are the maximum and the minimum product price in cents within the category 'Audio'? Show max_price_cents and min_price_cents.",
    """SELECT MAX(p.price_cents) AS max_price_cents, MIN(p.price_cents) AS min_price_cents
       FROM products p JOIN categories c ON c.category_id = p.category_id WHERE c.name = 'Audio'""",
    wrong=["SELECT MAX(price_cents) AS max_price_cents, MIN(price_cents) AS min_price_cents FROM products"])

add("aggregation",
    "How many different customers have placed at least one order? Show the number as customer_count.",
    "SELECT COUNT(DISTINCT customer_id) AS customer_count FROM orders",
    wrong=["SELECT COUNT(*) AS customer_count FROM orders"])

add("aggregation",
    "What is the total amount in cents of all payments with status 'successful'? Show the value as total_successful_cents.",
    "SELECT SUM(amount_cents) AS total_successful_cents FROM payments WHERE status = 'successful'",
    wrong=["SELECT SUM(amount_cents) AS total_successful_cents FROM payments"])

add("aggregation",
    "Which carrier has handled the largest number of shipments in total? Show the carrier and its number of shipments.",
    "SELECT carrier, COUNT(*) AS shipment_count FROM shipments GROUP BY carrier ORDER BY shipment_count DESC LIMIT 1",
    order_key=["carrier"],
    wrong=["SELECT carrier, COUNT(*) AS shipment_count FROM shipments GROUP BY carrier ORDER BY shipment_count ASC LIMIT 1"])

add("aggregation",
    "What is the average review rating across all reviews, rounded to two decimals? Show the value as avg_rating.",
    "SELECT ROUND(AVG(rating), 2) AS avg_rating FROM reviews",
    wrong=["""SELECT ROUND(AVG(product_avg), 2) AS avg_rating
              FROM (SELECT AVG(rating) AS product_avg FROM reviews GROUP BY product_id)"""])

add("aggregation",
    "How many reviews has each rating value received? Show the rating and the number of reviews.",
    "SELECT rating, COUNT(*) AS review_count FROM reviews GROUP BY rating",
    wrong=["SELECT rating, COUNT(DISTINCT product_id) AS review_count FROM reviews GROUP BY rating"])

add("aggregation",
    "What is the total discount in cents given on orders that used a coupon? Show the value as total_discount_cents.",
    """SELECT SUM(o.discount_cents) AS total_discount_cents FROM orders o
       WHERE o.coupon_id IS NOT NULL""",
    wrong=["""SELECT SUM(o.discount_cents * c.discount_percent / 100) AS total_discount_cents
              FROM orders o JOIN coupons c ON c.coupon_id = o.coupon_id"""])

# ============================== filtering ==============================
add("filtering",
    "Which products are inactive? Show the product name and its price in cents.",
    "SELECT name, price_cents FROM products WHERE is_active = 0",
    wrong=["SELECT name, price_cents FROM products WHERE stock_quantity = 0"])

add("filtering",
    "Which products in the category 'Monitors' cost more than 100000 cents? Show the product name and the price in cents.",
    """SELECT p.name, p.price_cents FROM products p JOIN categories c ON c.category_id = p.category_id
       WHERE c.name = 'Monitors' AND p.price_cents > 100000""",
    wrong=["SELECT name, price_cents FROM products WHERE price_cents > 100000"])

add("filtering",
    "Which orders were placed in March 2026? Show the order IDs and their statuses.",
    "SELECT order_id, status FROM orders WHERE ordered_at >= '2026-03-01' AND ordered_at < '2026-04-01'",
    wrong=["SELECT order_id, status FROM orders WHERE strftime('%m', ordered_at) = '03'"])

add("filtering",
    "Which customers registered in 2024 and live in 'Lviv' or 'Kyiv'? Show their IDs and full names.",
    """SELECT customer_id, full_name FROM customers
       WHERE registered_at >= '2024-01-01' AND registered_at < '2025-01-01' AND city IN ('Lviv', 'Kyiv')""",
    wrong=["SELECT customer_id, full_name FROM customers WHERE city IN ('Lviv', 'Kyiv')"])

add("filtering",
    "Which coupons are marked as inactive? Show the coupon code and the discount percentage.",
    "SELECT code, discount_percent FROM coupons WHERE is_active = 0")

add("filtering",
    "Which products have between 30 and 35 units in stock, both limits included? Show the product name and the stock quantity.",
    "SELECT name, stock_quantity FROM products WHERE stock_quantity BETWEEN 30 AND 35",
    wrong=["SELECT name, stock_quantity FROM products WHERE stock_quantity > 30 AND stock_quantity < 35"])

add("filtering",
    "Which payments with status 'failed' were for more than 500000 cents? Show the payment IDs and the amounts in cents.",
    "SELECT payment_id, amount_cents FROM payments WHERE status = 'failed' AND amount_cents > 500000",
    wrong=["SELECT payment_id, amount_cents FROM payments WHERE amount_cents > 500000"])

add("filtering",
    "Which suppliers are located in 'Poland' or 'Germany'? Show the supplier name and the country.",
    "SELECT name, country FROM suppliers WHERE country IN ('Poland', 'Germany')")

# ============================== sorting / top-N ==============================
add("sorting",
    "Show the five most expensive products, sorted by price in descending order. Show the product name and the price in cents.",
    "SELECT name, price_cents FROM products ORDER BY price_cents DESC, product_id LIMIT 5",
    order_key=["name"],
    wrong=["SELECT name, price_cents FROM products ORDER BY price_cents ASC, product_id LIMIT 5"])

add("sorting",
    "Show the three customers who registered first, sorted by registration date from the earliest. Show the full name and the registration date.",
    "SELECT full_name, registered_at FROM customers ORDER BY registered_at, customer_id LIMIT 3",
    order_key=["full_name"],
    wrong=["SELECT full_name, registered_at FROM customers ORDER BY registered_at DESC, customer_id LIMIT 3"])

add("sorting",
    "Show the five orders with the largest discount in cents, sorted by the discount in descending order. Show the order ID and the discount in cents.",
    "SELECT order_id, discount_cents FROM orders ORDER BY discount_cents DESC, order_id LIMIT 5",
    order_key=["order_id"])

add("sorting",
    "List all suppliers sorted alphabetically by name. Show only the supplier name.",
    "SELECT name FROM suppliers ORDER BY name",
    order_key=["name"])


# ============================== joins ==============================
add("joins",
    "Which products in the category 'Smartphones' have received at least one review with a rating of 5? Show each product name once.",
    """SELECT DISTINCT p.name FROM products p
       JOIN categories c ON c.category_id = p.category_id
       JOIN reviews r ON r.product_id = p.product_id
       WHERE c.name = 'Smartphones' AND r.rating = 5""",
    wrong=["""SELECT p.name FROM products p
              JOIN categories c ON c.category_id = p.category_id
              JOIN reviews r ON r.product_id = p.product_id
              WHERE c.name = 'Smartphones' AND r.rating = 5"""])

add("joins",
    "Show the product name and the supplier name for every product that costs more than 220000 cents.",
    """SELECT p.name AS product_name, s.name AS supplier_name FROM products p
       JOIN suppliers s ON s.supplier_id = p.supplier_id WHERE p.price_cents > 220000""",
    wrong=["""SELECT p.name AS product_name, s.name AS supplier_name FROM products p
              JOIN suppliers s ON s.supplier_id = p.product_id WHERE p.price_cents > 220000"""])

add("joins",
    "Which customers have written at least one review for a product in the category 'Laptops'? Show each customer's full name once.",
    """SELECT DISTINCT cu.full_name FROM customers cu
       JOIN reviews r ON r.customer_id = cu.customer_id
       JOIN products p ON p.product_id = r.product_id
       JOIN categories c ON c.category_id = p.category_id WHERE c.name = 'Laptops'""",
    wrong=["""SELECT cu.full_name FROM customers cu
              JOIN reviews r ON r.customer_id = cu.customer_id
              JOIN products p ON p.product_id = r.product_id
              JOIN categories c ON c.category_id = p.category_id WHERE c.name = 'Laptops'"""])

add("joins",
    "For orders with status 'returned', show the order ID, the customer's full name and the order date.",
    """SELECT o.order_id, cu.full_name, o.ordered_at FROM orders o
       JOIN customers cu ON cu.customer_id = o.customer_id WHERE o.status = 'returned'""",
    wrong=["""SELECT o.order_id, cu.full_name, o.ordered_at FROM orders o
              JOIN customers cu ON cu.customer_id = o.customer_id WHERE o.status = 'cancelled'"""])

add("joins",
    "Which orders have a payment with status 'refunded'? Show the order ID and the payment amount in cents.",
    """SELECT o.order_id, p.amount_cents FROM orders o JOIN payments p ON p.order_id = o.order_id
       WHERE p.status = 'refunded'""",
    wrong=["""SELECT o.order_id, p.amount_cents FROM orders o JOIN payments p ON p.order_id = o.order_id
              WHERE p.status = 'failed'"""])

add("joins",
    "Show the shipment ID and the customer's full name for all delivered shipments handled by the carrier 'Nova Post'.",
    """SELECT s.shipment_id, cu.full_name FROM shipments s
       JOIN orders o ON o.order_id = s.order_id
       JOIN customers cu ON cu.customer_id = o.customer_id
       WHERE s.carrier = 'Nova Post' AND s.status = 'delivered'""",
    wrong=["""SELECT s.shipment_id, cu.full_name FROM shipments s
              JOIN orders o ON o.order_id = s.order_id
              JOIN customers cu ON cu.customer_id = o.customer_id WHERE s.carrier = 'Nova Post'"""])

add("joins",
    "Which products appear in at least one order with status 'cancelled'? Show each product name once.",
    """SELECT DISTINCT p.name FROM products p
       JOIN order_items oi ON oi.product_id = p.product_id
       JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 'cancelled'""",
    wrong=["""SELECT DISTINCT p.name FROM products p
              JOIN order_items oi ON oi.product_id = p.product_id
              JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 'returned'"""])

add("joins",
    "Show the full name of every customer who placed at least one order with the coupon code 'SALE05'. Each customer once.",
    """SELECT DISTINCT cu.full_name FROM customers cu
       JOIN orders o ON o.customer_id = cu.customer_id
       JOIN coupons c ON c.coupon_id = o.coupon_id WHERE c.code = 'SALE05'""",
    wrong=["""SELECT DISTINCT cu.full_name FROM customers cu
              JOIN orders o ON o.customer_id = cu.customer_id
              JOIN coupons c ON c.coupon_id = o.coupon_id WHERE c.code = 'SALE06'"""])

add("joins",
    "Which suppliers provide at least one inactive product? Show each supplier name once.",
    """SELECT DISTINCT s.name FROM suppliers s JOIN products p ON p.supplier_id = s.supplier_id
       WHERE p.is_active = 0""",
    wrong=["""SELECT DISTINCT s.name FROM suppliers s JOIN products p ON p.supplier_id = s.supplier_id
              WHERE p.is_active = 1"""])

add("joins",
    "For each customer living in 'Vinnytsia', show the full name and the number of reviews they have written. Include customers with no reviews, with a count of 0.",
    """SELECT cu.full_name, COUNT(r.review_id) AS review_count FROM customers cu
       LEFT JOIN reviews r ON r.customer_id = cu.customer_id
       WHERE cu.city = 'Vinnytsia' GROUP BY cu.customer_id, cu.full_name""",
    wrong=["""SELECT cu.full_name, COUNT(r.review_id) AS review_count FROM customers cu
              JOIN reviews r ON r.customer_id = cu.customer_id
              WHERE cu.city = 'Vinnytsia' GROUP BY cu.customer_id, cu.full_name""",
           """SELECT cu.full_name, COUNT(*) AS review_count FROM customers cu
              LEFT JOIN reviews r ON r.customer_id = cu.customer_id
              WHERE cu.city = 'Vinnytsia' GROUP BY cu.customer_id, cu.full_name"""])

add("joins",
    "For each category, show the category name and the number of its products that have never been ordered. Include categories where this number is 0.",
    """SELECT c.name AS category_name, COUNT(p.product_id) AS never_ordered_products FROM categories c
       LEFT JOIN products p ON p.category_id = c.category_id
            AND NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id)
       GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, COUNT(p.product_id) AS never_ordered_products FROM categories c
              JOIN products p ON p.category_id = c.category_id
              WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id = p.product_id)
              GROUP BY c.category_id, c.name"""])

add("joins",
    "Which orders have more than one payment record? Show the order ID and the total of all its payments in cents.",
    """SELECT order_id, SUM(amount_cents) AS total_paid_cents FROM payments
       GROUP BY order_id HAVING COUNT(*) > 1""",
    wrong=["SELECT order_id, SUM(amount_cents) AS total_paid_cents FROM payments GROUP BY order_id"])

add("joins",
    "Which customers placed at least one order that used a coupon with a 20 percent discount? Show each customer's full name once.",
    """SELECT DISTINCT cu.full_name FROM customers cu
       JOIN orders o ON o.customer_id = cu.customer_id
       JOIN coupons c ON c.coupon_id = o.coupon_id WHERE c.discount_percent = 20""",
    wrong=["""SELECT DISTINCT cu.full_name FROM customers cu
              JOIN orders o ON o.customer_id = cu.customer_id
              JOIN coupons c ON c.coupon_id = o.coupon_id WHERE c.discount_percent = 10"""])

# ============================== subqueries ==============================
add("subqueries",
    "Which products cost more than the average price of the products from the same supplier? Show the product name and the price in cents.",
    """SELECT p.name, p.price_cents FROM products p
       WHERE p.price_cents > (SELECT AVG(p2.price_cents) FROM products p2 WHERE p2.supplier_id = p.supplier_id)""",
    wrong=["SELECT name, price_cents FROM products WHERE price_cents > (SELECT AVG(price_cents) FROM products)"])

add("subqueries",
    "Which products have more units in stock than the average stock quantity of the products in their own category? Show the product name and the stock quantity.",
    """SELECT p.name, p.stock_quantity FROM products p
       WHERE p.stock_quantity > (SELECT AVG(p2.stock_quantity) FROM products p2 WHERE p2.category_id = p.category_id)""",
    wrong=["SELECT name, stock_quantity FROM products WHERE stock_quantity > (SELECT AVG(stock_quantity) FROM products)"])

add("subqueries",
    "Which customers have placed at least one order that ended with status 'returned'? Show each customer's full name once.",
    """SELECT full_name FROM customers
       WHERE customer_id IN (SELECT customer_id FROM orders WHERE status = 'returned')""",
    wrong=["""SELECT full_name FROM customers
              WHERE customer_id IN (SELECT customer_id FROM orders WHERE status = 'cancelled')"""])

add("subqueries",
    "For each category, show the product with the maximum price: the category name, the product name and the price in cents.",
    """SELECT c.name AS category_name, p.name AS product_name, p.price_cents FROM products p
       JOIN categories c ON c.category_id = p.category_id
       WHERE p.price_cents = (SELECT MAX(p2.price_cents) FROM products p2 WHERE p2.category_id = p.category_id)""",
    wrong=["""SELECT c.name AS category_name, p.name AS product_name, p.price_cents FROM products p
              JOIN categories c ON c.category_id = p.category_id
              WHERE p.price_cents = (SELECT MAX(price_cents) FROM products)"""])

add("subqueries",
    "Which categories have an average product price above the average price of all products? Show the category name.",
    """SELECT c.name FROM categories c JOIN products p ON p.category_id = c.category_id
       GROUP BY c.category_id, c.name
       HAVING AVG(p.price_cents) > (SELECT AVG(price_cents) FROM products)""",
    wrong=["""SELECT c.name FROM categories c JOIN products p ON p.category_id = c.category_id
              GROUP BY c.category_id, c.name
              HAVING AVG(p.price_cents) > (SELECT MAX(price_cents) / 2 FROM products)"""])

add("subqueries",
    "Which suppliers provide more products than the average number of products per supplier? Show the supplier name and its number of products.",
    """SELECT s.name, COUNT(*) AS product_count FROM suppliers s JOIN products p ON p.supplier_id = s.supplier_id
       GROUP BY s.supplier_id, s.name
       HAVING COUNT(*) > (SELECT 1.0 * COUNT(*) / COUNT(DISTINCT supplier_id) FROM products)""",
    wrong=["""SELECT s.name, COUNT(*) AS product_count FROM suppliers s JOIN products p ON p.supplier_id = s.supplier_id
              GROUP BY s.supplier_id, s.name HAVING COUNT(*) >= 6"""])

add("subqueries",
    "Which orders with status 'returned' consist of exactly four order item rows? Show the order ID.",
    """SELECT order_id FROM orders WHERE status = 'returned'
       AND order_id IN (SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(*) = 4)""",
    wrong=["""SELECT order_id FROM orders WHERE status = 'returned'
              AND order_id IN (SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(*) >= 3)"""])

add("subqueries",
    "Which customers have an average review rating above the average rating of all reviews? Show the customer's full name and their average rating rounded to two decimals.",
    """SELECT cu.full_name, ROUND(AVG(r.rating), 2) AS avg_rating FROM customers cu
       JOIN reviews r ON r.customer_id = cu.customer_id GROUP BY cu.customer_id, cu.full_name
       HAVING AVG(r.rating) > (SELECT AVG(rating) FROM reviews)""",
    wrong=["""SELECT cu.full_name, ROUND(AVG(r.rating), 2) AS avg_rating FROM customers cu
              JOIN reviews r ON r.customer_id = cu.customer_id GROUP BY cu.customer_id, cu.full_name
              HAVING AVG(r.rating) >= 4"""])

add("subqueries",
    "What is the average number of products per supplier, rounded to two decimals? Show the value as avg_products_per_supplier.",
    """SELECT ROUND(AVG(cnt), 2) AS avg_products_per_supplier
       FROM (SELECT COUNT(*) AS cnt FROM products GROUP BY supplier_id)""",
    wrong=["SELECT ROUND(1.0 * COUNT(*) / COUNT(DISTINCT category_id), 2) AS avg_products_per_supplier FROM products"])

add("subqueries",
    "What is the largest number of orders placed by a single customer? Show the value as max_orders.",
    "SELECT MAX(cnt) AS max_orders FROM (SELECT COUNT(*) AS cnt FROM orders GROUP BY customer_id)",
    wrong=["SELECT COUNT(*) AS max_orders FROM orders"])

add("subqueries",
    "Which products cost more than every product in the category 'Accessories'? Show the product name and the price in cents.",
    """SELECT name, price_cents FROM products
       WHERE price_cents > (SELECT MAX(p.price_cents) FROM products p
                            JOIN categories c ON c.category_id = p.category_id WHERE c.name = 'Accessories')""",
    wrong=["""SELECT name, price_cents FROM products
              WHERE price_cents > (SELECT MIN(p.price_cents) FROM products p
                                   JOIN categories c ON c.category_id = p.category_id WHERE c.name = 'Accessories')"""])

add("subqueries",
    "Which customers have placed orders only in 2026, with no order dated before 2026? Show the customer's full name.",
    """SELECT cu.full_name FROM customers cu JOIN orders o ON o.customer_id = cu.customer_id
       GROUP BY cu.customer_id, cu.full_name HAVING MIN(o.ordered_at) >= '2026-01-01'""",
    wrong=["""SELECT DISTINCT cu.full_name FROM customers cu JOIN orders o ON o.customer_id = cu.customer_id
              WHERE o.ordered_at >= '2026-01-01'"""])

add("subqueries",
    "Which products have an average review rating higher than the average review rating of their own category? Show the product name and its average rating rounded to two decimals.",
    """SELECT p.name, ROUND(AVG(r.rating), 2) AS avg_rating FROM products p
       JOIN reviews r ON r.product_id = p.product_id GROUP BY p.product_id, p.name
       HAVING AVG(r.rating) > (SELECT AVG(r2.rating) FROM reviews r2
                               JOIN products p2 ON p2.product_id = r2.product_id
                               WHERE p2.category_id = p.category_id)""",
    wrong=["""SELECT p.name, ROUND(AVG(r.rating), 2) AS avg_rating FROM products p
              JOIN reviews r ON r.product_id = p.product_id GROUP BY p.product_id, p.name
              HAVING AVG(r.rating) > (SELECT AVG(rating) FROM reviews)"""])


# ============================== multi-table aggregation ==============================
add("multi_table_aggregation",
    "For each customer city, show the city and the total value in cents of the items in its customers' delivered orders (quantity times unit price).",
    """SELECT cu.city, SUM(oi.quantity * oi.unit_price_cents) AS delivered_value_cents FROM customers cu
       JOIN orders o ON o.customer_id = cu.customer_id
       JOIN order_items oi ON oi.order_id = o.order_id
       WHERE o.status = 'delivered' GROUP BY cu.city""",
    wrong=["""SELECT cu.city, SUM(oi.unit_price_cents) AS delivered_value_cents FROM customers cu
              JOIN orders o ON o.customer_id = cu.customer_id
              JOIN order_items oi ON oi.order_id = o.order_id
              WHERE o.status = 'delivered' GROUP BY cu.city"""])

add("multi_table_aggregation",
    "For each product category, show the category name and the number of units sold in orders with status 'delivered'.",
    """SELECT c.name AS category_name, SUM(oi.quantity) AS units_sold FROM categories c
       JOIN products p ON p.category_id = c.category_id
       JOIN order_items oi ON oi.product_id = p.product_id
       JOIN orders o ON o.order_id = oi.order_id
       WHERE o.status = 'delivered' GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, COUNT(*) AS units_sold FROM categories c
              JOIN products p ON p.category_id = c.category_id
              JOIN order_items oi ON oi.product_id = p.product_id
              JOIN orders o ON o.order_id = oi.order_id
              WHERE o.status = 'delivered' GROUP BY c.category_id, c.name"""])

add("multi_table_aggregation",
    "For each supplier, show the supplier name and the revenue in cents from its products in orders with status 'delivered' (quantity times unit price).",
    """SELECT s.name AS supplier_name, SUM(oi.quantity * oi.unit_price_cents) AS revenue_cents FROM suppliers s
       JOIN products p ON p.supplier_id = s.supplier_id
       JOIN order_items oi ON oi.product_id = p.product_id
       JOIN orders o ON o.order_id = oi.order_id
       WHERE o.status = 'delivered' GROUP BY s.supplier_id, s.name""",
    wrong=["""SELECT s.name AS supplier_name, SUM(oi.quantity * oi.unit_price_cents) AS revenue_cents FROM suppliers s
              JOIN products p ON p.supplier_id = s.supplier_id
              JOIN order_items oi ON oi.product_id = p.product_id
              GROUP BY s.supplier_id, s.name"""])

add("multi_table_aggregation",
    "For each shipping carrier, what is the average order value in cents? Compute each order's value as the sum of quantity times unit price over its items, then average these values over the carrier's orders. Show the average rounded to two decimals.",
    """SELECT s.carrier, ROUND(AVG(t.order_value), 2) AS avg_order_value_cents FROM shipments s
       JOIN (SELECT order_id, SUM(quantity * unit_price_cents) AS order_value FROM order_items GROUP BY order_id) t
         ON t.order_id = s.order_id GROUP BY s.carrier""",
    wrong=["""SELECT s.carrier, ROUND(AVG(oi.quantity * oi.unit_price_cents), 2) AS avg_order_value_cents FROM shipments s
              JOIN order_items oi ON oi.order_id = s.order_id GROUP BY s.carrier"""])

add("multi_table_aggregation",
    "For each customer city, how many different customers have placed at least one order? Show the city and that number.",
    """SELECT cu.city, COUNT(DISTINCT cu.customer_id) AS ordering_customers FROM customers cu
       JOIN orders o ON o.customer_id = cu.customer_id GROUP BY cu.city""",
    wrong=["""SELECT cu.city, COUNT(*) AS ordering_customers FROM customers cu
              JOIN orders o ON o.customer_id = cu.customer_id GROUP BY cu.city"""])

add("multi_table_aggregation",
    "For each product category, how many different customers have ordered at least one of its products? Show the category name and that number.",
    """SELECT c.name AS category_name, COUNT(DISTINCT o.customer_id) AS customer_count FROM categories c
       JOIN products p ON p.category_id = c.category_id
       JOIN order_items oi ON oi.product_id = p.product_id
       JOIN orders o ON o.order_id = oi.order_id GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, COUNT(o.customer_id) AS customer_count FROM categories c
              JOIN products p ON p.category_id = c.category_id
              JOIN order_items oi ON oi.product_id = p.product_id
              JOIN orders o ON o.order_id = oi.order_id GROUP BY c.category_id, c.name"""])

add("multi_table_aggregation",
    "For each supplier, show the supplier name and the number of reviews that its products have received.",
    """SELECT s.name AS supplier_name, COUNT(r.review_id) AS review_count FROM suppliers s
       JOIN products p ON p.supplier_id = s.supplier_id
       JOIN reviews r ON r.product_id = p.product_id GROUP BY s.supplier_id, s.name""",
    wrong=["""SELECT s.name AS supplier_name, COUNT(DISTINCT p.product_id) AS review_count FROM suppliers s
              JOIN products p ON p.supplier_id = s.supplier_id
              JOIN reviews r ON r.product_id = p.product_id GROUP BY s.supplier_id, s.name"""])

add("multi_table_aggregation",
    "For each coupon that was used in at least five orders, show the coupon code and the total discount in cents given through it.",
    """SELECT c.code, SUM(o.discount_cents) AS total_discount_cents FROM coupons c
       JOIN orders o ON o.coupon_id = c.coupon_id GROUP BY c.coupon_id, c.code HAVING COUNT(*) >= 5""",
    wrong=["""SELECT c.code, SUM(o.discount_cents) AS total_discount_cents FROM coupons c
              JOIN orders o ON o.coupon_id = c.coupon_id GROUP BY c.coupon_id, c.code"""])

add("multi_table_aggregation",
    "For each customer city, show the city and the total amount in cents of payments with status 'successful' for its customers' orders.",
    """SELECT cu.city, SUM(p.amount_cents) AS successful_cents FROM customers cu
       JOIN orders o ON o.customer_id = cu.customer_id
       JOIN payments p ON p.order_id = o.order_id
       WHERE p.status = 'successful' GROUP BY cu.city""",
    wrong=["""SELECT cu.city, SUM(p.amount_cents) AS successful_cents FROM customers cu
              JOIN orders o ON o.customer_id = cu.customer_id
              JOIN payments p ON p.order_id = o.order_id GROUP BY cu.city"""])

add("multi_table_aggregation",
    "For each payment status, how many different orders have at least one payment with that status? Show the status and the number of orders.",
    "SELECT status, COUNT(DISTINCT order_id) AS order_count FROM payments GROUP BY status",
    wrong=["SELECT status, COUNT(*) AS order_count FROM payments GROUP BY status"])

add("multi_table_aggregation",
    "For each product category, show the category name and the number of order item rows that belong to orders with status 'cancelled'.",
    """SELECT c.name AS category_name, COUNT(*) AS cancelled_item_rows FROM categories c
       JOIN products p ON p.category_id = c.category_id
       JOIN order_items oi ON oi.product_id = p.product_id
       JOIN orders o ON o.order_id = oi.order_id
       WHERE o.status = 'cancelled' GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, COUNT(*) AS cancelled_item_rows FROM categories c
              JOIN products p ON p.category_id = c.category_id
              JOIN order_items oi ON oi.product_id = p.product_id
              JOIN orders o ON o.order_id = oi.order_id
              WHERE o.status = 'delivered' GROUP BY c.category_id, c.name"""])

add("multi_table_aggregation",
    "For each shipping carrier, how many different customers have had a shipment handled by it? Show the carrier and that number.",
    """SELECT s.carrier, COUNT(DISTINCT o.customer_id) AS customer_count FROM shipments s
       JOIN orders o ON o.order_id = s.order_id GROUP BY s.carrier""",
    wrong=["""SELECT s.carrier, COUNT(o.customer_id) AS customer_count FROM shipments s
              JOIN orders o ON o.order_id = s.order_id GROUP BY s.carrier"""])

add("multi_table_aggregation",
    "Which three customers have spent the most on delivered orders, counting quantity times unit price of the items? Show the customer's full name and the total in cents, sorted by the total in descending order.",
    """SELECT cu.full_name, SUM(oi.quantity * oi.unit_price_cents) AS total_cents FROM customers cu
       JOIN orders o ON o.customer_id = cu.customer_id
       JOIN order_items oi ON oi.order_id = o.order_id
       WHERE o.status = 'delivered' GROUP BY cu.customer_id, cu.full_name
       ORDER BY total_cents DESC, cu.customer_id LIMIT 3""",
    order_key=["full_name"],
    wrong=["""SELECT cu.full_name, SUM(oi.quantity * oi.unit_price_cents) AS total_cents FROM customers cu
              JOIN orders o ON o.customer_id = cu.customer_id
              JOIN order_items oi ON oi.order_id = o.order_id
              GROUP BY cu.customer_id, cu.full_name
              ORDER BY total_cents DESC, cu.customer_id LIMIT 3"""])

add("multi_table_aggregation",
    "For each supplier, show the supplier name and the average rating of all reviews of its products, rounded to two decimals.",
    """SELECT s.name AS supplier_name, ROUND(AVG(r.rating), 2) AS avg_rating FROM suppliers s
       JOIN products p ON p.supplier_id = s.supplier_id
       JOIN reviews r ON r.product_id = p.product_id GROUP BY s.supplier_id, s.name""",
    wrong=["""SELECT supplier_name, ROUND(AVG(product_avg), 2) AS avg_rating FROM
              (SELECT s.name AS supplier_name, AVG(r.rating) AS product_avg FROM suppliers s
               JOIN products p ON p.supplier_id = s.supplier_id
               JOIN reviews r ON r.product_id = p.product_id GROUP BY s.supplier_id, s.name, p.product_id)
              GROUP BY supplier_name"""])

add("multi_table_aggregation",
    "For each order status, show the status and the total number of units, counting item quantities, in orders with that status.",
    """SELECT o.status, SUM(oi.quantity) AS total_units FROM orders o
       JOIN order_items oi ON oi.order_id = o.order_id GROUP BY o.status""",
    wrong=["""SELECT o.status, COUNT(*) AS total_units FROM orders o
              JOIN order_items oi ON oi.order_id = o.order_id GROUP BY o.status"""])

add("multi_table_aggregation",
    "For each customer city, show the city and the number of reviews written by its customers.",
    """SELECT cu.city, COUNT(r.review_id) AS review_count FROM customers cu
       JOIN reviews r ON r.customer_id = cu.customer_id GROUP BY cu.city""",
    wrong=["""SELECT cu.city, COUNT(DISTINCT cu.customer_id) AS review_count FROM customers cu
              JOIN reviews r ON r.customer_id = cu.customer_id GROUP BY cu.city"""])

add("multi_table_aggregation",
    "For each product category, show the category name and the number of different suppliers that provide at least one product in it.",
    """SELECT c.name AS category_name, COUNT(DISTINCT p.supplier_id) AS supplier_count FROM categories c
       JOIN products p ON p.category_id = c.category_id GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, COUNT(p.supplier_id) AS supplier_count FROM categories c
              JOIN products p ON p.category_id = c.category_id GROUP BY c.category_id, c.name"""])

# ============================== date aggregation ==============================
add("date_aggregation",
    "How many orders did customers from 'Lviv' place in each month of 2025? Show the month in the format YYYY-MM and the number of orders.",
    """SELECT strftime('%Y-%m', o.ordered_at) AS order_month, COUNT(*) AS order_count FROM orders o
       JOIN customers cu ON cu.customer_id = o.customer_id
       WHERE cu.city = 'Lviv' AND o.ordered_at >= '2025-01-01' AND o.ordered_at < '2026-01-01'
       GROUP BY strftime('%Y-%m', o.ordered_at)""",
    wrong=["""SELECT strftime('%Y-%m', ordered_at) AS order_month, COUNT(*) AS order_count FROM orders
              WHERE ordered_at >= '2025-01-01' AND ordered_at < '2026-01-01' GROUP BY strftime('%Y-%m', ordered_at)"""])

add("date_aggregation",
    "What was the total value in cents of order items for orders placed in each quarter of 2026? Show the quarter number from 1 to 4 and the total.",
    """SELECT (CAST(strftime('%m', o.ordered_at) AS INTEGER) + 2) / 3 AS quarter_number,
              SUM(oi.quantity * oi.unit_price_cents) AS total_cents
       FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
       WHERE o.ordered_at >= '2026-01-01' AND o.ordered_at < '2027-01-01'
       GROUP BY (CAST(strftime('%m', o.ordered_at) AS INTEGER) + 2) / 3""",
    wrong=["""SELECT (CAST(strftime('%m', o.ordered_at) AS INTEGER) + 2) / 3 AS quarter_number,
                     SUM(oi.quantity * oi.unit_price_cents) AS total_cents
              FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
              GROUP BY (CAST(strftime('%m', o.ordered_at) AS INTEGER) + 2) / 3"""])

add("date_aggregation",
    "How many customers registered in each month of 2024? Show the month in the format YYYY-MM and the number of customers.",
    """SELECT strftime('%Y-%m', registered_at) AS registration_month, COUNT(*) AS customer_count FROM customers
       WHERE registered_at >= '2024-01-01' AND registered_at < '2025-01-01'
       GROUP BY strftime('%Y-%m', registered_at)""",
    wrong=["""SELECT strftime('%m', registered_at) AS registration_month, COUNT(*) AS customer_count FROM customers
              GROUP BY strftime('%m', registered_at)"""])

add("date_aggregation",
    "How many shipments were shipped in each month of 2026, based on the shipped date? Show the month in the format YYYY-MM and the number of shipments.",
    """SELECT strftime('%Y-%m', shipped_at) AS shipped_month, COUNT(*) AS shipment_count FROM shipments
       WHERE shipped_at >= '2026-01-01' AND shipped_at < '2027-01-01' GROUP BY strftime('%Y-%m', shipped_at)""",
    wrong=["""SELECT strftime('%Y-%m', shipped_at) AS shipped_month, COUNT(*) AS shipment_count FROM shipments
              GROUP BY strftime('%Y-%m', shipped_at)"""])

add("date_aggregation",
    "How many reviews were created in each year? Show the year and the number of reviews.",
    "SELECT strftime('%Y', created_at) AS review_year, COUNT(*) AS review_count FROM reviews GROUP BY strftime('%Y', created_at)",
    wrong=["SELECT strftime('%Y', created_at) AS review_year, COUNT(DISTINCT product_id) AS review_count FROM reviews GROUP BY strftime('%Y', created_at)"])

add("date_aggregation",
    "In which month of 2025 were the most orders placed? Show the month in the format YYYY-MM and the number of orders.",
    """SELECT strftime('%Y-%m', ordered_at) AS order_month, COUNT(*) AS order_count FROM orders
       WHERE ordered_at >= '2025-01-01' AND ordered_at < '2026-01-01'
       GROUP BY strftime('%Y-%m', ordered_at) ORDER BY order_count DESC, order_month LIMIT 1""",
    order_key=["order_month"],
    wrong=["""SELECT strftime('%Y-%m', ordered_at) AS order_month, COUNT(*) AS order_count FROM orders
              WHERE ordered_at >= '2025-01-01' AND ordered_at < '2026-01-01'
              GROUP BY strftime('%Y-%m', ordered_at) ORDER BY order_count ASC, order_month LIMIT 1"""])

add("date_aggregation",
    "How many orders were placed on each day of the week? Show the weekday number from 0 (Sunday) to 6 (Saturday) and the number of orders.",
    "SELECT CAST(strftime('%w', ordered_at) AS INTEGER) AS weekday, COUNT(*) AS order_count FROM orders GROUP BY CAST(strftime('%w', ordered_at) AS INTEGER)",
    wrong=["SELECT CAST(strftime('%w', ordered_at) AS INTEGER) AS weekday, COUNT(DISTINCT customer_id) AS order_count FROM orders GROUP BY CAST(strftime('%w', ordered_at) AS INTEGER)"])

add("date_aggregation",
    "What is the total amount in cents of successful payments made in each month of 2026, based on the payment date? Show the month in the format YYYY-MM and the total.",
    """SELECT strftime('%Y-%m', paid_at) AS payment_month, SUM(amount_cents) AS total_cents FROM payments
       WHERE status = 'successful' AND paid_at >= '2026-01-01' AND paid_at < '2027-01-01'
       GROUP BY strftime('%Y-%m', paid_at)""",
    wrong=["""SELECT strftime('%Y-%m', paid_at) AS payment_month, SUM(amount_cents) AS total_cents FROM payments
              WHERE paid_at >= '2026-01-01' AND paid_at < '2027-01-01' GROUP BY strftime('%Y-%m', paid_at)"""])

add("date_aggregation",
    "How many coupons are valid on the date 2025-07-15, meaning that valid_from is on or before that date and valid_until is on or after it? Show the number as valid_coupons.",
    "SELECT COUNT(*) AS valid_coupons FROM coupons WHERE valid_from <= '2025-07-15' AND valid_until >= '2025-07-15'",
    wrong=["SELECT COUNT(*) AS valid_coupons FROM coupons WHERE valid_from <= '2025-07-15'"])

add("date_aggregation",
    "How many orders were placed in the first half of 2026 (January to June) and how many in the second half (July to December)? Show the half as 1 or 2 and the number of orders.",
    """SELECT CASE WHEN CAST(strftime('%m', ordered_at) AS INTEGER) <= 6 THEN 1 ELSE 2 END AS half_year, COUNT(*) AS order_count
       FROM orders WHERE ordered_at >= '2026-01-01' AND ordered_at < '2027-01-01'
       GROUP BY CASE WHEN CAST(strftime('%m', ordered_at) AS INTEGER) <= 6 THEN 1 ELSE 2 END""",
    wrong=["""SELECT CASE WHEN CAST(strftime('%m', ordered_at) AS INTEGER) <= 6 THEN 1 ELSE 2 END AS half_year, COUNT(*) AS order_count
              FROM orders GROUP BY CASE WHEN CAST(strftime('%m', ordered_at) AS INTEGER) <= 6 THEN 1 ELSE 2 END"""])


# ============================== negation ("never", "no") ==============================
add("negation",
    "Which products have never been reviewed? Show the product name.",
    "SELECT name FROM products WHERE product_id NOT IN (SELECT product_id FROM reviews)",
    wrong=["SELECT name FROM products WHERE product_id NOT IN (SELECT product_id FROM order_items)"])

add("negation",
    "Which customers have never placed an order? Show the customer's full name.",
    "SELECT full_name FROM customers WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = customers.customer_id)",
    wrong=["SELECT full_name FROM customers WHERE customer_id NOT IN (SELECT customer_id FROM orders WHERE status = 'delivered')"])

add("negation",
    "Which products have never been ordered? Show the product name.",
    "SELECT name FROM products WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id = products.product_id)",
    wrong=["SELECT name FROM products WHERE product_id NOT IN (SELECT product_id FROM reviews)"])

add("negation",
    "Which orders have no payment record at all? Show the order ID.",
    "SELECT o.order_id FROM orders o WHERE NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id)" ,
    wrong=["""SELECT o.order_id FROM orders o LEFT JOIN payments p ON p.order_id = o.order_id
              WHERE p.status IS NULL OR p.status <> 'successful'"""])

add("negation",
    "Which customers have placed orders, but none of their orders has the status 'delivered'? Show the customer's full name.",
    """SELECT cu.full_name FROM customers cu
       WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = cu.customer_id)
         AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = cu.customer_id AND o.status = 'delivered')""",
    wrong=["""SELECT DISTINCT cu.full_name FROM customers cu JOIN orders o ON o.customer_id = cu.customer_id
              WHERE o.status <> 'delivered'"""])

add("negation",
    "Which customers have placed at least one order but have never written a review? Show the customer's full name.",
    """SELECT cu.full_name FROM customers cu
       WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = cu.customer_id)
         AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.customer_id = cu.customer_id)""",
    wrong=["SELECT cu.full_name FROM customers cu WHERE NOT EXISTS (SELECT 1 FROM reviews r WHERE r.customer_id = cu.customer_id)"])

add("negation",
    "Which customers have placed at least one order but have never used a coupon? Show the customer's full name.",
    """SELECT cu.full_name FROM customers cu
       WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = cu.customer_id)
         AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = cu.customer_id AND o.coupon_id IS NOT NULL)""",
    wrong=["""SELECT DISTINCT cu.full_name FROM customers cu JOIN orders o ON o.customer_id = cu.customer_id
              WHERE o.coupon_id IS NULL"""])

add("negation",
    "Which orders with status 'processing' have no shipment record? Show the order ID.",
    """SELECT o.order_id FROM orders o
       WHERE o.status = 'processing' AND NOT EXISTS (SELECT 1 FROM shipments s WHERE s.order_id = o.order_id)""",
    wrong=["""SELECT o.order_id FROM orders o
              WHERE o.status = 'pending' AND NOT EXISTS (SELECT 1 FROM shipments s WHERE s.order_id = o.order_id)"""])

add("negation",
    "Which coupons have never been used in any order? Show the coupon code.",
    "SELECT code FROM coupons WHERE coupon_id NOT IN (SELECT coupon_id FROM orders WHERE coupon_id IS NOT NULL)",
    wrong=["SELECT code FROM coupons WHERE is_active = 0 AND valid_until < '2026-01-01'"])

add("negation",
    "Which suppliers have no inactive products at all? Show the supplier name.",
    """SELECT s.name FROM suppliers s
       WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.supplier_id = s.supplier_id AND p.is_active = 0)""",
    wrong=["""SELECT DISTINCT s.name FROM suppliers s JOIN products p ON p.supplier_id = s.supplier_id
              WHERE p.is_active = 1"""])

# ============================== conditional aggregation ==============================
add("conditional_aggregation",
    "For each category, show the category name, the number of active products and the number of inactive products.",
    """SELECT c.name AS category_name,
              SUM(CASE WHEN p.is_active = 1 THEN 1 ELSE 0 END) AS active_products,
              SUM(CASE WHEN p.is_active = 0 THEN 1 ELSE 0 END) AS inactive_products
       FROM categories c JOIN products p ON p.category_id = c.category_id GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, COUNT(*) AS active_products, COUNT(*) AS inactive_products
              FROM categories c JOIN products p ON p.category_id = c.category_id GROUP BY c.category_id, c.name"""])

add("conditional_aggregation",
    "For each customer city, show the city, the number of its customers' delivered orders and the number of their cancelled orders.",
    """SELECT cu.city,
              SUM(CASE WHEN o.status = 'delivered' THEN 1 ELSE 0 END) AS delivered_orders,
              SUM(CASE WHEN o.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_orders
       FROM customers cu JOIN orders o ON o.customer_id = cu.customer_id GROUP BY cu.city""",
    wrong=["""SELECT cu.city, COUNT(*) AS delivered_orders, COUNT(*) AS cancelled_orders
              FROM customers cu JOIN orders o ON o.customer_id = cu.customer_id GROUP BY cu.city"""])

add("conditional_aggregation",
    "For each shipping carrier, show the carrier, the number of delivered shipments and the number of shipments with status 'in_transit'.",
    """SELECT carrier,
              SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered_shipments,
              SUM(CASE WHEN status = 'in_transit' THEN 1 ELSE 0 END) AS in_transit_shipments
       FROM shipments GROUP BY carrier""",
    wrong=["""SELECT carrier,
                     SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered_shipments,
                     SUM(CASE WHEN status = 'shipped' THEN 1 ELSE 0 END) AS in_transit_shipments
              FROM shipments GROUP BY carrier"""])

add("conditional_aggregation",
    "For each supplier country, show the country, the number of products priced above 149000 cents and the number priced at or below 149000 cents.",
    """SELECT s.country,
              SUM(CASE WHEN p.price_cents > 149000 THEN 1 ELSE 0 END) AS expensive_products,
              SUM(CASE WHEN p.price_cents <= 149000 THEN 1 ELSE 0 END) AS other_products
       FROM suppliers s JOIN products p ON p.supplier_id = s.supplier_id GROUP BY s.country""",
    wrong=["""SELECT s.country,
                     SUM(CASE WHEN p.price_cents >= 149000 THEN 1 ELSE 0 END) AS expensive_products,
                     SUM(CASE WHEN p.price_cents < 149000 THEN 1 ELSE 0 END) AS other_products
              FROM suppliers s JOIN products p ON p.supplier_id = s.supplier_id GROUP BY s.country"""])

add("conditional_aggregation",
    "For each order status, show the status, the number of orders that used a coupon and the number of orders without a coupon.",
    """SELECT status,
              SUM(CASE WHEN coupon_id IS NOT NULL THEN 1 ELSE 0 END) AS with_coupon,
              SUM(CASE WHEN coupon_id IS NULL THEN 1 ELSE 0 END) AS without_coupon
       FROM orders GROUP BY status""",
    wrong=["""SELECT status, COUNT(coupon_id) AS with_coupon, COUNT(*) AS without_coupon FROM orders GROUP BY status"""])

add("conditional_aggregation",
    "What percentage of all orders have the status 'delivered'? Show the percentage rounded to two decimals as delivered_percent.",
    "SELECT ROUND(100.0 * SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) / COUNT(*), 2) AS delivered_percent FROM orders",
    wrong=["SELECT 100 * SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) / COUNT(*) AS delivered_percent FROM orders"])

# ============================== ranking / ratios ==============================
add("ranking",
    "For each category, which product has the largest stock quantity? Show the category name, the product name and the stock quantity. If several products share the maximum, show all of them.",
    """SELECT c.name AS category_name, p.name AS product_name, p.stock_quantity FROM products p
       JOIN categories c ON c.category_id = p.category_id
       WHERE p.stock_quantity = (SELECT MAX(p2.stock_quantity) FROM products p2 WHERE p2.category_id = p.category_id)""",
    wrong=["""SELECT c.name AS category_name, p.name AS product_name, p.stock_quantity FROM products p
              JOIN categories c ON c.category_id = p.category_id
              WHERE p.stock_quantity = (SELECT MAX(stock_quantity) FROM products)"""])

add("ranking",
    "For each customer from 'Odesa' who has placed orders, show the full name and the number of orders, sorted by the number of orders in descending order and then by full name.",
    """SELECT cu.full_name, COUNT(*) AS order_count FROM customers cu
       JOIN orders o ON o.customer_id = cu.customer_id WHERE cu.city = 'Odesa'
       GROUP BY cu.customer_id, cu.full_name ORDER BY order_count DESC, cu.full_name""",
    order_key=["full_name"],
    wrong=["""SELECT cu.full_name, COUNT(*) AS order_count FROM customers cu
              JOIN orders o ON o.customer_id = cu.customer_id WHERE cu.city = 'Odesa'
              GROUP BY cu.customer_id, cu.full_name ORDER BY order_count ASC, cu.full_name"""])

add("ranking",
    "For each category, what share of its products is active? Show the category name and the percentage rounded to two decimals as active_percent.",
    """SELECT c.name AS category_name, ROUND(100.0 * SUM(p.is_active) / COUNT(*), 2) AS active_percent
       FROM categories c JOIN products p ON p.category_id = c.category_id GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, ROUND(100.0 * SUM(p.is_active) / (SELECT COUNT(*) FROM products), 2) AS active_percent
              FROM categories c JOIN products p ON p.category_id = c.category_id GROUP BY c.category_id, c.name"""])

add("ranking",
    "For each category, show the category name and the difference in cents between the maximum and the minimum product price in it.",
    """SELECT c.name AS category_name, MAX(p.price_cents) - MIN(p.price_cents) AS price_spread_cents
       FROM categories c JOIN products p ON p.category_id = c.category_id GROUP BY c.category_id, c.name""",
    wrong=["""SELECT c.name AS category_name, MAX(p.price_cents) AS price_spread_cents
              FROM categories c JOIN products p ON p.category_id = c.category_id GROUP BY c.category_id, c.name"""])

add("filtering",
    "Which customers have an email address that starts with 'customer9'? Show the full name and the email address.",
    "SELECT full_name, email FROM customers WHERE email LIKE 'customer9%'",
    wrong=["SELECT full_name, email FROM customers WHERE email LIKE 'customer9@%'"])

add("joins",
    "For products that have at least three reviews, show the product name and the number of reviews.",
    """SELECT p.name, COUNT(*) AS review_count FROM products p JOIN reviews r ON r.product_id = p.product_id
       GROUP BY p.product_id, p.name HAVING COUNT(*) >= 3""",
    wrong=["""SELECT p.name, COUNT(*) AS review_count FROM products p JOIN reviews r ON r.product_id = p.product_id
              GROUP BY p.product_id, p.name"""])

add("aggregation",
    "What is the average quantity per order item row across all order items, rounded to two decimals? Show the value as avg_quantity.",
    "SELECT ROUND(AVG(quantity), 2) AS avg_quantity FROM order_items",
    wrong=["""SELECT ROUND(AVG(total_quantity), 2) AS avg_quantity
              FROM (SELECT SUM(quantity) AS total_quantity FROM order_items GROUP BY order_id)"""])

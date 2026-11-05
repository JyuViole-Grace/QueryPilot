
-- QueryPilot: e-commerce database schema
-- SQLite

-- Enable foreign-key enforcement.
PRAGMA foreign_keys = ON;


-- =========================================================
-- 1. Customers
-- =========================================================
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL,
    registered_at TEXT NOT NULL
        CHECK (date(registered_at) IS NOT NULL)
);


-- =========================================================
-- 2. Product categories
-- =========================================================
CREATE TABLE IF NOT EXISTS categories (
    category_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);


-- =========================================================
-- 3. Suppliers
-- =========================================================
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    country TEXT NOT NULL
);


-- =========================================================
-- 4. Products
-- =========================================================
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    supplier_id INTEGER NOT NULL,
    price_cents INTEGER NOT NULL
        CHECK (price_cents >= 0),
    stock_quantity INTEGER NOT NULL DEFAULT 0
        CHECK (stock_quantity >= 0),
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    FOREIGN KEY (category_id)
        REFERENCES categories(category_id),

    FOREIGN KEY (supplier_id)
        REFERENCES suppliers(supplier_id)
);


-- =========================================================
-- 5. Coupons
-- =========================================================
CREATE TABLE IF NOT EXISTS coupons (
    coupon_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    discount_percent INTEGER NOT NULL
        CHECK (discount_percent BETWEEN 0 AND 100),
    valid_from TEXT NOT NULL
        CHECK (date(valid_from) IS NOT NULL),
    valid_until TEXT NOT NULL
        CHECK (date(valid_until) IS NOT NULL),
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    CHECK (date(valid_from) <= date(valid_until))
);


-- =========================================================
-- 6. Orders
-- =========================================================
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    ordered_at TEXT NOT NULL
        CHECK (date(ordered_at) IS NOT NULL),
    status TEXT NOT NULL
        CHECK (
            status IN (
                'pending',
                'processing',
                'shipped',
                'delivered',
                'cancelled',
                'returned'
            )
        ),
    coupon_id INTEGER,
    discount_cents INTEGER NOT NULL DEFAULT 0
        CHECK (discount_cents >= 0),

    FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id),

    FOREIGN KEY (coupon_id)
        REFERENCES coupons(coupon_id)
);


-- =========================================================
-- 7. Order items
-- One row represents one product line in an order.
-- unit_price_cents is the price at the time of purchase.
-- =========================================================
CREATE TABLE IF NOT EXISTS order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL
        CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL
        CHECK (unit_price_cents >= 0),

    FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    FOREIGN KEY (product_id)
        REFERENCES products(product_id),

    UNIQUE (order_id, product_id)
);


-- =========================================================
-- 8. Payments
-- An order may have multiple payment attempts.
-- =========================================================
CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL
        CHECK (amount_cents >= 0),
    status TEXT NOT NULL
        CHECK (
            status IN (
                'pending',
                'successful',
                'failed',
                'refunded'
            )
        ),
    paid_at TEXT,

    FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    CHECK (
        paid_at IS NULL
        OR date(paid_at) IS NOT NULL
    )
);


-- =========================================================
-- 9. Shipments
-- =========================================================
CREATE TABLE IF NOT EXISTS shipments (
    shipment_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    carrier TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (
            status IN (
                'pending',
                'shipped',
                'in_transit',
                'delivered',
                'failed'
            )
        ),
    shipped_at TEXT,
    delivered_at TEXT,

    FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    CHECK (
        delivered_at IS NULL
        OR shipped_at IS NULL
        OR date(delivered_at) >= date(shipped_at)
    )
);


-- =========================================================
-- 10. Reviews
-- =========================================================
CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    rating INTEGER NOT NULL
        CHECK (rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL
        CHECK (date(created_at) IS NOT NULL),

    FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id),

    FOREIGN KEY (product_id)
        REFERENCES products(product_id),

    UNIQUE (customer_id, product_id)
);


-- =========================================================
-- Indexes for frequently used joins and filters
-- =========================================================

CREATE INDEX IF NOT EXISTS idx_products_category
    ON products(category_id);

CREATE INDEX IF NOT EXISTS idx_products_supplier
    ON products(supplier_id);

CREATE INDEX IF NOT EXISTS idx_orders_customer
    ON orders(customer_id);

CREATE INDEX IF NOT EXISTS idx_orders_date_status
    ON orders(ordered_at, status);

CREATE INDEX IF NOT EXISTS idx_order_items_product
    ON order_items(product_id);

CREATE INDEX IF NOT EXISTS idx_order_items_order
    ON order_items(order_id);

CREATE INDEX IF NOT EXISTS idx_payments_order_status
    ON payments(order_id, status);

CREATE INDEX IF NOT EXISTS idx_shipments_order
    ON shipments(order_id);

CREATE INDEX IF NOT EXISTS idx_reviews_product_rating
    ON reviews(product_id, rating);

CREATE INDEX IF NOT EXISTS idx_reviews_customer
    ON reviews(customer_id);

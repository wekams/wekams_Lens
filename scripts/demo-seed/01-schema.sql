-- Demo e-commerce schema for testing Wekams Lens against a real Postgres.
-- Loaded automatically on first start of the demo-source container.

CREATE TABLE customers (
    id           SERIAL PRIMARY KEY,
    email        TEXT NOT NULL UNIQUE,
    full_name    TEXT NOT NULL,
    country      TEXT NOT NULL,
    signed_up_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    sku         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0)
);

CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    placed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status      TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'shipped', 'refunded'))
);

CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0)
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_placed_at ON orders(placed_at);
CREATE INDEX idx_order_items_order ON order_items(order_id);

COMMENT ON TABLE customers IS 'End customers who can place orders.';
COMMENT ON TABLE products  IS 'Catalog of products available for purchase.';
COMMENT ON TABLE orders    IS 'Orders placed by customers.';
COMMENT ON TABLE order_items IS 'Line items within an order.';

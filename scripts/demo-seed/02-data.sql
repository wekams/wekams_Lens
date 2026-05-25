-- Seed data for the demo source. Small but realistic enough for chat queries
-- like "top customers", "revenue last month", "refund rate by category".

INSERT INTO customers (email, full_name, country, signed_up_at) VALUES
    ('aria@example.com',  'Aria Patel',     'IN', NOW() - INTERVAL '120 days'),
    ('liam@example.com',  'Liam Chen',      'SG', NOW() - INTERVAL '95 days'),
    ('sofia@example.com', 'Sofia Garcia',   'AE', NOW() - INTERVAL '80 days'),
    ('noah@example.com',  'Noah Williams',  'AU', NOW() - INTERVAL '60 days'),
    ('emma@example.com',  'Emma Johnson',   'IN', NOW() - INTERVAL '40 days'),
    ('kai@example.com',   'Kai Tanaka',     'SG', NOW() - INTERVAL '21 days'),
    ('mia@example.com',   'Mia Rossi',      'AE', NOW() - INTERVAL '10 days');

INSERT INTO products (sku, name, category, price_cents) VALUES
    ('SKU-001', 'Wireless Headphones',  'electronics', 12900),
    ('SKU-002', 'Bluetooth Speaker',    'electronics',  6900),
    ('SKU-003', 'Mechanical Keyboard',  'electronics', 14900),
    ('SKU-004', 'Cotton T-Shirt',       'apparel',      2400),
    ('SKU-005', 'Running Shoes',        'apparel',      8900),
    ('SKU-006', 'Stainless Bottle',     'home',         1800),
    ('SKU-007', 'Ceramic Mug',          'home',          900),
    ('SKU-008', 'Yoga Mat',             'fitness',      3200);

-- Spread orders across the last 90 days, with a deliberate dip "last week"
-- so a question like "why did orders drop?" has something to find.
INSERT INTO orders (customer_id, placed_at, status) VALUES
    (1, NOW() - INTERVAL '85 days', 'shipped'),
    (1, NOW() - INTERVAL '60 days', 'shipped'),
    (2, NOW() - INTERVAL '70 days', 'shipped'),
    (2, NOW() - INTERVAL '40 days', 'shipped'),
    (2, NOW() - INTERVAL '15 days', 'shipped'),
    (3, NOW() - INTERVAL '55 days', 'refunded'),
    (3, NOW() - INTERVAL '30 days', 'shipped'),
    (4, NOW() - INTERVAL '45 days', 'shipped'),
    (4, NOW() - INTERVAL '20 days', 'shipped'),
    (5, NOW() - INTERVAL '35 days', 'shipped'),
    (5, NOW() - INTERVAL '25 days', 'shipped'),
    (5, NOW() - INTERVAL '12 days', 'paid'),
    (6, NOW() - INTERVAL '18 days', 'shipped'),
    (6, NOW() - INTERVAL '5 days',  'pending'),
    (7, NOW() - INTERVAL '8 days',  'shipped'),
    (7, NOW() - INTERVAL '2 days',  'paid');

INSERT INTO order_items (order_id, product_id, quantity, price_cents) VALUES
    (1, 1, 1, 12900),
    (1, 4, 2,  2400),
    (2, 2, 1,  6900),
    (3, 3, 1, 14900),
    (4, 5, 1,  8900),
    (5, 1, 1, 12900),
    (5, 7, 4,   900),
    (6, 8, 1,  3200),
    (7, 6, 2,  1800),
    (8, 4, 3,  2400),
    (9, 2, 1,  6900),
    (10, 5, 1,  8900),
    (11, 3, 1, 14900),
    (12, 1, 1, 12900),
    (13, 7, 2,   900),
    (14, 6, 1,  1800),
    (15, 8, 1,  3200),
    (16, 2, 1,  6900);

ANALYZE;

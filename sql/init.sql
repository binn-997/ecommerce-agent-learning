CREATE TABLE IF NOT EXISTS sku_master (
    sku TEXT PRIMARY KEY,
    asin TEXT,
    product_name TEXT NOT NULL,
    reorder_days INTEGER NOT NULL DEFAULT 21,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    amazon_order_id TEXT PRIMARY KEY,
    sku TEXT REFERENCES sku_master(sku),
    purchase_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    currency CHAR(3),
    amount NUMERIC(12, 2),
    raw_payload JSONB NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    metric_date DATE NOT NULL,
    sku TEXT REFERENCES sku_master(sku),
    units_sold INTEGER NOT NULL DEFAULT 0,
    revenue NUMERIC(12, 2) NOT NULL DEFAULT 0,
    ad_spend NUMERIC(12, 2) NOT NULL DEFAULT 0,
    inventory_units INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (metric_date, sku)
);

CREATE TABLE IF NOT EXISTS alerts (
    source_key TEXT PRIMARY KEY,
    alert_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS orders_purchase_at_idx ON orders (purchase_at DESC);
CREATE INDEX IF NOT EXISTS daily_metrics_sku_date_idx ON daily_metrics (sku, metric_date DESC);

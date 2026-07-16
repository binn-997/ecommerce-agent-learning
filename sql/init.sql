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
    sessions INTEGER NOT NULL DEFAULT 0,
    currency CHAR(3) NOT NULL DEFAULT 'EUR',
    trace_id TEXT,
    PRIMARY KEY (metric_date, sku)
);

CREATE TABLE IF NOT EXISTS alerts (
    source_key TEXT PRIMARY KEY,
    alert_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_imports (
    payload_hash CHAR(64) PRIMARY KEY,
    payload JSONB NOT NULL,
    trace_id TEXT NOT NULL,
    seller_id_hash TEXT NOT NULL,
    operation TEXT NOT NULL,
    request_id TEXT NOT NULL,
    date_window TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_replayed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_cursors (
    seller_id_hash TEXT NOT NULL,
    operation TEXT NOT NULL,
    cursor_value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (seller_id_hash, operation)
);

CREATE TABLE IF NOT EXISTS advertising_metrics (
    metric_date DATE NOT NULL,
    campaign_id TEXT NOT NULL,
    sku TEXT NOT NULL REFERENCES sku_master(sku),
    report_id TEXT NOT NULL,
    impressions BIGINT NOT NULL CHECK (impressions >= 0),
    clicks BIGINT NOT NULL CHECK (clicks >= 0),
    purchases BIGINT NOT NULL CHECK (purchases >= 0),
    spend NUMERIC(12, 2) NOT NULL CHECK (spend >= 0),
    attributed_sales NUMERIC(12, 2) NOT NULL CHECK (attributed_sales >= 0),
    trace_id TEXT NOT NULL,
    PRIMARY KEY (metric_date, campaign_id, sku)
);

CREATE TABLE IF NOT EXISTS human_reviews (
    request_id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'reject', 'edit')),
    reviewer_id_hash TEXT NOT NULL,
    payload JSONB NOT NULL,
    publishes_change BOOLEAN NOT NULL DEFAULT FALSE CHECK (publishes_change = FALSE),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id BIGSERIAL PRIMARY KEY,
    trace_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS orders_purchase_at_idx ON orders (purchase_at DESC);
CREATE INDEX IF NOT EXISTS daily_metrics_sku_date_idx ON daily_metrics (sku, metric_date DESC);
CREATE INDEX IF NOT EXISTS audit_events_trace_idx ON audit_events (trace_id, created_at);

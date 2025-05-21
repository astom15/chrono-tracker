CREATE TABLE IF NOT EXISTS listings (
    id SERIAL PRIMARY KEY,
    input_sku_attributes JSONB,
    scraped_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    listing_url TEXT NOT NULL,
    listing_title TEXT,
    price NUMERIC(14,2),
    currency VARCHAR(10),
    condition VARCHAR(255),
    production_year INTEGER,
    location VARCHAR(255),
    seller_name VARCHAR(255)
    brand VARCHAR(255)
    model VARCHAR(25)
    movement VARCHAR(25)
    case_material VARCHAR(25)
    dial_color VARCHAR(25)
    dial VARCHAR(25)
    reference_number VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_listings_listing_url ON listings (listing_url);
CREATE INDEX IF NOT EXISTS idx_listings_scraped_timestamp ON listings (scraped_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_listings_input_sku_attributes ON listings USING GIN (input_sku_attributes);
CREATE INDEX IF NOT EXISTS idx_listings_price ON listings (price);
CREATE INDEX IF NOT EXISTS idx_listings_condition ON listings (condition);
CREATE INDEX IF NOT EXISTS idx_listings_year ON listings (production_year);
CREATE INDEX IF NOT EXISTS idx_listings_location ON listings (location);
CREATE INDEX IF NOT EXISTS idx_listings_model ON listings (model);
CREATE INDEX IF NOT EXISTS idx_listings_brand ON listings (brand);

CREATE TABLE IF NOT EXISTS analysis_results (
    id SERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    input_sku_attributes JSONB NOT NULL,
    your_list_price NUMERIC(14,2),
    calculated_average_market_price NUMERIC(14,2),
    delta_percentage NUMERIC(5,2),
    bottom_5_listings_urls TEXT[],
    bottom_5_listings_prices NUMERIC(14,2)[],
    total_listings_found INTEGER,
    alert_triggered BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_ar_run_timestamp ON analysis_results (run_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ar_input_sku_attributes ON analysis_results USING GIN (input_sku_attributes);
CREATE INDEX IF NOT EXISTS idx_ar_alert_triggered ON analysis_results (alert_triggered) WHERE alert_triggered = TRUE;

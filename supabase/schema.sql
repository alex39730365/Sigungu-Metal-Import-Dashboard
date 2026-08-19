-- Supabase(PostgreSQL) schema for Sigungu Metal Import Dashboard
-- Run this in Supabase Dashboard > SQL Editor, or use scripts/setup_supabase_schema.py

CREATE TABLE IF NOT EXISTS raw_metal_imports (
    target_key TEXT PRIMARY KEY,
    year_month TEXT NOT NULL,
    sido_cd TEXT NOT NULL,
    sigungu_name TEXT NOT NULL,
    hs_code TEXT NOT NULL,
    item_name TEXT NOT NULL,
    metal_category TEXT NOT NULL,
    import_count INTEGER NOT NULL DEFAULT 0,
    import_amount_usd NUMERIC(20, 2) NOT NULL DEFAULT 0,
    export_count INTEGER NOT NULL DEFAULT 0,
    export_amount_usd NUMERIC(20, 2) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collection_progress (
    task_name TEXT PRIMARY KEY,
    completed_index INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

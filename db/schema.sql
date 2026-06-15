-- db/schema.sql — Roaring Kittens, Phase 0-1
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS news_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    published_at TIMESTAMPTZ NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tickers     TEXT[] NOT NULL DEFAULT '{}',
    source      VARCHAR(50) NOT NULL,
    headline    TEXT NOT NULL,
    body        TEXT,
    url         TEXT UNIQUE NOT NULL,
    embedding   VECTOR(1536)
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_events (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_tickers ON news_events USING gin (tickers);

CREATE TABLE IF NOT EXISTS usage_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
    operation     VARCHAR(50) NOT NULL,
    model         VARCHAR(50) NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd      NUMERIC(10,6) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log (timestamp DESC);

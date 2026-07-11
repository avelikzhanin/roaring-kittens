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

CREATE TABLE IF NOT EXISTS calls (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    asked_by      BIGINT NOT NULL,
    ticker        VARCHAR(20) NOT NULL,
    figi          VARCHAR(20) NOT NULL,
    source        VARCHAR(20) NOT NULL,          -- 'ask' | 'spotlight' | 'retro'
    question      TEXT,
    stance        VARCHAR(10) NOT NULL,          -- 'bullish' | 'bearish' | 'neutral'
    confidence    FLOAT NOT NULL,
    summary       TEXT NOT NULL,
    price_at_call NUMERIC,                       -- NULL => не скорится
    news_urls     TEXT[] NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_calls_ticker_created ON calls (ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS call_scores (
    call_id          UUID NOT NULL REFERENCES calls(id),
    horizon_days     INTEGER NOT NULL,           -- 5 | 20 | 60
    stock_return_pct NUMERIC NOT NULL,
    imoex_return_pct NUMERIC NOT NULL,
    verdict          VARCHAR(10) NOT NULL,       -- 'hit' | 'miss'
    scored_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (call_id, horizon_days)
);

CREATE TABLE IF NOT EXISTS bot_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

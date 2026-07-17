from pgvector.sqlalchemy import Vector
from sqlalchemy import (TIMESTAMP, BigInteger, Boolean, Column, Float, ForeignKey,
                        Integer, MetaData, Numeric, String, Table, Text, text)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

metadata = MetaData()

calls = Table(
    "calls", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("asked_by", BigInteger, nullable=False),
    Column("ticker", String(20), nullable=False),
    Column("figi", String(20), nullable=False),
    Column("source", String(20), nullable=False),
    Column("question", Text),
    Column("stance", String(10), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("summary", Text, nullable=False),
    Column("price_at_call", Numeric),
    Column("news_urls", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("embedding", Vector(1536)),
)

theses = Table(
    "theses", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("ticker", String(20), nullable=False),
    Column("figi", String(20), nullable=False),
    Column("opened_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("closed_at", TIMESTAMP(timezone=True)),
    Column("status", String(20), nullable=False, server_default=text("'active'")),
    Column("thesis", Text, nullable=False),
    Column("invalidation", Text, nullable=False),
    Column("source", String(20), nullable=False),
    Column("backed_by_position", Boolean, nullable=False, server_default=text("false")),
    Column("confidence", Float),
    Column("entry_price", Numeric),
    Column("realized_return_pct", Numeric),
    Column("close_reason", Text),
    Column("last_weakened_at", TIMESTAMP(timezone=True)),
)

insights = Table(
    "insights", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("summary", Text, nullable=False),
    Column("scope", String(50), nullable=False),
    Column("scope_value", String(50)),
    Column("confidence", Float, nullable=False),
    Column("embedding", Vector(1536)),
    Column("times_applied", Integer, nullable=False, server_default=text("0")),
    Column("archived_at", TIMESTAMP(timezone=True)),
)

call_scores = Table(
    "call_scores", metadata,
    Column("call_id", UUID(as_uuid=True), ForeignKey("calls.id"), primary_key=True),
    Column("horizon_days", Integer, primary_key=True),
    Column("stock_return_pct", Numeric, nullable=False),
    Column("imoex_return_pct", Numeric, nullable=False),
    Column("verdict", String(10), nullable=False),
    Column("scored_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

news_events = Table(
    "news_events", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("published_at", TIMESTAMP(timezone=True), nullable=False),
    Column("fetched_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("tickers", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("source", String(50), nullable=False),
    Column("headline", Text, nullable=False),
    Column("body", Text),
    Column("url", Text, nullable=False, unique=True),
)

council_runs = Table(
    "council_runs", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("ticker", String(20), nullable=False),
    Column("asked_by", BigInteger, nullable=False),
    Column("transcript", JSONB, nullable=False),
    Column("call_id", UUID(as_uuid=True), ForeignKey("calls.id")),
)

bot_state = Table(
    "bot_state", metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

usage_log = Table(
    "usage_log", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("timestamp", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("operation", String(50), nullable=False),
    Column("model", String(50), nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost_usd", Numeric(10, 6), nullable=False),
)

from sqlalchemy import TIMESTAMP, Column, Integer, MetaData, Numeric, String, Table, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID

metadata = MetaData()

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

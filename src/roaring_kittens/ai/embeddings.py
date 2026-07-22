from typing import Any

import structlog

from roaring_kittens.ai.llm import UsageLogger
from roaring_kittens.ai.usage_context import current_user_id
from roaring_kittens.utils.retry import retry_async

log = structlog.get_logger()

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
EMBED_COST_PER_1M = 0.02
MAX_INPUT_CHARS = 8000


class Embedder:
    def __init__(self, client: Any, usage_logger: UsageLogger):
        self._client = client
        self._log_usage = usage_logger

    @retry_async(attempts=2, base_delay=2.0)
    async def embed(self, text: str, operation: str) -> list[float]:
        resp = await self._client.embeddings.create(
            model=EMBED_MODEL, input=text[:MAX_INPUT_CHARS])
        tokens = resp.usage.prompt_tokens
        await self._log_usage(operation, EMBED_MODEL, tokens, 0,
                              tokens / 1_000_000 * EMBED_COST_PER_1M,
                              user_id=current_user_id.get())
        return resp.data[0].embedding

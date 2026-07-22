from typing import Any, Awaitable, Callable, TypeVar

import structlog
from pydantic import BaseModel

from roaring_kittens.ai.pricing import estimate_cost
from roaring_kittens.ai.usage_context import budget_mode, current_user_id
from roaring_kittens.utils.retry import retry_async

log = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)

UsageLogger = Callable[..., Awaitable[None]]  # (operation, model, input_tokens, output_tokens, cost_usd, user_id=None)

# 80% бюджета: тяжёлые модели подменяются на дешёвые; o4-mini/mini не трогаем
ECONOM_MODEL_MAP = {"gpt-4o": "gpt-4o-mini", "gpt-4.1": "gpt-4o-mini"}


class LLM:
    def __init__(self, client: Any, usage_logger: UsageLogger):
        self._client = client
        self._log_usage = usage_logger

    def _parse_fn(self):
        """Structured-output helper. SDK переносил его между chat.completions и beta.*;
        пробуем стабильный путь, иначе beta."""
        completions = self._client.chat.completions
        fn = getattr(completions, "parse", None)
        if fn is not None:
            return fn
        return self._client.beta.chat.completions.parse

    @retry_async(attempts=3, base_delay=2.0)
    async def parse(self, *, model: str, operation: str,
                    messages: list[dict], schema: type[T],
                    temperature: float | None = None) -> T:
        if budget_mode.get() == "econom":
            model = ECONOM_MODEL_MAP.get(model, model)
        kwargs: dict[str, Any] = dict(model=model, messages=messages, response_format=schema)
        if temperature is not None:
            kwargs["temperature"] = temperature  # reasoning-модели (o-серия) не принимают — не передаём
        resp = await self._parse_fn()(**kwargs)
        u = resp.usage
        cost = estimate_cost(model, u.prompt_tokens, u.completion_tokens)
        await self._log_usage(operation, model, u.prompt_tokens, u.completion_tokens,
                              cost, user_id=current_user_id.get())
        log.info("llm_call", operation=operation, model=model,
                 input=u.prompt_tokens, output=u.completion_tokens, cost=round(cost, 5))
        return resp.choices[0].message.parsed


def make_db_usage_logger(session_factory) -> UsageLogger:
    from roaring_kittens.db.tables import usage_log

    async def _log(operation, model, input_tokens, output_tokens, cost_usd,
                   user_id=None):
        async with session_factory() as session:
            await session.execute(usage_log.insert().values(
                operation=operation, model=model, input_tokens=input_tokens,
                output_tokens=output_tokens, cost_usd=cost_usd, user_id=user_id,
            ))
            await session.commit()

    return _log

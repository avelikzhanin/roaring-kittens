from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import BaseModel

from roaring_kittens.ai.llm import LLM
from roaring_kittens.ai.pricing import estimate_cost


class Echo(BaseModel):
    answer: str


def _fake_response(parsed):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


async def test_parse_returns_schema_and_logs_usage():
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(
            parse=AsyncMock(return_value=_fake_response(Echo(answer="да")))
        ))
    )
    logged = []

    async def fake_log(operation, model, input_tokens, output_tokens, cost_usd):
        logged.append((operation, model, input_tokens, output_tokens, cost_usd))

    llm = LLM(client=fake_client, usage_logger=fake_log)
    result = await llm.parse(model="gpt-4o", operation="test_op",
                             messages=[{"role": "user", "content": "hi"}], schema=Echo)
    assert result.answer == "да"
    assert logged == [("test_op", "gpt-4o", 100, 50, estimate_cost("gpt-4o", 100, 50))]


def test_estimate_cost():
    assert estimate_cost("gpt-4o", 1_000_000, 0) == 2.50
    assert estimate_cost("gpt-4o-mini", 0, 1_000_000) == 0.60

from types import SimpleNamespace

from pydantic import BaseModel

from roaring_kittens.ai.llm import LLM
from roaring_kittens.ai.usage_context import (
    budget_mode, current_user_id, use_budget_mode, use_user,
)


class Echo(BaseModel):
    answer: str


def _fake_client(tracker):
    async def parse(**kwargs):
        tracker["model"] = kwargs["model"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=Echo(answer="ok")))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))


async def test_user_id_flows_to_usage_logger_and_econom_swaps_model():
    tracker = {}
    logged = {}

    async def fake_log(operation, model, input_tokens, output_tokens, cost_usd,
                       user_id=None):
        logged["user_id"] = user_id
        logged["model"] = model

    llm = LLM(client=_fake_client(tracker), usage_logger=fake_log)
    with use_user(111), use_budget_mode("econom"):
        assert current_user_id.get() == 111
        assert budget_mode.get() == "econom"
        await llm.parse(model="gpt-4o", operation="t",
                        messages=[{"role": "user", "content": "x"}], schema=Echo)
    assert tracker["model"] == "gpt-4o-mini"   # econom подменил
    assert logged["user_id"] == 111
    # вне контекста — дефолты
    assert current_user_id.get() is None and budget_mode.get() == "ok"
    await llm.parse(model="gpt-4o", operation="t",
                    messages=[{"role": "user", "content": "x"}], schema=Echo)
    assert tracker["model"] == "gpt-4o" and logged["user_id"] is None

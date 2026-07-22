from types import SimpleNamespace
from unittest.mock import AsyncMock

from roaring_kittens.ai.embeddings import EMBED_MODEL, Embedder


def _fake_client(vector):
    resp = SimpleNamespace(data=[SimpleNamespace(embedding=vector)],
                           usage=SimpleNamespace(prompt_tokens=7, total_tokens=7))
    return SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(return_value=resp)))


async def test_embed_returns_vector_and_logs_usage():
    logged = []

    async def fake_log(operation, model, input_tokens, output_tokens, cost_usd,
                       user_id=None):
        logged.append((operation, model, input_tokens, output_tokens))

    client = _fake_client([0.1] * 1536)
    emb = Embedder(client=client, usage_logger=fake_log)
    vec = await emb.embed("Сбер растёт", operation="memory_query")
    assert len(vec) == 1536
    assert logged == [("memory_query", EMBED_MODEL, 7, 0)]
    # текст обрезается до 8000 символов
    await emb.embed("x" * 20000, operation="memory_query")
    sent = client.embeddings.create.call_args.kwargs["input"]
    assert len(sent) == 8000

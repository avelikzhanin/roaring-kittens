"""USD за 1M токенов (input, output). Сверить с актуальным прайсом OpenAI при имплементации."""
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o4-mini": (1.10, 4.40),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = MODEL_PRICES.get(model, (5.0, 15.0))  # консервативный дефолт для неизвестных моделей
    return input_tokens / 1_000_000 * inp + output_tokens / 1_000_000 * out

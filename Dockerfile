FROM python:3.12-slim
WORKDIR /app

# git нужен для установки Tinkoff SDK (он git-only, удалён с PyPI)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir --no-deps \
       "tinkoff-investments @ git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta117"

COPY scripts ./scripts
COPY db ./db

CMD ["python", "-m", "roaring_kittens.main"]

FROM python:3.12-slim
WORKDIR /app

# git нужен для установки Tinkoff SDK (он git-only, удалён с PyPI)
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Tinkoff Invest API подписан УЦ Минцифры — без этого корня gRPC видит
# «self signed certificate in certificate chain» и бот слепнет (инцидент 09.2026).
# Только КОРЕНЬ: сервер шлёт полную цепочку, а вендоринг Sub CA (истекает 03.2027)
# повторил бы инцидент нашими же руками.
COPY certs/russian_trusted_root_ca_pem.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates
ENV GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir --no-deps \
       "tinkoff-investments @ git+https://github.com/RussianInvestments/invest-python.git@0.2.0-beta117"

COPY scripts ./scripts
COPY db ./db

CMD ["python", "-m", "roaring_kittens.main"]

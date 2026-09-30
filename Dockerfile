FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN groupadd -g 10001 qmo && useradd -u 10001 -g 10001 --home-dir /app qmo

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

RUN mkdir -p /var/lib/qmo/data && chown -R 10001:10001 /app /var/lib/qmo
USER 10001:10001

ENTRYPOINT ["uv", "run", "--no-sync", "qmo"]
CMD ["status", "--root-dir", "/var/lib/qmo/data"]

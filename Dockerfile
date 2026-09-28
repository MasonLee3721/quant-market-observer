FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN groupadd --system qmo && useradd --system --gid qmo --home-dir /app qmo

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

RUN mkdir -p /var/lib/qmo/data && chown -R qmo:qmo /app /var/lib/qmo
USER qmo

ENTRYPOINT ["uv", "run", "--no-sync", "qmo"]
CMD ["status", "--root-dir", "/var/lib/qmo/data"]

FROM python:3.13-slim AS builder

ARG UV_VERSION=0.11.26

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app
RUN pip install --no-cache-dir "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev


FROM builder AS test

COPY tests ./tests
COPY compose.deploy.yaml ./compose.deploy.yaml
COPY deploy ./deploy
RUN uv sync --frozen --extra dev
CMD ["sh", "-c", "uv run --no-sync ruff check . && uv run --no-sync pytest -q"]


FROM python:3.13-slim AS runtime

ARG INSTALL_LEGACY_DOC_SUPPORT=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    HOME=/tmp/splicr-home \
    XDG_CACHE_HOME=/tmp/splicr-cache \
    XDG_CONFIG_HOME=/tmp/splicr-config \
    SPLICR_DATA_DIR=/data

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates ffmpeg && \
    if [ "$INSTALL_LEGACY_DOC_SUPPORT" = "1" ]; then \
        apt-get install -y --no-install-recommends libreoffice-writer; \
    fi && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 splicr && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin splicr && \
    install -d -m 0700 -o 10001 -g 10001 /data

WORKDIR /app
COPY --from=builder --chown=10001:10001 /app /app

USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).read()"]
CMD ["uvicorn", "splicr.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

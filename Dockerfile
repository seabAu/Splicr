FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPLICR_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv==0.11.26 && \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

VOLUME ["/data"]
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "splicr.api:app", "--host", "0.0.0.0", "--port", "8000"]

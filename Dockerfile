FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BEHALF_LEDGER_DIR=/app/ledger \
    BEHALF_STATE_DIR=/app/state \
    BEHALF_OUT_DIR=/app/out \
    BEHALF_CONFIG=/app/config.yaml

WORKDIR /app

# Dependencies first so edits to src/ do not invalidate the wheel layer.
COPY pyproject.toml ./
COPY src/behalf/__init__.py src/behalf/__init__.py
RUN pip install --no-cache-dir ".[all]"

COPY src ./src
COPY config.yaml ./config.yaml
COPY docker/entrypoint.sh /usr/local/bin/entrypoint
RUN pip install --no-cache-dir --no-deps -e . && chmod +x /usr/local/bin/entrypoint

RUN useradd --create-home --uid 10001 behalf \
    && mkdir -p /app/state /app/out /app/ledger \
    && chown -R behalf:behalf /app
USER behalf

ENTRYPOINT ["entrypoint"]
CMD ["roster"]

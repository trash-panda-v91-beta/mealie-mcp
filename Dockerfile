# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32

# Build stage: install runtime deps and the project into a virtualenv.
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /uvx /bin/

# Use the image's system Python; don't pull dev/test deps into the image.
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Cache dependency install (they change rarely vs. project source).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

# Copy the project and install it (non-editable, so the code lives in .venv).
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# Runtime stage: copy only the virtualenv.
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd -m -u 1000 mcpuser
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
USER mcpuser

# MCP stdio server entrypoint.
CMD ["/app/.venv/bin/mealie-mcp"]

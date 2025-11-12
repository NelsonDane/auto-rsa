# Nelson Dane

FROM ghcr.io/astral-sh/uv:bookworm-slim@sha256:430f10227c44f7688a095c27bfe234d8ca26a3603472db6ed2cf4e90ad19732a AS builder
# Layer taken from: https://www.joshkasuboski.com/posts/distroless-python-uv/

# UV Flags
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PYTHON_PREFERENCE=only-managed

WORKDIR /app

# Install system dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Needed for SSL
    ca-certificates \
    # Needed for building packages from git sources
    git \
&& rm -rf /var/lib/apt/lists/*

# Install Python
COPY pyproject.toml .
RUN uv python install

# UV sync with cache
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-editable
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM alpine:3.22@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412 AS unixifier

# Make entrypoint executable
WORKDIR /app
RUN apk add --no-cache dos2unix=7.5.2-r0
COPY entrypoint.sh .
RUN dos2unix entrypoint.sh && chmod +x entrypoint.sh

FROM debian:bookworm-slim@sha256:936abff852736f951dab72d91a1b6337cf04217b2a77a5eaadc7c0f2f1ec1758 AS final

# Set ENV variables
ENV TZ=America/New_York \
    DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    XDG_CACHE_HOME=/tmp/.cache \
    PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers

WORKDIR /app
RUN useradd -m appuser && chown -R appuser:appuser /app

# Install other dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    chromium \
    chromium-driver \
    xvfb \
&& rm -rf /var/lib/apt/lists/*

# Install python and dependencies
COPY --from=builder --chown=python:python /python /python
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install playwright
RUN playwright install firefox

# Set the entrypoint to our entrypoint.sh
COPY --from=unixifier --chmod=755 /app/entrypoint.sh /app/entrypoint.sh

# Switch to non-root user
USER appuser

# Sanity check
RUN auto_rsa_bot --help

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

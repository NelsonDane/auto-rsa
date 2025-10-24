# Nelson Dane

# Build from python slim image
FROM python:3.13.7-slim@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    dos2unix \
    git \
&& rm -rf /var/lib/apt/lists/*

# Use Python venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install pip requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Make entrypoint executable
COPY entrypoint.sh .
RUN dos2unix entrypoint.sh && chmod +x entrypoint.sh

FROM python:3.13.7-slim@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689

# Set ENV variables
ENV TZ=America/New_York \
    DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    XDG_CACHE_HOME=/tmp/.cache \
    PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers

WORKDIR /app

# Install other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    git \
    tzdata \
    xvfb \
&& rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install playwright
RUN playwright install firefox

# Copy app files
COPY . .

# Set the entrypoint to our entrypoint.sh
COPY --from=builder /app/entrypoint.sh .
RUN chmod 755 /app/entrypoint.sh

# Create user and switch to it
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]

# Nelson Dane

# Build from python slim image
FROM python:3.13.7-slim@sha256:58c30f5bfaa718b5803a53393190b9c68bd517c44c6c94c1b6c8c172bcfad040 AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

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

FROM python:3.13.7-slim@sha256:58c30f5bfaa718b5803a53393190b9c68bd517c44c6c94c1b6c8c172bcfad040

# Set ENV variables
ENV TZ=America/New_York
ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99

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
ENTRYPOINT ["/app/entrypoint.sh"]

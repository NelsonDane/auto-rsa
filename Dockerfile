# Nelson Dane

# Build from python slim image
FROM python:3.13.7-slim@sha256:58c30f5bfaa718b5803a53393190b9c68bd517c44c6c94c1b6c8c172bcfad040

# Set ENV variables
ENV TZ=America/New_York
ENV DEBIAN_FRONTEND=noninteractive

# Default display to :99
ENV DISPLAY=:99

# Chromium requires Clang-19
RUN apt-get update && apt-get install -y --no-install-recommends \
    gnupg \
    lsb-release \
    wget \
&& rm -rf /var/lib/apt/lists/*
RUN wget https://apt.llvm.org/llvm.sh && chmod +x llvm.sh && ./llvm.sh 19
RUN ln -s /usr/bin/clang-19 /usr/bin/clang

# Install other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    dos2unix \
    git \
    tzdata \
    xvfb \
&& rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install playwrightj
# Don't install deps: https://github.com/microsoft/playwright/issues/13738
# RUN playwright install firefox && \
    # playwright install-deps
RUN playwright install firefox

# CD into app
WORKDIR /app
COPY . .

# Make the entrypoint executable
RUN dos2unix entrypoint.sh && \
    chmod +x entrypoint.sh

# Set the entrypoint to our entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
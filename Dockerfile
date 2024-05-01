# Nelson Dane

# Build from python slim image
FROM python:3.12-slim

# Set ENV variables
ENV TZ=America/New_York
ENV DEBIAN_FRONTEND=noninteractive

# Default display to :99
ENV DISPLAY :99

# Install python, pip, and tzdata
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    dos2unix \
    git \
    tzdata \
    xvfb \
&& rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install playwright
RUN playwright install && \
    playwright install-deps

# CD into app
WORKDIR /app
COPY . .

# Make the entrypoint executable
RUN dos2unix entrypoint.sh && \
    chmod +x entrypoint.sh

# Set the entrypoint to our entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
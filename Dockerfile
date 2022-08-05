# Nelson Dane

# Build from Playwright
FROM mcr.microsoft.com/playwright:v1.24.0-focal
# Set ENV variables
ENV TZ=America/New_York
ENV DEBIAN_FRONTEND=noninteractive

# CD into app
WORKDIR /app

# Install python, pip, and tzdata
RUN apt-get update && apt-get install -y \
    python3-pip \
    tzdata \
&& rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt .

# Install dependencies
RUN pip install -r requirements.txt
# Install playwright for Schwab
RUN playwright install
RUN playwright install-deps

# Grab needed files
COPY ./auto-rsa.py .
COPY ./allyAPI.py .
COPY ./fidelityAPI.py .
COPY ./robinhoodAPI.py .
COPY ./schwabAPI.py .
COPY ./tradierAPI.py .
COPY ./webullAPI.py .

CMD ["python3","auto-rsa.py"]
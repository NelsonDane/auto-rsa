# Nelson Dane
# NOT CURRENTLY WORKING

# Build from alpine to keep the image small
FROM alpine:latest
# Set default timezone
ENV TZ=America/New_York

# Install python, pip, and tzdata
RUN apk add --no-cache py3-pip tzdata

# Grab needed files
WORKDIR /app
COPY ./requirements.txt .

# Install dependencies (Fails here: requires playwright for Schwab)
RUN pip install -r requirements.txt

COPY ./auto-rsa.py .
COPY ./allyAPI.py .
COPY ./fidelityAPI.py .
COPY ./robinhoodAPI.py .
COPY ./schwabAPI.py .
COPY ./tradierAPI.py .
COPY ./webullAPI.py .

CMD ["python3","auto-rsa.py"]


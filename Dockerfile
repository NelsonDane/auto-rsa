# Nelson Dane

# Build from alpine to keep the image small
FROM ubuntu:22.04
# Set default timezone
ENV TZ=America/New_York
ENV DEBIAN_FRONTEND=noninteractive

# Install python, pip, and tzdata
RUN apt-get update && apt-get install python3-pip tzdata -y

# CD into app and grab requirements
WORKDIR /app
COPY ./requirements.txt .

# Install dependencies (Fails here: requires playwright for Schwab)
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
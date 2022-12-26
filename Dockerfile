# Nelson Dane

# Build from Ubuntu 22.04
FROM ubuntu:22.04
# Set ENV variables
ENV TZ=America/New_York
ENV DEBIAN_FRONTEND=noninteractive

# Default display to :99
ENV DISPLAY :99

# CD into app
WORKDIR /app

# Install python, pip, and tzdata
RUN apt-get update && apt-get install -y \
    xvfb \
    xvfb \
    xfonts-cyrillic \
    xfonts-100dpi \
    xfonts-75dpi \
    xfonts-base \
    xfonts-scalable \
    gtk2-engines-pixbuf \
    wget \
    gpg \
    python3-pip \
    tzdata \
&& rm -rf /var/lib/apt/lists/*

# Install Edge
RUN wget https://packages.microsoft.com/keys/microsoft.asc -O- | apt-key add -
RUN sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/edge stable main" > /etc/apt/sources.list.d/microsoft-edge.list'
RUN apt-get update && apt-get install -y microsoft-edge-stable && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY ./requirements.txt .
RUN pip install -r requirements.txt

# Grab needed files
COPY ./autoRSA.py .
COPY ./allyAPI.py .
COPY ./fidelityAPI.py .
COPY ./robinhoodAPI.py .
COPY ./schwabAPI.py .
COPY ./tradierAPI.py .
COPY ./webullAPI.py .
COPY ./seleniumAPI.py .
COPY ./entrypoint.sh .

# Make the entrypoint executable
RUN chmod +x entrypoint.sh

# Set the entrypoint to our entrypoint.sh                                                                                                                     
ENTRYPOINT ["/app/entrypoint.sh"] 
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    libhidapi-dev

RUN wget https://github.com/todbot/hidapitester/releases/download/v0.5/hidapitester-linux-x86_64.zip \
    && unzip hidapitester-linux-x86_64.zip \
    && rm hidapitester-linux-x86_64.zip \
    && mv ./hidapitester /usr/local/bin/hidapitester

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY ./controller/requirements/ /tmp/requirements/
RUN pip install --disable-pip-version-check --no-cache-dir -r /tmp/requirements/dev.txt \
    && rm -rf /tmp/requirements/

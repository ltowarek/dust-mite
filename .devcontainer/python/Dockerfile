FROM python:3.12-bookworm

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    libhidapi-dev \
    locales

# WA for VSCode issue https://github.com/microsoft/vscode/issues/189924
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen

RUN wget https://github.com/todbot/hidapitester/releases/download/v0.5/hidapitester-linux-x86_64.zip \
    && unzip hidapitester-linux-x86_64.zip \
    && rm hidapitester-linux-x86_64.zip \
    && mv ./hidapitester /usr/local/bin/hidapitester

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY ./controller/requirements/ /tmp/requirements/
RUN pip install --disable-pip-version-check --no-cache-dir -r /tmp/requirements/dev.txt \
    && rm -rf /tmp/requirements/

ARG USERNAME=vscode
ARG USER_UID=1050
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

USER $USERNAME

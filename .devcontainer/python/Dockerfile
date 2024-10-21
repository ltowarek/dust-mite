FROM python:3.12-bookworm

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    libhidapi-dev

RUN wget https://github.com/todbot/hidapitester/releases/download/v0.5/hidapitester-linux-x86_64.zip \
    && unzip hidapitester-linux-x86_64.zip \
    && rm hidapitester-linux-x86_64.zip \
    && mv ./hidapitester /usr/local/bin/hidapitester

ARG USERNAME=vscode
ARG USER_UID=1050
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

USER $USERNAME

RUN python3 -m venv ~/venv
ENV PATH="~/venv/bin:$PATH"

COPY --chown=$USER_UID:$USER_GID ./controller/requirements/ /tmp/requirements/
RUN pip install --disable-pip-version-check --no-cache-dir -r /tmp/requirements/dev.txt \
    && rm -rf /tmp/requirements/

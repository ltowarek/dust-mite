FROM python:3.12-bookworm

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    libhidapi-dev \
    && rm -rf /var/lib/apt/lists/*

ARG USERNAME=dustmite
ARG USER_UID=1040
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

USER $USERNAME

RUN python3 -m venv /home/$USERNAME/venv
ENV PATH="/home/$USERNAME/venv/bin:$PATH"

COPY --chown=$USERNAME:$USERNAME requirements/ /tmp/requirements/
RUN pip install --disable-pip-version-check --no-cache-dir -r /tmp/requirements/dev.txt \
    && rm -rf /tmp/requirements/

WORKDIR /home/$USERNAME/workspace/controller

COPY --chown=$USERNAME:$USERNAME . .
RUN pip install --disable-pip-version-check --no-cache-dir .

CMD ["streamer"]

FROM python:3.12-bookworm

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    curl \
    locales

# WA for VSCode issue https://github.com/microsoft/vscode/issues/189924
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen

ARG USERNAME=vscode
ARG USER_UID=1050
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

COPY scripts/install-gh.sh /tmp/install-gh.sh
RUN chmod +x /tmp/install-gh.sh && /tmp/install-gh.sh

USER $USERNAME

RUN python3 -m venv /home/$USERNAME/venv
ENV PATH="/home/$USERNAME/venv/bin:$PATH"

COPY --chown=$USERNAME:$USERNAME ./observability/requirements/ /tmp/requirements/
RUN pip install --disable-pip-version-check --no-cache-dir -r /tmp/requirements/dev.txt \
    && rm -rf /tmp/requirements/

RUN mkdir -p /home/$USERNAME/.claude
RUN curl -fsSL https://claude.ai/install.sh | bash -s stable
RUN echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

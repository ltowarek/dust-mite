FROM debian:bookworm

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    ca-certificates \
    curl \
    git \
    locales \
    python3-venv \
    xz-utils

# WA for VSCode issue https://github.com/microsoft/vscode/issues/189924
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen

ARG ACTIONLINT_VERSION=1.7.12
RUN curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/local/bin actionlint

ARG SHELLCHECK_VERSION=0.11.0
RUN curl -fsSL "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz" \
    | tar -xJ -C /usr/local/bin --strip-components=1 "shellcheck-v${SHELLCHECK_VERSION}/shellcheck"

ARG SHFMT_VERSION=3.14.1
RUN curl -fsSL -o /usr/local/bin/shfmt "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_linux_amd64" \
    && chmod +x /usr/local/bin/shfmt

# Debian's Python is externally managed (PEP 668), so zizmor gets its own venv.
ENV PATH="/opt/zizmor/bin:$PATH"
COPY .devcontainer/infrastructure/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/zizmor \
    && /opt/zizmor/bin/pip install --disable-pip-version-check --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

ARG USERNAME=vscode
ARG USER_UID=1050
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

USER $USERNAME

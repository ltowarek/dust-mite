FROM debian:bookworm

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    curl \
    default-jre \
    git \
    graphviz \
    imagemagick \
    locales \
    plantuml

# WA for VSCode issue https://github.com/microsoft/vscode/issues/189924
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen

ARG USERNAME=vscode
ARG USER_UID=1050
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

RUN mkdir -p /home/$USERNAME/.claude && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.claude

USER $USERNAME

RUN curl -fsSL https://claude.ai/install.sh | bash -s stable
RUN echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

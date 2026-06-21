FROM espressif/idf:release-v6.0

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    ccache \
    clang-format \
    curl \
    locales \
    protobuf-compiler

# WA for VSCode issue https://github.com/microsoft/vscode/issues/189924
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen

ARG USERNAME=vscode
ARG USER_UID=1050
ARG USER_GID=$USER_UID

COPY car/requirements-test.txt /tmp/requirements-test.txt
RUN /opt/esp/python_env/idf6.0_py3.12_env/bin/pip install -r /tmp/requirements-test.txt

RUN userdel -r ubuntu \
    && groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME \
    && usermod -aG dialout $USERNAME

ENV IDF_CCACHE_ENABLE=1
ENV CCACHE_DIR=/home/${USERNAME}/.ccache

RUN mkdir -p /home/$USERNAME/.claude && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.claude

RUN mkdir -p /home/$USERNAME/.ccache && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.ccache

RUN mkdir -p /home/$USERNAME/build && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/build

COPY scripts/install-gh.sh /tmp/install-gh.sh
RUN chmod +x /tmp/install-gh.sh && /tmp/install-gh.sh

USER $USERNAME

RUN git config --global --add safe.directory /opt/esp/idf/components/openthread/openthread
RUN echo "source $IDF_PATH/export.sh > /dev/null 2>&1" >> $HOME/.bashrc

RUN curl -fsSL https://claude.ai/install.sh | bash -s stable
RUN echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

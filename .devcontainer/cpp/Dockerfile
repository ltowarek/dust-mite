FROM debian:11.11 AS qemu-builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -y -q && apt-get install -y -q --no-install-recommends \
    build-essential \
    git \
    libgcrypt-dev \
    libglib2.0-dev \
    libpixman-1-dev \
    libslirp-dev \
    ninja-build \
    python3-pip \
    wget \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install meson==1.7.0 tomli==2.2.1

RUN git clone --depth 1 --branch apptrace \
        https://github.com/ltowarek/espressif-qemu.git /tmp/espressif-qemu \
    && cd /tmp/espressif-qemu \
    && ./configure --target-list=xtensa-softmmu \
                   --prefix=/opt/espressif-qemu \
                   --without-default-features \
                   --enable-gcrypt \
                   --enable-pixman \
                   --enable-slirp \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/espressif-qemu


FROM espressif/idf:release-v6.0

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    ccache \
    curl \
    libgcrypt20 \
    libglib2.0-0 \
    libpixman-1-0 \
    libslirp0 \
    locales \
    protobuf-compiler

COPY --from=qemu-builder /opt/espressif-qemu/bin/qemu-system-xtensa \
                         /opt/espressif-qemu/bin/qemu-system-xtensa
COPY --from=qemu-builder /opt/espressif-qemu/share/qemu/ \
                         /opt/espressif-qemu/share/qemu/

ENV QEMU_PROG_PATH=/opt/espressif-qemu/bin/qemu-system-xtensa

# esp-clang provides an Xtensa-aware clang/clang-tidy/clang-format; vanilla apt
# clang-tidy has no Xtensa backend, and a separate apt clang-format would drift
# in version from this one (car/scripts use esp-clang's clang-format/clang-tidy
# everywhere via export.sh, not whatever's on the system PATH).
RUN python3 $IDF_PATH/tools/idf_tools.py --quiet --idf-path $IDF_PATH install esp-clang

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

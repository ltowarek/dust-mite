FROM debian:bookworm AS qemu-builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -y -q && apt-get install -y -q --no-install-recommends \
    build-essential \
    git \
    libgcrypt20-dev \
    libglib2.0-dev \
    libpixman-1-dev \
    libslirp-dev \
    ninja-build \
    python3-venv \
    wget \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/qemu-builder-venv
ENV PATH="/opt/qemu-builder-venv/bin:$PATH"
RUN pip install --disable-pip-version-check --no-cache-dir meson==1.7.0 tomli==2.2.1

ARG ESPRESSIF_QEMU_COMMIT=ca3bac91db4d4dfc4eb179c39b2eb4908cabb8ec
RUN git init -q /tmp/espressif-qemu \
    && cd /tmp/espressif-qemu \
    && git fetch -q --depth 1 https://github.com/ltowarek/espressif-qemu.git \
           "$ESPRESSIF_QEMU_COMMIT" \
    && git checkout -q FETCH_HEAD \
    && ./configure --target-list=xtensa-softmmu \
                   --prefix=/opt/espressif-qemu \
                   --without-default-features \
                   --enable-gcrypt \
                   --enable-pixman \
                   --enable-slirp \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/espressif-qemu


# ESP-IDF releases containing release/v6.0 merge 1f8d24ceeb7 or release/v6.1
# commit 83da0b33a5 ("fix(usb_phy): Fixed USB PHY clock during low-power modes")
# hang every ESP32-S3 QEMU boot with the QEMU built above: USB Serial/JTAG init
# busy-waits on I2C_MST_BBPLL_CAL_DONE, a bit Espressif's QEMU never sets
# (https://github.com/espressif/qemu/issues/193). v6.0.3 and v6.1 predate it.
# Before taking a later release, add the fix (espressif/qemu#195) to the
# apptrace branch cloned above.
# The digest keeps the image fixed even if Docker Hub re-pushes the tag.
FROM espressif/idf:v6.0.3@sha256:54278f2c01e6e759502e2f04c9103589c17528923426f4d63193490c7a08f555

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    ccache \
    curl \
    libgcrypt20 \
    libglib2.0-0 \
    libpixman-1-0 \
    libslirp0 \
    locales \
    unzip

# Ubuntu's protobuf-compiler (libprotoc 3.21.12) cannot generate code for the
# vendored protobuf runtime pinned in car/components/esp-opentelemetry-cpp:
# protoc emits an exact-match version guard, and protobuf disclaims all
# cross-runtime support. Install the official release matching that pin
# instead, on PATH, in place of the apt package. Reuse the fork's own
# install script so the pinned version lives in one place.
COPY car/components/esp-opentelemetry-cpp/.devcontainer/install-protoc.sh /tmp/install-protoc.sh
RUN bash /tmp/install-protoc.sh && rm /tmp/install-protoc.sh

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

RUN mkdir -p /home/$USERNAME/.ccache && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/.ccache

RUN mkdir -p /home/$USERNAME/build && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME/build

USER $USERNAME

RUN git config --global --add safe.directory /opt/esp/idf/components/openthread/openthread
RUN echo "source $IDF_PATH/export.sh > /dev/null 2>&1" >> $HOME/.bashrc

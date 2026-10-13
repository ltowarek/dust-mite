# Same ESP-IDF image as .devcontainer/cpp/Dockerfile, which explains the pin.
FROM espressif/idf:v6.0.3@sha256:54278f2c01e6e759502e2f04c9103589c17528923426f4d63193490c7a08f555

ARG USERNAME=dustmite
ARG USER_UID=1040
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

USER $USERNAME

RUN echo "source $IDF_PATH/export.sh > /dev/null 2>&1" >> $HOME/.bashrc

COPY --chown=$USERNAME:$USERNAME scripts/run_cpp.sh /home/$USERNAME/run_cpp.sh

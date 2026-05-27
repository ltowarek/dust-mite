FROM espressif/idf:release-v6.0

ARG USERNAME=dustmite
ARG USER_UID=1040
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

USER $USERNAME

RUN echo "source $IDF_PATH/export.sh > /dev/null 2>&1" >> $HOME/.bashrc

COPY --chown=$USERNAME:$USERNAME scripts/run_cpp.sh /home/$USERNAME/run_cpp.sh

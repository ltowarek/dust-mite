FROM espressif/idf:release-v5.3

ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

ARG USERNAME=vscode
ARG USER_UID=1050
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

USER $USERNAME

RUN git config --global --add safe.directory /opt/esp/idf/components/openthread/openthread
RUN echo "source $IDF_PATH/export.sh > /dev/null 2>&1" >> $HOME/.bashrc

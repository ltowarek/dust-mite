FROM node:22-bookworm

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    locales

# WA for VSCode issue https://github.com/microsoft/vscode/issues/189924
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && locale-gen

ARG USERNAME=vscode
ARG USER_UID=1050
ARG USER_GID=$USER_UID

RUN userdel -r node \
    && groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

COPY ./web/package.json ./web/package-lock.json /tmp/web/
RUN cd /tmp/web && npm ci \
    && npx playwright install --with-deps firefox \
    && rm -rf /tmp/web

USER $USERNAME

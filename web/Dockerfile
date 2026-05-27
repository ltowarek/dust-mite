FROM node:22-bookworm-slim

ARG USERNAME=dustmite
ARG USER_UID=1040
ARG USER_GID=$USER_UID

RUN userdel -r node \
    && groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID --create-home --shell /bin/bash $USERNAME

USER $USERNAME

WORKDIR /home/$USERNAME/workspace/web

COPY --chown=$USERNAME:$USERNAME package.json package-lock.json ./
RUN npm ci

COPY --chown=$USERNAME:$USERNAME . .

EXPOSE 5173
CMD ["npx", "vp", "dev", "--port", "5173", "--host"]

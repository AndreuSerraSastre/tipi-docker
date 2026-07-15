ARG DOCKER_CLI_IMAGE=docker:29-cli
ARG OPENCLAW_BASE_IMAGE=ghcr.io/openclaw/openclaw:latest
FROM ${DOCKER_CLI_IMAGE} AS docker-cli

FROM ${OPENCLAW_BASE_IMAGE}

ARG CODEX_VERSION=0.144.4

USER root
WORKDIR /app
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins
COPY patch-spanish-realtime.mjs /tmp/patch-spanish-realtime.mjs
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl jq procps \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --prefix /tmp/codex --omit=dev --no-save --no-audit --no-fund \
        "@openai/codex@${CODEX_VERSION}" \
    && rm -rf /app/node_modules/@openai/codex* \
    && cp -a /tmp/codex/node_modules/@openai/codex* /app/node_modules/@openai/ \
    && node /tmp/patch-spanish-realtime.mjs \
    && rm -rf /tmp/codex /tmp/patch-spanish-realtime.mjs /root/.npm
RUN /app/node_modules/.bin/codex --version \
    && docker --version \
    && docker compose version
ENV PATH="/app/node_modules/.bin:${PATH}"
USER node

LABEL org.opencontainers.image.title="Tipi OpenClaw Gateway" \
      org.opencontainers.image.description="OpenClaw con Codex actualizado para GPT-5.6 Luna"

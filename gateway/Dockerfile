ARG OPENCLAW_BASE_IMAGE=ghcr.io/openclaw/openclaw:latest
FROM ${OPENCLAW_BASE_IMAGE}

ARG CODEX_VERSION=0.144.3

USER root
WORKDIR /app
COPY patch-spanish-realtime.mjs /tmp/patch-spanish-realtime.mjs
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl docker.io jq procps \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --prefix /tmp/codex --omit=dev --no-save --no-audit --no-fund \
        "@openai/codex@${CODEX_VERSION}" \
    && rm -rf /app/node_modules/@openai/codex* \
    && cp -a /tmp/codex/node_modules/@openai/codex* /app/node_modules/@openai/ \
    && node /tmp/patch-spanish-realtime.mjs \
    && rm -rf /tmp/codex /tmp/patch-spanish-realtime.mjs /root/.npm
USER node

LABEL org.opencontainers.image.title="Tipi OpenClaw Gateway" \
      org.opencontainers.image.description="OpenClaw con Codex actualizado para GPT-5.6 Sol"

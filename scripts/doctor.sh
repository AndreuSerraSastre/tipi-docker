#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
FILES=(-f compose.yaml -f compose.registry.yaml)

test -r .env
test -d data/models/vosk-model-small-es-0.42
test -e /dev/snd
docker compose "${FILES[@]}" --profile linux-audio ps
docker compose "${FILES[@]}" --profile tools run --rm openclaw-cli doctor --non-interactive
docker compose "${FILES[@]}" --profile linux-audio exec -T tipi-voice python -m tipi_voice --list-devices


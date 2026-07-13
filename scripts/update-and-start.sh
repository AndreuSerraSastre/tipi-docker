#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

set -a
source ./.env
set +a
mkdir -p data/maintenance
printf '%s\n' running > data/maintenance/voice-desired-state

FILES=(-f compose.yaml -f compose.registry.yaml)
PROFILE=(--profile linux-audio)
old_openclaw="$(docker image inspect "$OPENCLAW_IMAGE" --format '{{.Id}}' 2>/dev/null || true)"
old_voice="$(docker image inspect "$TIPI_VOICE_IMAGE" --format '{{.Id}}' 2>/dev/null || true)"

if [[ "$OPENCLAW_IMAGE" == *:local || "$TIPI_VOICE_IMAGE" == *:local ]]; then
  FILES=(-f compose.yaml)
  update_command=(build --pull openclaw-gateway tipi-voice)
else
  update_command=(pull)
fi

if docker compose "${FILES[@]}" "${PROFILE[@]}" "${update_command[@]}"; then
  docker compose "${FILES[@]}" "${PROFILE[@]}" stop tipi-voice >/dev/null 2>&1 || true
  if docker compose "${FILES[@]}" up -d --wait --remove-orphans openclaw-gateway \
    && "$ROOT/scripts/bootstrap-openclaw.sh" \
    && "$ROOT/scripts/enable-autonomy.sh" \
    && docker compose "${FILES[@]}" "${PROFILE[@]}" up -d --wait --remove-orphans; then
    exit 0
  fi
fi

echo 'La actualización no superó las comprobaciones de salud; iniciando recuperación.' >&2
if [[ -z "$old_openclaw" || -z "$old_voice" ]]; then
  echo 'No hay dos imágenes anteriores disponibles para recuperar.' >&2
  exit 1
fi

OPENCLAW_IMAGE="$old_openclaw" TIPI_VOICE_IMAGE="$old_voice" \
  docker compose -f compose.yaml -f compose.rollback.yaml --profile linux-audio \
  up -d --wait --remove-orphans

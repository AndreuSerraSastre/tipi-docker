#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib-tipi.sh"

mkdir -p data/maintenance
printf '%s\n' running > data/maintenance/voice-desired-state

openclaw_image="$(tipi_get_env OPENCLAW_IMAGE)"
openclaw_image="${openclaw_image:-ghcr.io/andreuserrasastre/tipi-openclaw:latest}"
voice_image="$(tipi_get_env TIPI_VOICE_IMAGE)"
voice_image="${voice_image:-ghcr.io/andreuserrasastre/tipi-voice:latest}"

running_image_id() {
  local service="$1" fallback_image="$2" container_id
  container_id="$(tipi_compose --profile linux-audio ps -q "$service" 2>/dev/null || true)"
  if [[ -n "$container_id" ]]; then
    docker inspect --format '{{.Image}}' "$container_id" 2>/dev/null || true
  else
    docker image inspect "$fallback_image" --format '{{.Id}}' 2>/dev/null || true
  fi
}

old_openclaw="$(running_image_id openclaw-gateway "$openclaw_image")"
old_voice="$(running_image_id tipi-voice "$voice_image")"
state_backup='data/maintenance/last-good-openclaw.json'
state_backup_ready=0
old_gateway_container="$(tipi_compose ps -q openclaw-gateway 2>/dev/null || true)"
if [[ -n "$old_gateway_container" ]]; then
  temporary_backup="$(mktemp 'data/maintenance/openclaw.json.XXXXXX')"
  docker exec "$old_gateway_container" \
    cat /home/node/.openclaw/openclaw.json > "$temporary_backup"
  chmod 600 "$temporary_backup"
  mv "$temporary_backup" "$state_backup"
  state_backup_ready=1
fi

restore_openclaw_config() {
  (( state_backup_ready )) && [[ -f "$state_backup" && -n "$old_openclaw" ]] || return 0
  docker run --rm --user root -i \
    -v "$ROOT/data/openclaw:/state" \
    --entrypoint sh "$old_openclaw" \
    -c 'umask 077; cat > /state/openclaw.json.restore && mv /state/openclaw.json.restore /state/openclaw.json' \
    < "$state_backup"
}

update_failed=0
if tipi_is_local_image "$openclaw_image"; then
  tipi_compose build --pull openclaw-gateway || update_failed=1
else
  tipi_compose pull openclaw-gateway openclaw-cli || update_failed=1
fi
if tipi_is_local_image "$voice_image"; then
  tipi_compose build --pull tipi-voice || update_failed=1
else
  tipi_compose pull tipi-voice || update_failed=1
fi

if (( update_failed )); then
  if [[ -z "$old_openclaw" || -z "$old_voice" ]]; then
    echo 'No se pudieron obtener las imágenes y no hay una versión local completa.' >&2
    exit 1
  fi
  echo 'No se pudo comprobar una actualización; se probará la versión local existente.' >&2
fi

candidate_openclaw="$(docker image inspect "$openclaw_image" --format '{{.Id}}' 2>/dev/null || true)"
candidate_voice="$(docker image inspect "$voice_image" --format '{{.Id}}' 2>/dev/null || true)"
rejected_file='data/maintenance/rejected-images'
candidate_pair="$candidate_openclaw $candidate_voice"
if [[ -n "$candidate_openclaw" && -n "$candidate_voice" \
  && -n "$old_openclaw" && -n "$old_voice" \
  && "$old_openclaw $old_voice" != "$candidate_pair" \
  && -f "$rejected_file" \
  && "$(tr -d '\r\n' < "$rejected_file")" == "$candidate_pair" ]]; then
  echo 'La versión publicada ya falló antes; se mantiene la última versión sana.' >&2
  OPENCLAW_IMAGE="$old_openclaw" TIPI_VOICE_IMAGE="$old_voice" \
    docker compose -f compose.yaml -f compose.rollback.yaml --profile linux-audio \
    up -d --wait --remove-orphans
  "$ROOT/scripts/doctor.sh"
  exit 0
fi

if tipi_compose up -d --wait --remove-orphans openclaw-gateway \
  && "$ROOT/scripts/bootstrap-openclaw.sh" \
  && "$ROOT/scripts/enable-autonomy.sh"; then
  if tipi_compose --profile linux-audio up -d --remove-orphans \
    && tipi_approve_voice_device \
    && tipi_compose --profile linux-audio up -d --wait --remove-orphans \
    && "$ROOT/scripts/doctor.sh"; then
    rm -f "$rejected_file"
    exit 0
  fi
fi

echo 'La versión candidata no superó las comprobaciones; iniciando recuperación.' >&2
if [[ -z "$old_openclaw" || -z "$old_voice" ]]; then
  echo 'No hay dos imágenes anteriores disponibles para recuperar.' >&2
  exit 1
fi
if [[ -n "$candidate_openclaw" && -n "$candidate_voice" ]]; then
  printf '%s\n' "$candidate_pair" > "$rejected_file"
  chmod 600 "$rejected_file"
fi
restore_openclaw_config

if OPENCLAW_IMAGE="$old_openclaw" TIPI_VOICE_IMAGE="$old_voice" \
  docker compose -f compose.yaml -f compose.rollback.yaml --profile linux-audio \
  up -d --wait --remove-orphans \
  && "$ROOT/scripts/doctor.sh"; then
  echo 'Recuperación completada con las imágenes anteriores.' >&2
  exit 0
fi

echo 'La recuperación automática también ha fallado.' >&2
exit 1

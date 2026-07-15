#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK=/tmp/tipi-wake-room-test
CAPTURE_DEVICE="${1:-}"
PLAYBACK_DEVICE="${2:-}"
RECORD_PID=''

cd "$ROOT"
source "$ROOT/scripts/lib-tipi.sh"

for command_name in aplay arecord docker espeak-ng python3; do
  command -v "$command_name" >/dev/null || {
    echo "Falta la dependencia de diagnóstico: $command_name" >&2
    exit 1
  }
done

voice_container="$(tipi_compose --profile linux-audio ps -q tipi-voice)"
[[ -n "$voice_container" ]] || {
  echo 'Tipi Voice debe estar arrancado antes de la prueba.' >&2
  exit 1
}
voice_image="$(docker inspect --format '{{.Image}}' "$voice_container")"
original_desired="$(cat data/maintenance/voice-desired-state 2>/dev/null || echo running)"

if [[ -z "$CAPTURE_DEVICE" || -z "$PLAYBACK_DEVICE" ]]; then
  mapfile -t selected_devices < <(python3 - <<'PY'
import json
import re
from pathlib import Path

health = json.loads(Path("data/voice/tipi-voice.health").read_text())
for key in ("inputDevice", "outputDevice"):
    match = re.search(r"\(hw:(\d+,\d+)\)", str(health.get(key, "")))
    print(f"hw:{match.group(1)}" if match else "")
PY
  )
  CAPTURE_DEVICE="${CAPTURE_DEVICE:-${selected_devices[0]:-}}"
  PLAYBACK_DEVICE="${PLAYBACK_DEVICE:-${selected_devices[1]:-}}"
fi
[[ -n "$CAPTURE_DEVICE" && -n "$PLAYBACK_DEVICE" ]] || {
  echo 'No se pudieron deducir los dispositivos ALSA.' >&2
  echo 'Uso: scripts/test-wake-room.sh hw:TARJETA,DISPOSITIVO hw:TARJETA,DISPOSITIVO' >&2
  exit 1
}

finish() {
  local status="$1" container_id health restored=0
  trap - EXIT
  set +e
  if [[ -n "$RECORD_PID" ]] && kill -0 "$RECORD_PID" 2>/dev/null; then
    kill "$RECORD_PID" 2>/dev/null
    wait "$RECORD_PID" 2>/dev/null
  fi
  cd "$ROOT" || status=1
  printf '%s\n' "$original_desired" > data/maintenance/voice-desired-state
  if [[ "$original_desired" == running ]]; then
    tipi_compose --profile linux-audio up -d --no-deps tipi-voice >/dev/null
    for _ in $(seq 1 60); do
      container_id="$(tipi_compose --profile linux-audio ps -q tipi-voice)"
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null)"
      if [[ "$health" == healthy ]]; then
        restored=1
        break
      fi
      sleep 2
    done
    if (( restored )); then
      echo 'ROOM_TEST_VOICE_RESTORED=healthy'
    else
      echo 'No se pudo restaurar Tipi Voice tras la prueba.' >&2
      status=1
    fi
  else
    tipi_compose --profile linux-audio stop -t 15 tipi-voice >/dev/null
    echo 'ROOM_TEST_VOICE_RESTORED=stopped'
  fi
  exit "$status"
}
trap 'finish $?' EXIT

if [[ -e "$WORK" ]]; then
  resolved="$(readlink -f -- "$WORK")"
  [[ "$resolved" == "$WORK" ]] || {
    echo "Ruta temporal inesperada: $resolved" >&2
    exit 1
  }
  backup="${WORK}.previous.$(date +%Y%m%d-%H%M%S)"
  mv -- "$WORK" "$backup"
  echo "Prueba anterior conservada en $backup"
fi
install -d -m 0755 "$WORK"

printf '%s\n' stopped > data/maintenance/voice-desired-state
tipi_compose --profile linux-audio stop -t 15 tipi-voice >/dev/null
sleep 2

espeak-ng -v es -s 140 -a 200 -w "$WORK/clean.wav" 'Tipi'
espeak-ng -v es -s 145 -a 175 -w "$WORK/background.wav" 'Estamos explicando'
espeak-ng -v es -s 145 -a 190 -w "$WORK/negative.wav" \
  'Si, ese tipo tipico es para ti.'

docker run --rm --network none --read-only --tmpfs /tmp:size=64m \
  --user "$(id -u):$(id -g)" -e PYTHONPATH=/app \
  -v "$ROOT/data/models:/models:ro" -v "$WORK:/work" \
  -v "$ROOT/voice/tools/wake_room_test.py:/tool.py:ro" \
  --entrypoint python "$voice_image" /tool.py generate

capture_track() {
  local scenario="$1" playback="$WORK/$1-playback.wav"
  local recording="$WORK/$1-room.wav" play_seconds record_seconds
  play_seconds="$(python3 -c 'import math,sys,wave; w=wave.open(sys.argv[1]); print(math.ceil(w.getnframes()/w.getframerate()))' "$playback")"
  record_seconds=$((play_seconds + 2))
  arecord -q -D "$CAPTURE_DEVICE" -t wav -f S16_LE -r 48000 -c 1 \
    -d "$record_seconds" "$recording" &
  RECORD_PID=$!
  sleep 0.5
  aplay -q -D "$PLAYBACK_DEVICE" "$playback"
  wait "$RECORD_PID"
  RECORD_PID=''
  docker run --rm --network none --read-only --tmpfs /tmp:size=64m \
    -e PYTHONPATH=/app -v "$ROOT/data/models:/models:ro" -v "$WORK:/work:ro" \
    -v "$ROOT/voice/tools/wake_room_test.py:/tool.py:ro" \
    --entrypoint python "$voice_image" /tool.py detect \
    --input "/work/$1-room.wav" --scenario "$scenario"
}

echo "Prueba de sala: captura=$CAPTURE_DEVICE salida=$PLAYBACK_DEVICE"
capture_track negative
capture_track positive

resolved="$(readlink -f -- "$WORK")"
[[ "$resolved" == "$WORK" ]] || {
  echo "No se elimina una ruta temporal inesperada: $resolved" >&2
  exit 1
}
find "$WORK" -depth -mindepth 1 -delete
rmdir "$WORK"
echo 'ROOM_ACOUSTIC_WAKE_TEST_OK'

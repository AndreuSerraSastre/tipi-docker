#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib-tipi.sh"

SUDO=()
if (( EUID != 0 )); then
  command -v sudo >/dev/null || {
    echo 'Se necesita sudo para preparar permisos y el servicio systemd.' >&2
    exit 1
  }
  SUDO=(sudo)
fi

missing_commands=()
for command_name in curl unzip openssl python3 timeout; do
  command -v "$command_name" >/dev/null || missing_commands+=("$command_name")
done
if (( ${#missing_commands[@]} )); then
  if command -v apt-get >/dev/null; then
    echo "Instalando dependencias de host: ${missing_commands[*]}"
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y \
      ca-certificates coreutils curl openssl python3 unzip
  else
    echo "Faltan utilidades de host: ${missing_commands[*]}." >&2
    exit 1
  fi
fi

[[ "$(uname -s)" == Linux ]] || { echo 'Este asistente requiere Linux.' >&2; exit 1; }
command -v docker >/dev/null || {
  echo 'Falta Docker Engine. Instálalo y añade este usuario al grupo docker.' >&2
  exit 1
}
command -v systemctl >/dev/null || {
  echo 'Se necesita systemd para garantizar el arranque automático.' >&2
  exit 1
}
docker compose version >/dev/null
docker info >/dev/null || {
  echo 'El usuario actual no puede acceder al daemon Docker.' >&2
  exit 1
}
[[ "$(uname -m)" == aarch64 || "$(uname -m)" == x86_64 ]] || {
  echo 'Se necesita Linux de 64 bits (aarch64 o x86_64).' >&2
  exit 1
}
(( 10#$(date +%Y) >= 2025 )) || {
  echo 'La fecha del sistema es incorrecta; sincronízala antes de autorizar OpenAI.' >&2
  exit 1
}
available_kib="$(df -Pk "$ROOT" | awk 'NR == 2 { print $4 }')"
(( available_kib >= 3 * 1024 * 1024 )) || {
  echo 'Se necesitan al menos 3 GB libres para imágenes, modelo y actualizaciones.' >&2
  exit 1
}
[[ -e /dev/snd ]] || {
  echo 'No aparece /dev/snd. Conecta y habilita el micrófono y los altavoces.' >&2
  exit 1
}

umask 077
if [[ ! -f .env ]]; then
  cp .env.example .env
fi
chmod 600 .env
if [[ -z "$(tipi_get_env OPENCLAW_GATEWAY_TOKEN)" ]]; then
  tipi_set_env OPENCLAW_GATEWAY_TOKEN "$(openssl rand -hex 32)"
fi

mkdir -p data/openclaw data/models data/voice
[[ -f data/openclaw/openclaw.json ]] || cp config/openclaw.json data/openclaw/openclaw.json
"${SUDO[@]}" chown -R 1000:1000 data/openclaw
"${SUDO[@]}" chown -R 10001:10001 data/voice

saved_realtime_key="$(tipi_get_env OPENAI_REALTIME_API_KEY)"
if [[ -z "$saved_realtime_key" ]]; then
  echo
  echo 'Paso 1 de 4: introduce la API key que usará OpenAI Realtime.'
  read -r -s -p 'OPENAI_REALTIME_API_KEY (no se mostrará): ' realtime_key
  echo
  [[ "$realtime_key" == sk-* ]] || { echo 'La clave no parece válida.' >&2; exit 1; }
  tipi_set_env OPENAI_REALTIME_API_KEY "$realtime_key"
  saved_realtime_key="$realtime_key"
  unset realtime_key
fi

if ! tipi_compose pull openclaw-gateway openclaw-cli; then
  echo 'La imagen publicada de OpenClaw no está disponible; construyéndola localmente.' >&2
  tipi_set_env OPENCLAW_IMAGE 'tipi-openclaw:local'
  tipi_compose build --pull openclaw-gateway
fi
if ! tipi_compose pull tipi-voice; then
  echo 'La imagen publicada de voz no está disponible; construyéndola localmente.' >&2
  tipi_set_env TIPI_VOICE_IMAGE 'tipi-voice:local'
  tipi_compose build --pull tipi-voice
fi

tipi_compose up -d --wait openclaw-gateway

auth_json="$(tipi_compose --profile tools run --rm --no-deps \
  openclaw-cli models auth list --json --provider openai)"
if ! grep -q '"type"[[:space:]]*:[[:space:]]*"oauth"' <<<"$auth_json"; then
  echo
  echo 'Paso 2 de 4: inicia sesión en OpenAI con la URL y el código que aparecerán a continuación.'
  tipi_compose --profile tools run --rm --no-deps \
    openclaw-cli models auth login --provider openai --device-code
fi
unset auth_json

echo
echo 'Paso 3 de 4: preparando el reconocimiento, el micrófono y los altavoces.'
"$ROOT/scripts/download-model.sh"
tipi_compose --profile linux-audio run --rm --no-deps tipi-voice --list-devices
devices_json="$(tipi_compose --profile linux-audio run --rm --no-deps \
  tipi-voice --list-devices-json)"

suggest_device() {
  local direction="$1"
  python3 -c '
import json, re, sys
direction = sys.argv[1]
channel = "inputChannels" if direction == "entrada" else "outputChannels"
data = json.load(sys.stdin).get("devices", [])
candidates = []
for item in data:
    if item.get(channel, 0) < 1:
        continue
    name = str(item.get("name", ""))
    lowered = name.casefold()
    score = (120 if "usb" in lowered else 0) + (30 if "(hw:" in lowered else 0)
    if "hdmi" in lowered or "dmix" in lowered:
        score -= 80
    candidates.append((score, name))
candidates.sort(reverse=True)
if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
    selector = re.sub(r"\s*[:\-]*\s*\(hw:.*$", "", candidates[0][1]).strip()
    print(selector or candidates[0][1])
' "$direction" <<<"$devices_json"
}

if [[ -z "$(tipi_get_env TIPI_INPUT_DEVICE)" ]]; then
  input_device="$(suggest_device entrada)"
  if [[ -z "$input_device" ]]; then
    read -r -p 'Número o parte estable del nombre del micrófono: ' input_device
  else
    echo "Micrófono seleccionado automáticamente: $input_device"
  fi
  [[ -n "$input_device" ]] || { echo 'Debes elegir un micrófono.' >&2; exit 1; }
  tipi_set_env TIPI_INPUT_DEVICE "$input_device"
fi
if [[ -z "$(tipi_get_env TIPI_OUTPUT_DEVICE)" ]]; then
  output_device="$(suggest_device salida)"
  if [[ -z "$output_device" ]]; then
    read -r -p 'Número o parte estable del nombre de los altavoces: ' output_device
  else
    echo "Altavoces seleccionados automáticamente: $output_device"
  fi
  [[ -n "$output_device" ]] || { echo 'Debes elegir unos altavoces.' >&2; exit 1; }
  tipi_set_env TIPI_OUTPUT_DEVICE "$output_device"
fi
unset devices_json saved_realtime_key

echo
echo 'Paso 4 de 4: arrancando y comprobando Tipi.'
model="$(tipi_get_env TIPI_OPENCLAW_MODEL)"
model="${model:-openai/gpt-5.6-luna}"
tipi_compose --profile tools run --rm --no-deps openclaw-cli models set "$model"
tipi_compose up -d --force-recreate --wait openclaw-gateway
"$ROOT/scripts/bootstrap-openclaw.sh"
"$ROOT/scripts/enable-autonomy.sh"
mkdir -p data/maintenance
printf '%s\n' running > data/maintenance/voice-desired-state
tipi_compose --profile linux-audio up -d tipi-voice
tipi_approve_voice_device
tipi_compose --profile linux-audio up -d --wait tipi-voice

service_template="$ROOT/systemd/tipi.service"
service_target='/etc/systemd/system/tipi.service'
service_user="${SUDO_USER:-$(id -un)}"
[[ "$service_user" != root ]] || service_user="$(stat -c '%U' "$ROOT")"
service_group="$(id -gn "$service_user")"
"${SUDO[@]}" chown "$service_user:$service_group" .env
"${SUDO[@]}" chown -R "$service_user:$service_group" data/maintenance
sed \
  -e "s|__TIPI_DIR__|$ROOT|g" \
  -e "s|__TIPI_USER__|$service_user|g" \
  -e "s|__TIPI_GROUP__|$service_group|g" \
  "$service_template" | "${SUDO[@]}" tee "$service_target" >/dev/null
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable tipi.service
"${SUDO[@]}" systemctl restart tipi.service
"$ROOT/scripts/doctor.sh"

echo
echo 'Tipi está instalado, sano y configurado para arrancar automáticamente.'
echo "Diagnóstico: $ROOT/scripts/doctor.sh"

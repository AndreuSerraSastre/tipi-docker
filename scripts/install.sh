#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

for command_name in docker curl unzip openssl sudo python3; do
  command -v "$command_name" >/dev/null || {
    echo "Falta $command_name." >&2
    exit 1
  }
done
docker compose version >/dev/null
[[ "$(uname -m)" == 'aarch64' || "$(uname -m)" == 'x86_64' ]] || {
  echo 'Se necesita Linux de 64 bits (aarch64 o x86_64).' >&2
  exit 1
}
[[ -e /dev/snd ]] || {
  echo 'No aparece /dev/snd. Conecta y habilita el micrófono y los altavoces.' >&2
  exit 1
}

set_env() {
  local name="$1" value="$2" source='.env' temporary
  temporary="$(mktemp .env.XXXXXX)"
  awk -v name="$name" -v value="$value" '
    BEGIN { found = 0 }
    index($0, name "=") == 1 { print name "=" value; found = 1; next }
    { print }
    END { if (!found) print name "=" value }
  ' "$source" > "$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$source"
}

get_env() {
  local name="$1"
  awk -v name="$name" 'index($0, name "=") == 1 { print substr($0, length(name) + 2); exit }' .env
}

umask 077
if [[ ! -f .env ]]; then
  cp .env.example .env
  set_env OPENCLAW_GATEWAY_TOKEN "$(openssl rand -hex 32)"
fi

mkdir -p data/openclaw data/models data/voice
[[ -f data/openclaw/openclaw.json ]] || cp config/openclaw.json data/openclaw/openclaw.json
sudo chown -R 1000:1000 data/openclaw
sudo chown -R 10001:10001 data/voice

saved_realtime_key="$(get_env OPENAI_REALTIME_API_KEY)"
if [[ -z "$saved_realtime_key" ]]; then
  echo
  echo 'Paso 1 de 4: introduce la API key que usará OpenAI Realtime.'
  read -r -s -p 'OPENAI_REALTIME_API_KEY (no se mostrará): ' realtime_key
  echo
  [[ "$realtime_key" == sk-* ]] || { echo 'La clave no parece válida.' >&2; exit 1; }
  set_env OPENAI_REALTIME_API_KEY "$realtime_key"
  saved_realtime_key="$realtime_key"
  unset realtime_key
fi

files=(-f compose.yaml -f compose.registry.yaml)
if ! docker compose "${files[@]}" --profile linux-audio pull; then
  echo 'Las imagenes publicadas no estan disponibles; construyendolas localmente.' >&2
  set_env OPENCLAW_IMAGE 'tipi-openclaw:local'
  set_env TIPI_VOICE_IMAGE 'tipi-voice:local'
  files=(-f compose.yaml)
  docker compose "${files[@]}" --profile linux-audio build --pull openclaw-gateway tipi-voice
fi

docker compose "${files[@]}" up -d --wait openclaw-gateway

auth_json="$(docker compose "${files[@]}" --profile tools run --rm --no-deps \
  openclaw-cli models auth list --json --provider openai)"
if ! grep -q '"type"[[:space:]]*:[[:space:]]*"oauth"' <<<"$auth_json"; then
  echo
  echo 'Paso 2 de 4: inicia sesión en OpenAI con el código que aparecerá a continuación.'
  docker compose "${files[@]}" --profile tools run --rm --no-deps \
    openclaw-cli models auth login --provider openai --device-code
fi

echo
echo 'Paso 3 de 4: preparando el reconocimiento, el micrófono y los altavoces.'
"$ROOT/scripts/download-model.sh"
docker compose "${files[@]}" --profile linux-audio run --rm --no-deps \
  tipi-voice --list-devices

if [[ -z "$(get_env TIPI_INPUT_DEVICE)" ]]; then
  read -r -p 'Número o parte del nombre del micrófono: ' input_device
  [[ -n "$input_device" ]] || { echo 'Debes elegir un micrófono.' >&2; exit 1; }
  set_env TIPI_INPUT_DEVICE "$input_device"
fi
if [[ -z "$(get_env TIPI_OUTPUT_DEVICE)" ]]; then
  read -r -p 'Número o parte del nombre de los altavoces: ' output_device
  [[ -n "$output_device" ]] || { echo 'Debes elegir unos altavoces.' >&2; exit 1; }
  set_env TIPI_OUTPUT_DEVICE "$output_device"
fi

echo
echo 'Paso 4 de 4: arrancando y comprobando Tipi.'
docker compose "${files[@]}" up -d --wait openclaw-gateway
docker compose "${files[@]}" --profile tools run --rm --no-deps \
  openclaw-cli models set openai/gpt-5.6-sol
docker compose "${files[@]}" up -d --force-recreate --wait openclaw-gateway
"$ROOT/scripts/bootstrap-openclaw.sh"
"$ROOT/scripts/enable-autonomy.sh"
mkdir -p data/maintenance
printf '%s\n' running > data/maintenance/voice-desired-state
docker compose "${files[@]}" --profile linux-audio up -d tipi-voice

request_id=''
for _ in {1..20}; do
  devices_json="$(docker compose "${files[@]}" --profile tools run --rm --no-deps \
    openclaw-cli devices list --json 2>/dev/null || true)"
  request_id="$(python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
for item in data.get("pending", []):
    if item.get("displayName") == "Tipi Voice":
        print(item.get("requestId", ""))
        break
' <<<"$devices_json")"
  [[ -n "$request_id" ]] && break
  sleep 2
done
if [[ -n "$request_id" ]]; then
  docker compose "${files[@]}" --profile tools run --rm --no-deps \
    openclaw-cli devices approve "$request_id"
fi

"$ROOT/scripts/update-and-start.sh"

service_template="$ROOT/systemd/tipi.service"
service_target='/etc/systemd/system/tipi.service'
sed "s|__TIPI_DIR__|$ROOT|g" "$service_template" | sudo tee "$service_target" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable tipi.service

echo
echo 'Tipi está instalado y se actualizará de forma segura en cada arranque.'
echo "Diagnóstico: $ROOT/scripts/doctor.sh"

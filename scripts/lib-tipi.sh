#!/usr/bin/env bash

if [[ -n "${TIPI_LIB_LOADED:-}" ]]; then
  return 0
fi
TIPI_LIB_LOADED=1

TIPI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIPI_COMPOSE=(docker compose -f "$TIPI_ROOT/compose.yaml")

tipi_compose() {
  "${TIPI_COMPOSE[@]}" "$@"
}

tipi_get_env() {
  local name="$1" file="${2:-$TIPI_ROOT/.env}" value
  [[ -f "$file" ]] || return 0
  value="$(awk -v name="$name" 'index($0, name "=") == 1 {
    print substr($0, length(name) + 2)
    exit
  }' "$file")"
  value="${value%$'\r'}"
  if [[ ${#value} -ge 2 ]]; then
    if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi
  printf '%s' "$value"
}

tipi_set_env() {
  local name="$1" value="$2" source="$TIPI_ROOT/.env" temporary
  [[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]] || {
    echo "Nombre de variable no válido: $name" >&2
    return 1
  }
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || {
    echo "El valor de $name contiene un salto de línea" >&2
    return 1
  }
  temporary="$(mktemp "$TIPI_ROOT/.env.XXXXXX")"
  awk -v name="$name" -v value="$value" '
    BEGIN { found = 0 }
    index($0, name "=") == 1 { print name "=" value; found = 1; next }
    { print }
    END { if (!found) print name "=" value }
  ' "$source" > "$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$source"
}

tipi_is_local_image() {
  [[ "$1" == *:local ]]
}

tipi_service_health() {
  local service="$1" container_id
  container_id="$(tipi_compose --profile linux-audio ps -q "$service" 2>/dev/null || true)"
  [[ -n "$container_id" ]] || return 1
  [[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null)" == healthy ]]
}

tipi_approve_voice_device() {
  local expected_device devices_json request_id voice_container
  for _ in {1..8}; do
    tipi_service_health tipi-voice && return 0
    sleep 1
  done
  voice_container="$(tipi_compose --profile linux-audio ps -q tipi-voice 2>/dev/null || true)"
  [[ -n "$voice_container" ]] || {
    echo 'La voz no ha creado su identidad de dispositivo.' >&2
    return 1
  }
  expected_device="$(docker exec "$voice_container" python -c '
import json
print(json.load(open("/state/device-identity.json", encoding="utf-8")).get("deviceId", ""))
' 2>/dev/null || true)"
  [[ -n "$expected_device" ]] || return 1
  devices_json="$(timeout 45 "${TIPI_COMPOSE[@]}" exec -T openclaw-gateway \
    node dist/index.js devices list --json 2>/dev/null || true)"
  request_id="$(python3 -c '
import json, sys
raw = sys.stdin.read()
start = raw.find("{")
if start < 0:
    raise SystemExit(0)
data = json.loads(raw[start:])
expected = sys.argv[1]
for item in data.get("pending", []):
    if item.get("deviceId") == expected and item.get("displayName") == "Tipi Voice":
        print(item.get("requestId", ""))
        break
' "$expected_device" <<<"$devices_json")"
  unset devices_json expected_device
  if [[ -z "$request_id" ]]; then
    tipi_service_health tipi-voice && return 0
    echo 'La voz no está sana y OpenClaw no muestra una solicitud de emparejamiento coincidente.' >&2
    return 1
  fi
  timeout 45 "${TIPI_COMPOSE[@]}" exec -T openclaw-gateway \
    node dist/index.js devices approve "$request_id" >/dev/null
  echo 'Identidad local de Tipi Voice aprobada.'
}

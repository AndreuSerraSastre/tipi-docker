#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib-tipi.sh"

for command_name in docker python3 timeout; do
  command -v "$command_name" >/dev/null || {
    echo "Falta $command_name." >&2
    exit 1
  }
done

[[ -r .env ]] || { echo 'No se puede leer .env.' >&2; exit 1; }
[[ -d data/models/vosk-model-small-es-0.42 ]] || {
  echo 'Falta el modelo Vosk.' >&2
  exit 1
}
[[ -e /dev/snd ]] || { echo 'No aparece /dev/snd.' >&2; exit 1; }

tipi_compose --profile linux-audio config --quiet

for service in openclaw-gateway tipi-voice; do
  container_id="$(tipi_compose --profile linux-audio ps -q "$service")"
  [[ -n "$container_id" ]] || {
    echo "El servicio $service no está creado." >&2
    exit 1
  }
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
  [[ "$health" == healthy ]] || {
    echo "El servicio $service no está sano: $health" >&2
    exit 1
  }
  echo "OK: $service está sano."
done

expected_model="$(tipi_get_env TIPI_OPENCLAW_MODEL)"
expected_model="${expected_model:-openai/gpt-5.6-luna}"
expected_thinking="$(tipi_get_env TIPI_OPENCLAW_THINKING)"
expected_thinking="${expected_thinking:-low}"
expected_realtime_reasoning="$(tipi_get_env TIPI_REALTIME_REASONING)"
expected_realtime_reasoning="${expected_realtime_reasoning:-low}"
effective_config="$(mktemp)"
catalog_file="$(mktemp)"
trap 'rm -f "$effective_config" "$catalog_file"' EXIT
timeout 20 "${TIPI_COMPOSE[@]}" exec -T openclaw-gateway \
  cat /home/node/.openclaw/openclaw.json > "$effective_config"
python3 - "$effective_config" "$expected_model" "$expected_thinking" \
  "$expected_realtime_reasoning" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
model = data.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")
thinking = data.get("agents", {}).get("defaults", {}).get("thinkingDefault")
consult = data.get("talk", {}).get("consultThinkingLevel")
realtime = (
    data.get("talk", {})
    .get("realtime", {})
    .get("providers", {})
    .get("openai", {})
    .get("reasoningEffort")
)
if model != sys.argv[2]:
    raise SystemExit(f"Modelo inesperado: {model!r}")
if thinking != sys.argv[3] or consult != sys.argv[3]:
    raise SystemExit(
        f"Razonamiento inesperado: agente={thinking!r}, consulta={consult!r}"
    )
if realtime != sys.argv[4]:
    raise SystemExit(f"Razonamiento Realtime inesperado: {realtime!r}")
print(
    f"OK: OpenClaw usa {model}; agente, consulta y Realtime en "
    f"{thinking}/{consult}/{realtime}."
)
PY

timeout 45 "${TIPI_COMPOSE[@]}" exec -T openclaw-gateway \
  node dist/index.js models list --json > "$catalog_file"
python3 - "$catalog_file" "$expected_model" <<'PY'
import json
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text(encoding="utf-8")
start = raw.find("{")
if start < 0:
    raise SystemExit("OpenClaw no devolvió el catálogo de modelos")
models = json.loads(raw[start:]).get("models", [])
entry = next((item for item in models if item.get("key") == sys.argv[2]), None)
if not entry or not entry.get("available") or entry.get("missing"):
    raise SystemExit(f"El modelo {sys.argv[2]} no está autenticado o disponible")
print(f"OK: {sys.argv[2]} está autenticado y disponible.")
PY

# Las variables de este bloque deben expandirse dentro del contenedor.
# shellcheck disable=SC2016
timeout 20 "${TIPI_COMPOSE[@]}" exec -T openclaw-gateway sh -eu -c '
workspace=/home/node/.openclaw/workspace
for file in IDENTITY.md USER.md MEMORY.md AGENTS.md BOOT.md HEARTBEAT.md CARETAKER_LESSONS.md; do
  test -s "$workspace/$file"
done
test -s "$workspace/.tipi-bootstrap-v1"
test -s "$workspace/.tipi-autonomy-v1"
grep -q TIPI_AUTONOMY_V1 "$workspace/AGENTS.md"
'
echo 'OK: identidad, memoria y programa de autocuidado están completos.'

timeout 45 "${TIPI_COMPOSE[@]}" --profile linux-audio exec -T tipi-voice \
  python -m tipi_voice --check
voice_container="$(tipi_compose --profile linux-audio ps -q tipi-voice)"
[[ "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$voice_container")" == true ]] || {
  echo 'La raíz del contenedor de voz no es de solo lectura.' >&2
  exit 1
}
if docker exec "$voice_container" printenv OPENAI_REALTIME_API_KEY >/dev/null 2>&1; then
  echo 'La API key de Realtime está expuesta al contenedor de voz.' >&2
  exit 1
fi
echo 'OK: voz aislada, raíz de solo lectura y sin API key de Realtime.'
python3 <<'PY'
import json
import time
from pathlib import Path

path = Path("data/voice/tipi-voice.health")
try:
    raw = path.read_text(encoding="utf-8").strip()
except OSError as error:
    raise SystemExit(f"Estado de voz ilegible: {error}")
if not raw:
    age = time.time() - path.stat().st_mtime
    if not 0 <= age < 35:
        raise SystemExit(f"Estado de voz antiguo obsoleto: {age:.1f} segundos")
    print("OK: archivo de salud antiguo vigente; se actualizará con la nueva imagen.")
    raise SystemExit(0)
try:
    health = json.loads(raw)
except ValueError as error:
    raise SystemExit(f"Estado de voz ilegible: {error}")
age = time.time() - float(health.get("timestamp", 0))
mtime_age = time.time() - path.stat().st_mtime
if not 0 <= age < 35:
    if not 0 <= mtime_age < 35:
        raise SystemExit(f"Estado de voz obsoleto: {age:.1f} segundos")
    # Las imágenes anteriores mantenían la salud con touch(). Durante un
    # rollback pueden refrescar el mtime de un JSON escrito por la versión nueva.
    print("OK: salud actualizada por una imagen anterior compatible.")
if not health.get("gatewayConnected"):
    raise SystemExit("La voz no figura conectada al Gateway")
input_device = str(health.get("inputDevice") or "").strip()
output_device = str(health.get("outputDevice") or "").strip()
if not input_device or not output_device:
    raise SystemExit("La voz no informa de micrófono y altavoces activos")
version = str(health.get("version") or "desconocida")
print(
    f"OK: Tipi Voice {version}; entrada={input_device}; salida={output_device}; "
    f"niveles={health.get('microphoneLevel')}/{health.get('outputLevel')}."
)
PY

if command -v systemctl >/dev/null; then
  systemctl list-unit-files tipi.service --no-legend 2>/dev/null | grep -q '^tipi.service' || {
    echo 'tipi.service no está instalado.' >&2
    exit 1
  }
  systemctl is-enabled --quiet tipi.service
  service_state="$(systemctl is-active tipi.service 2>/dev/null || true)"
  [[ "$service_state" == active || "$service_state" == activating ]] || {
    echo "tipi.service no está activo: $service_state" >&2
    exit 1
  }
  service_user="$(systemctl show tipi.service -p User --value)"
  service_directory="$(systemctl show tipi.service -p WorkingDirectory --value)"
  [[ -n "$service_user" ]] || {
    echo 'tipi.service no declara el usuario de servicio.' >&2
    exit 1
  }
  [[ "$service_directory" == "$ROOT" ]] || {
    echo "tipi.service apunta a un directorio inesperado: $service_directory" >&2
    exit 1
  }
  echo "OK: tipi.service está habilitado y $service_state como $service_user."
  systemctl list-unit-files tipi-network-watchdog.service --no-legend 2>/dev/null \
    | grep -q '^tipi-network-watchdog.service' || {
      echo 'tipi-network-watchdog.service no está instalado.' >&2
      exit 1
    }
  systemctl is-enabled --quiet tipi-network-watchdog.service
  watchdog_state="$(systemctl is-active tipi-network-watchdog.service 2>/dev/null || true)"
  [[ "$watchdog_state" == active ]] || {
    echo "El watchdog de red no está activo: $watchdog_state" >&2
    exit 1
  }
  echo 'OK: recuperación automática tras volver Internet activa.'
fi

echo 'Diagnóstico de Tipi completado sin errores.'

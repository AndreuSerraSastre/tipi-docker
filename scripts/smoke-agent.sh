#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib-tipi.sh"

thinking="$(tipi_get_env TIPI_OPENCLAW_THINKING)"
thinking="${thinking:-low}"
message='Prueba técnica de Tipi: usa la herramienta de ejecución para consultar la hora actual del sistema con date. Explica en una frase qué verificaste y termina exactamente con TIPI_SMOKE_OK. No modifiques nada.'

result="$(timeout 180 "${TIPI_COMPOSE[@]}" --profile tools run --rm --no-deps \
  openclaw-cli agent \
  --session-key agent:main:tipi-smoke-test \
  --thinking "$thinking" \
  --timeout 150 \
  --message "$message")"
printf '%s\n' "$result"
grep -q 'TIPI_SMOKE_OK' <<<"$result" || {
  echo 'El agente no completó la prueba de herramientas.' >&2
  exit 1
}
echo 'Prueba real de modelo y herramientas: OK.'

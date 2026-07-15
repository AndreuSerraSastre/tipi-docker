#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib-tipi.sh"

marker='data/openclaw/workspace/.tipi-autonomy-v1'
agents='data/openclaw/workspace/AGENTS.md'
boot='data/openclaw/workspace/BOOT.md'
heartbeat='data/openclaw/workspace/HEARTBEAT.md'
lessons='data/openclaw/workspace/CARETAKER_LESSONS.md'
fingerprint_files=(
  config/tipi-autonomy-request.md
  workspace/AGENTS.md
  workspace/BOOT.md
  workspace/HEARTBEAT.md
  workspace/CARETAKER_LESSONS.md
)
autonomy_fingerprint="$(sha256sum "${fingerprint_files[@]}" | awk '{print $1}' | paste -sd: -)"
if [[ -f "$marker" && "$(tr -d '\r\n' < "$marker")" == "$autonomy_fingerprint" \
  && -f "$agents" && -f "$boot" && -f "$heartbeat" && -f "$lessons" ]] \
  && grep -q 'TIPI_AUTONOMY_V1' "$agents"; then
  exit 0
fi

tipi_compose --profile tools run --rm --no-deps \
  openclaw-cli exec-policy preset yolo
tipi_compose --profile tools run --rm --no-deps \
  openclaw-cli hooks enable boot-md

mkdir -p data/maintenance
request="$(< config/tipi-autonomy-request.md)"
thinking="$(tipi_get_env TIPI_OPENCLAW_THINKING)"
thinking="${thinking:-low}"
echo 'OpenClaw está creando y probando su modo cuidador...'
tipi_compose --profile tools run --rm --no-deps \
  openclaw-cli agent \
  --session-key agent:main:tipi-autonomy-setup \
  --thinking "$thinking" \
  --timeout 600 \
  --message "$request"

if [[ ! -f "$agents" || ! -f "$boot" || ! -f "$heartbeat" || ! -f "$lessons" ]] \
  || ! grep -q 'TIPI_AUTONOMY_V1' "$agents"; then
  echo 'OpenClaw terminó, pero no dejó completas sus órdenes de autocuidado.' >&2
  exit 1
fi
printf '%s\n' "$autonomy_fingerprint" > "$marker"
echo 'Modo cuidador autónomo preparado y verificado.'

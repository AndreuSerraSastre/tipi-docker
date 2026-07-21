#!/usr/bin/env bash
set -euo pipefail

STATE_FILE="${TIPI_NETWORK_STATE_FILE:-/run/tipi-network-watchdog.state}"
CHECK_URL="${TIPI_CONNECTIVITY_URL:-https://api.openai.com/v1/models}"
INTERVAL_SECONDS="${TIPI_NETWORK_CHECK_INTERVAL_SECONDS:-10}"
FAILURES_REQUIRED="${TIPI_NETWORK_FAILURES_REQUIRED:-3}"
SUCCESSES_REQUIRED="${TIPI_NETWORK_SUCCESSES_REQUIRED:-2}"

previous='unknown'
if [[ -r "$STATE_FILE" ]]; then
  previous="$(tr -d '\r\n' < "$STATE_FILE")"
fi
[[ "$previous" == online || "$previous" == offline ]] || previous='unknown'

failures=0
successes=0

record_state() {
  local state="$1" temporary
  temporary="${STATE_FILE}.tmp"
  printf '%s\n' "$state" > "$temporary"
  chmod 644 "$temporary"
  mv "$temporary" "$STATE_FILE"
}

recover_tipi() {
  local service_state
  service_state="$(systemctl is-active tipi.service 2>/dev/null || true)"
  case "$service_state" in
    active|activating|failed)
      logger -t tipi-network-watchdog \
        'Internet recuperado; reiniciando Tipi para renovar sus sesiones externas.'
      systemctl restart --no-block tipi.service
      ;;
    *)
      logger -t tipi-network-watchdog \
        "Internet recuperado; Tipi permanece $service_state y no se inicia automaticamente."
      ;;
  esac
}

while true; do
  current="$previous"
  if curl --silent --output /dev/null \
    --connect-timeout 4 --max-time 8 "$CHECK_URL"; then
    failures=0
    successes=$((successes + 1))
    if (( successes >= SUCCESSES_REQUIRED )); then
      current='online'
    fi
  else
    successes=0
    failures=$((failures + 1))
    if (( failures >= FAILURES_REQUIRED )); then
      current='offline'
    fi
  fi

  if [[ "$current" != "$previous" ]]; then
    record_state "$current"
    if [[ "$previous" == offline && "$current" == online ]]; then
      recover_tipi
    elif [[ "$current" == offline ]]; then
      logger -t tipi-network-watchdog \
        'Internet no disponible; Tipi se recuperara cuando vuelva la conexion.'
    fi
    previous="$current"
  fi

  sleep "$INTERVAL_SECONDS"
done

#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
  health_file="${TIPI_HEALTH_FILE:-/state/tipi-voice.health}"
  rm -f -- "$health_file" "$health_file.tmp"
fi

exec python -m tipi_voice "$@"

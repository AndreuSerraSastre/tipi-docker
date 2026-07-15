#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib-tipi.sh"
mkdir -p data/maintenance
printf '%s\n' stopped > data/maintenance/voice-desired-state
tipi_compose --profile linux-audio down

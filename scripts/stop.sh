#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p data/maintenance
printf '%s\n' stopped > data/maintenance/voice-desired-state
docker compose -f compose.yaml -f compose.registry.yaml --profile linux-audio down

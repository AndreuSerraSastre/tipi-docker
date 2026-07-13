#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LATEST="$(find "$ROOT_DIR/data/voice/logs" "$ROOT_DIR/data/logs" \
  -maxdepth 1 -type f -name 'tipi-*.log' -printf '%T@ %p\n' 2>/dev/null \
  | sort -nr | head -n 1 | cut -d' ' -f2-)"

if [[ -z "$LATEST" ]]; then
  echo "Todavía no hay logs. Arranca Tipi y mantén al menos una conversación." >&2
  exit 1
fi

echo "Mostrando en directo: $LATEST"
tail -n 100 -f "$LATEST"

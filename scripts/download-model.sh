#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_NAME="vosk-model-small-es-0.42"
MODEL_DIR="$ROOT/data/models/$MODEL_NAME"
ARCHIVE="${TMPDIR:-/tmp}/$MODEL_NAME.zip"
EXPECTED="09b239888f633ef2f0b4e09736e3d9936acfd810bc65d53fad45261762c6511f"

[[ -d "$MODEL_DIR" ]] && exit 0
mkdir -p "$ROOT/data/models"
curl --fail --location --retry 3 \
  "https://alphacephei.com/vosk/models/$MODEL_NAME.zip" \
  --output "$ARCHIVE"
echo "$EXPECTED  $ARCHIVE" | sha256sum --check --status
unzip -q "$ARCHIVE" -d "$ROOT/data/models"
rm -f "$ARCHIVE"


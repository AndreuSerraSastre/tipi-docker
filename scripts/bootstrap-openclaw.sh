#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

marker='data/openclaw/workspace/.tipi-bootstrap-v1'
workspace='data/openclaw/workspace'
attestation='data/openclaw/workspace-attestations/cddce8bd7eebfe25e3f3e5cf0f37a0822fa900fa1864cc27b3e2d6b7e3fb6b4b.attested'
[[ -f "$marker" ]] && exit 0

# Migración desde la antigua carpeta superpuesta. La ruta es la atestación
# SHA-256 exacta de /home/node/.openclaw/workspace y nunca se borra si hay datos.
if [[ -f "$attestation" ]] && [[ -z "$(find "$workspace" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  rm -f -- "$attestation"
fi

files=(-f compose.yaml -f compose.registry.yaml)
run_turn() {
  docker compose "${files[@]}" --profile tools run --rm --no-deps \
    openclaw-cli agent \
    --session-key agent:main:tipi-onboarding \
    --thinking medium \
    --timeout 300 \
    --message "$1"
}

echo
echo 'OpenClaw va a conocer a Tipi mediante su conversación inicial.'
run_turn 'Hola. Acabas de iniciar por primera vez. Sigue tu ritual de BOOTSTRAP.md: preséntate y hazme las preguntas necesarias para descubrir quién eres, quién soy y para qué has sido creado. Todavía no escribas las respuestas por mí.'

echo 'Respondiendo automáticamente con la información del proyecto Tipi...'
answers="$(< config/tipi-bootstrap-answers.md)"
run_turn "$answers"

configured() {
  [[ -f "$workspace/IDENTITY.md" ]] \
    && [[ -f "$workspace/USER.md" ]] \
    && [[ -f "$workspace/MEMORY.md" ]] \
    && grep -q 'Tipi' "$workspace/IDENTITY.md" \
    && grep -q 'Andreu' "$workspace/USER.md" \
    && [[ ! -f "$workspace/BOOTSTRAP.md" ]]
}

if ! configured; then
  run_turn 'Finaliza ahora el onboarding: escribe IDENTITY.md, USER.md, SOUL.md y una MEMORY.md pública con lo que ya te he explicado; crea la nota diaria de memoria y elimina BOOTSTRAP.md. Después confirma brevemente que has terminado.'
fi
configured || {
  echo 'OpenClaw terminó el diálogo, pero no dejó completa la identidad y memoria de Tipi.' >&2
  exit 1
}

printf '%s\n' 'tipi-bootstrap-v1' > "$marker"
echo 'OpenClaw ya conoce su identidad, a Andreu y el propósito de Tipi.'

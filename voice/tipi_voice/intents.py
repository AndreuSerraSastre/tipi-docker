from __future__ import annotations

import re
import unicodedata


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()


_STOP_PHRASES = {
    "calla",
    "callate",
    "calla ya",
    "callate ya",
    "para",
    "para ya",
    "para de hablar",
    "deja de hablar",
    "deja de escuchar",
    "silencio",
    "prou",
    "atura",
    "atura t",
    "cierra la conversacion",
    "termina la conversacion",
    "que te calles",
    "para de parlar",
    "deixa de parlar",
    "deixa d escoltar",
}

_UNEXPECTED_SCRIPT_RE = re.compile(
    r"[\u0400-\u04ff\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]"
)
_LATIN_LETTER_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")


def is_stop_command(text: str) -> bool:
    """Detecta una orden inequívoca de cerrar la conversación de voz."""
    normalized = _normalize(text)
    if normalized in _STOP_PHRASES:
        return True
    if any(
        f" {phrase}" in f" {normalized}"
        for phrase in (
            "callate",
            "calla ya",
            "callate ya",
            "silencio",
            "prou",
            "atura t",
            "deja de hablar",
            "deixa de parlar",
        )
    ):
        return True
    return any(
        normalized.startswith(prefix)
        for prefix in (
            "tipi callate",
            "tipi para de hablar",
            "tipi deja de hablar",
            "tipi prou",
            "tipi atura",
            "tipi para de parlar",
            "tipi deixa de parlar",
        )
    )


def is_plausible_visitor_transcript(text: str) -> bool:
    """Descarta transcripciones claramente ajenas a español/catalán/inglés."""
    stripped = text.strip()
    if not stripped:
        return False
    unexpected = _UNEXPECTED_SCRIPT_RE.findall(stripped)
    if not unexpected:
        return True
    latin = _LATIN_LETTER_RE.findall(stripped)
    return bool(latin) and len(unexpected) <= len(latin)

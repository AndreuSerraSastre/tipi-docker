from __future__ import annotations

import re
import unicodedata


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
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


def is_stop_command(text: str) -> bool:
    """Detecta una orden inequívoca de cerrar la conversación de voz."""
    normalized = _normalize(text)
    if normalized in _STOP_PHRASES:
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

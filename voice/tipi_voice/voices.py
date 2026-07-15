from __future__ import annotations

import re
import unicodedata

AVAILABLE_REALTIME_VOICES: tuple[str, ...] = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
)

_VOICE_ALIASES = {
    "alloy": ("alloy", "aloy"),
    "ash": ("ash",),
    "ballad": ("ballad", "balad"),
    "coral": ("coral",),
    "echo": ("echo", "eco"),
    "sage": ("sage",),
    "shimmer": ("shimmer",),
    "verse": ("verse",),
    "marin": ("marin", "mari", "marina", "marine"),
    "cedar": ("cedar", "cedro"),
}


def display_voice(voice: str) -> str:
    return voice.strip().lower().capitalize()


def voice_answer_for(text: str, current_voice: str) -> str | None:
    normalized = _normalize(text)
    requested = _requested_voice(normalized)
    current = _normalize_voice(current_voice)
    if requested is None and not _is_voice_catalog_request(normalized):
        return None
    if requested is not None and _is_change_request(normalized):
        if requested == current:
            return (
                f"Ya estoy usando {display_voice(current)}. Las otras voces disponibles son: "
                f"{_voice_list(exclude=current)}."
            )
        return (
            f"{display_voice(requested)} esta disponible, pero no puedo cambiar la voz de una "
            "conversacion que ya ha empezado a emitir audio. Para dejarla fija, pon "
            f"TIPI_REALTIME_SPEAKER_VOICE={requested} en el .env y reinicia Tipi."
        )
    if requested is not None:
        return (
            f"{display_voice(requested)} esta disponible. Ahora mismo estoy usando "
            f"{display_voice(current)}."
        )
    return (
        f"Las voces disponibles son: {_voice_list()}. Ahora mismo estoy usando "
        f"{display_voice(current)}. Las recomendadas son Marin y Cedar."
    )


def _voice_list(*, exclude: str | None = None) -> str:
    voices = [display_voice(voice) for voice in AVAILABLE_REALTIME_VOICES if voice != exclude]
    if len(voices) <= 1:
        return "".join(voices)
    return f"{', '.join(voices[:-1])} y {voices[-1]}"


def _normalize_voice(value: str) -> str:
    normalized = _normalize(value)
    requested = _requested_voice(normalized)
    return requested or "cedar"


def _requested_voice(normalized_text: str) -> str | None:
    padded = f" {normalized_text} "
    for voice, aliases in _VOICE_ALIASES.items():
        if any(f" {alias} " in padded for alias in aliases):
            return voice
    return None


def _is_voice_catalog_request(normalized_text: str) -> bool:
    padded = f" {normalized_text} "
    mentions_voice = any(
        phrase in padded
        for phrase in (" voz ", " voces ", " speaker voice ", " speakervoice ", " voice ")
    )
    asks_catalog = any(
        phrase in padded
        for phrase in (
            " que ",
            " cual ",
            " cuales ",
            " tienes ",
            " hay ",
            " disponibles ",
            " opciones ",
            " lista ",
            " usando ",
            " actual ",
        )
    )
    return mentions_voice and asks_catalog


def _is_change_request(normalized_text: str) -> bool:
    padded = f" {normalized_text} "
    return any(
        phrase in padded
        for phrase in (
            " pon",
            " pont",
            " ponte",
            " cambia",
            " cambiar",
            " usa",
            " usar",
            " quiero",
            " dejame",
            " con la voz",
        )
    )


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_marks).strip()

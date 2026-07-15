from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

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
    "marin": ("marin", "mari", "marine"),
    "cedar": ("cedar", "cedro"),
}


@dataclass(frozen=True)
class VoiceRequest:
    answer: str
    requested_voice: str | None = None


class VoicePreferenceStore:
    def __init__(self, path: Path, configured_voice: str):
        self.path = path
        self.voice = _normalize_voice(configured_voice)
        self._load()

    def _load(self) -> None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))["voice"]
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return
        normalized = _requested_voice(_normalize(str(value)))
        if normalized:
            self.voice = normalized

    def set(self, voice: str) -> None:
        normalized = _requested_voice(_normalize(voice))
        if not normalized:
            raise ValueError(f"Voz Realtime no disponible: {voice}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"voice": normalized}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(self.path)
        self.voice = normalized


def display_voice(voice: str) -> str:
    return voice.strip().lower().capitalize()


def voice_answer_for(text: str, current_voice: str) -> str | None:
    request = voice_request_for(text, current_voice)
    return request.answer if request else None


def voice_request_for(text: str, current_voice: str) -> VoiceRequest | None:
    normalized = _normalize(text)
    requested = _requested_voice(normalized)
    current = _normalize_voice(current_voice)
    catalog_request = _is_voice_catalog_request(normalized)
    change_request = bool(requested and _is_voice_change_request(normalized, requested))
    if (
        not catalog_request
        and not change_request
        and not (requested and _mentions_voice(normalized))
    ):
        return None
    if requested is not None and change_request:
        if requested == current:
            return VoiceRequest(
                f"Ya estoy usando {display_voice(current)}. Las otras voces disponibles son: "
                f"{_voice_list(exclude=current)}."
            )
        return VoiceRequest(
            f"He preparado la voz {display_voice(requested)}. La usaré a partir de la "
            "próxima conversación.",
            requested_voice=requested,
        )
    if requested is not None:
        return VoiceRequest(
            f"{display_voice(requested)} esta disponible. Ahora mismo estoy usando "
            f"{display_voice(current)}."
        )
    return VoiceRequest(
        f"Las voces disponibles son: {_voice_list()}. Ahora mismo estoy usando "
        f"{display_voice(current)}. Las recomendadas son Marin y Cedar."
    )


def _voice_list(*, exclude: str | None = None) -> str:
    voices = [
        display_voice(voice) for voice in AVAILABLE_REALTIME_VOICES if voice != exclude
    ]
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
    return _mentions_voice(normalized_text) and asks_catalog


def _mentions_voice(normalized_text: str) -> bool:
    padded = f" {normalized_text} "
    return any(
        phrase in padded
        for phrase in (
            " voz ",
            " voces ",
            " veu ",
            " veus ",
            " speaker voice ",
            " speakervoice ",
            " voice ",
        )
    )


def _is_voice_change_request(normalized_text: str, requested_voice: str) -> bool:
    tokens = normalized_text.split()
    aliases = set(_VOICE_ALIASES[requested_voice])
    alias_index = next(
        (index for index, token in enumerate(tokens) if token in aliases), -1
    )
    if alias_index < 0:
        return False

    prefix = tokens[:alias_index]
    suffix = tokens[alias_index + 1 :]
    allowed_suffixes = ([], ["ahora"], ["por", "favor"], ["ahora", "por", "favor"])
    if suffix not in allowed_suffixes:
        return False

    actions = {
        "pon",
        "ponme",
        "pont",
        "ponte",
        "posa",
        "cambia",
        "cambiame",
        "canvia",
        "usa",
        "quiero",
        "vull",
        "dejame",
        "deixa",
    }
    fillers = {"a", "amb", "con", "de", "el", "la", "me", "una", "veu", "voz"}
    if any(token in actions for token in prefix) and all(
        token in actions or token in fillers for token in prefix
    ):
        return True
    return prefix in (
        ["con", "la", "voz", "de"],
        ["con", "la", "voz"],
        ["amb", "la", "veu", "de"],
    )


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_marks).strip()

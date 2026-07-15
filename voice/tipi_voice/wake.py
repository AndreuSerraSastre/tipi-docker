from __future__ import annotations

import audioop
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from vosk import KaldiRecognizer, Model, SetLogLevel


NORMAL_WAKE_COOLDOWN_SECONDS = 2.0
PLAYBACK_WAKE_COOLDOWN_SECONDS = 0.45
PLAYBACK_EVIDENCE_WINDOW_SECONDS = 1.25
PLAYBACK_EVIDENCE_WINDOW_SAMPLES = round(48_000 * PLAYBACK_EVIDENCE_WINDOW_SECONDS)
PLAYBACK_ENDPOINT_WINDOW_SECONDS = 0.75
PLAYBACK_ENDPOINT_WINDOW_SAMPLES = round(48_000 * PLAYBACK_ENDPOINT_WINDOW_SECONDS)
PLAYBACK_MIN_ISOLATED_ALIAS_SECONDS = 0.38
_PLAYBACK_GRAMMAR_WORDS = {"tipi", "tip"}
_PLAYBACK_ACOUSTIC_TOKENS = {"tv", "pipi", "tibi"}
_PLAYBACK_COMMAND_TOKENS = {"calla", "callate", "escucha", "para", "silencio"}
_PLAYBACK_FALSE_PREDECESSORS = {"tipo", "tipos", "tipica", "tipico"}
_PLAYBACK_CONTRASTIVE_GRAMMAR = (
    "tipi",
    "tip",
    "tipo",
    "tipos",
    "t\u00edpico",
    "t\u00edpica",
    "si",
    "s\u00ed",
    "ti",
    "pipi",
    "tibi",
    "tv",
    "city",
    "para",
    "aqu\u00ed",
    "[unk]",
)


def normalize_phrase(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def matches_wake_phrase(phrase: str, words: set[str], *, strict: bool = False) -> bool:
    tokens = normalize_phrase(phrase).split()
    # Only configured words may wake Tipi. Prefix matching (for example
    # accepting every token beginning with "tip") turns ordinary speech and
    # noise into false activations, especially with partial Vosk results.
    return any(token in words for token in tokens)


def matches_playback_acoustic_cue(phrase: str) -> bool:
    """Filtra la gramática sensible con una segunda transcripción abierta."""
    tokens = normalize_phrase(phrase).split()
    for index, token in enumerate(tokens):
        if token not in _PLAYBACK_ACOUSTIC_TOKENS:
            continue
        if index and tokens[index - 1] in _PLAYBACK_FALSE_PREDECESSORS:
            continue
        if index == len(tokens) - 1 or any(
            following in _PLAYBACK_COMMAND_TOKENS
            for following in tokens[index + 1 : index + 3]
        ):
            return True
    return bool(
        tokens
        and tokens[0] == "ti"
        and any(token in _PLAYBACK_COMMAND_TOKENS for token in tokens[1:3])
    )


def matches_playback_terminal_alias(phrase: str) -> bool:
    """Acepta un alias fonético inequívoco al final de la hipótesis abierta."""
    tokens = normalize_phrase(phrase).split()
    return bool(
        tokens
        and tokens[-1] in _PLAYBACK_ACOUSTIC_TOKENS
        and (len(tokens) == 1 or tokens[-2] not in _PLAYBACK_FALSE_PREDECESSORS)
    )


def matches_playback_contrastive_cue(phrase: str) -> bool:
    """Acepta una pista de activaci\u00f3n solo fuera de contextos confusores."""
    tokens = normalize_phrase(phrase).split()
    for index, token in enumerate(tokens):
        if token not in _PLAYBACK_GRAMMAR_WORDS | _PLAYBACK_ACOUSTIC_TOKENS:
            continue
        if index and tokens[index - 1] in _PLAYBACK_FALSE_PREDECESSORS:
            continue
        return True
    return matches_playback_acoustic_cue(phrase)


def matches_completed_playback_alias(data: dict[str, Any]) -> bool:
    """Valida un alias aislado y suficientemente largo de un resultado final."""
    result = data.get("result")
    if not isinstance(result, list) or len(result) != 1:
        return False
    word = result[0]
    if not isinstance(word, dict):
        return False
    token = normalize_phrase(str(word.get("word") or ""))
    if token not in _PLAYBACK_GRAMMAR_WORDS | _PLAYBACK_ACOUSTIC_TOKENS:
        return False
    try:
        duration = float(word["end"]) - float(word["start"])
    except (KeyError, TypeError, ValueError):
        return False
    return duration >= PLAYBACK_MIN_ISOLATED_ALIAS_SECONDS


class WakeWordDetector:
    def __init__(self, model_path: Path, wake_words: tuple[str, ...]):
        SetLogLevel(-1)
        self.words = {normalize_phrase(word) for word in wake_words}
        self.model = Model(str(model_path))
        # Use the model's full vocabulary. A grammar containing only the wake
        # word and ``[unk]`` forces acoustically similar ordinary words (for
        # example "tipo" or "típico") toward "tipi" and creates false wakes.
        self.recognizer = KaldiRecognizer(self.model, 16_000)
        # During loud playback, the open recognizer can hear a short name as
        # "tv" or "ti para". A contrastive grammar retains those aliases and
        # their common confusers instead of forcing ordinary speech to "tipi".
        # It is still not trusted on a partial hypothesis alone.
        playback_grammar = json.dumps(_PLAYBACK_CONTRASTIVE_GRAMMAR, ensure_ascii=False)
        self.playback_recognizer = KaldiRecognizer(self.model, 16_000, playback_grammar)
        self.playback_recognizer.SetWords(True)
        self._rate_state: Any = None
        self._last_trigger = 0.0
        self._playback_sample_position = 0
        self._last_acoustic_cue_sample: int | None = None
        self._last_constrained_wake_sample: int | None = None
        self._last_open_complete_sample: int | None = None
        self._last_open_complete_phrase = ""

    def _clear_playback_evidence(self) -> None:
        self._last_acoustic_cue_sample = None
        self._last_constrained_wake_sample = None
        self._last_open_complete_sample = None
        self._last_open_complete_phrase = ""

    def feed(self, pcm_48khz: bytes, *, strict: bool = False) -> bool:
        self._playback_sample_position = (
            getattr(self, "_playback_sample_position", 0) + len(pcm_48khz) // 2
        )
        position = self._playback_sample_position
        pcm_16khz, self._rate_state = audioop.ratecv(
            pcm_48khz, 2, 1, 48_000, 16_000, self._rate_state
        )
        complete = self.recognizer.AcceptWaveform(pcm_16khz)
        if not complete and not strict:
            # Outside playback, require an utterance endpoint. This prevents
            # short-lived partial guesses from opening sessions in ambient noise.
            return False
        raw = self.recognizer.Result() if complete else self.recognizer.PartialResult()
        data = json.loads(raw)
        phrase = normalize_phrase(data.get("text") or data.get("partial") or "")
        if strict and complete and phrase:
            self._last_open_complete_sample = position
            self._last_open_complete_phrase = phrase
        playback_complete = False
        playback_phrase = ""
        playback_data: dict[str, Any] = {}
        if strict:
            playback_complete = self.playback_recognizer.AcceptWaveform(pcm_16khz)
            playback_raw = (
                self.playback_recognizer.Result()
                if playback_complete
                else self.playback_recognizer.PartialResult()
            )
            playback_data = json.loads(playback_raw)
            playback_phrase = normalize_phrase(
                playback_data.get("text") or playback_data.get("partial") or ""
            )
        else:
            self._clear_playback_evidence()
        cooldown = (
            PLAYBACK_WAKE_COOLDOWN_SECONDS if strict else NORMAL_WAKE_COOLDOWN_SECONDS
        )
        direct_match = bool(
            phrase and matches_wake_phrase(phrase, self.words, strict=strict)
        )
        terminal_alias = bool(strict and matches_playback_terminal_alias(phrase))
        acoustic_cue = bool(strict and matches_playback_acoustic_cue(phrase))
        constrained_wake = bool(
            strict and matches_playback_contrastive_cue(playback_phrase)
        )
        if acoustic_cue:
            self._last_acoustic_cue_sample = position
        if constrained_wake:
            self._last_constrained_wake_sample = position

        cue_position = getattr(self, "_last_acoustic_cue_sample", None)
        constrained_position = getattr(self, "_last_constrained_wake_sample", None)
        for attribute, evidence_position in (
            ("_last_acoustic_cue_sample", cue_position),
            ("_last_constrained_wake_sample", constrained_position),
        ):
            if (
                evidence_position is not None
                and position - evidence_position > PLAYBACK_EVIDENCE_WINDOW_SAMPLES
            ):
                setattr(self, attribute, None)
        cue_position = getattr(self, "_last_acoustic_cue_sample", None)
        constrained_position = getattr(self, "_last_constrained_wake_sample", None)
        fallback_match = bool(
            strict
            and (acoustic_cue or constrained_wake)
            and cue_position is not None
            and constrained_position is not None
            and abs(cue_position - constrained_position)
            <= PLAYBACK_EVIDENCE_WINDOW_SAMPLES
        )
        open_complete_position = getattr(self, "_last_open_complete_sample", None)
        open_complete_phrase = getattr(self, "_last_open_complete_phrase", "")
        safe_recent_endpoint = bool(
            open_complete_position is not None
            and position - open_complete_position <= PLAYBACK_ENDPOINT_WINDOW_SAMPLES
            and not any(
                token in _PLAYBACK_FALSE_PREDECESSORS
                for token in normalize_phrase(open_complete_phrase).split()
            )
        )
        endpoint_alias_match = bool(
            strict
            and playback_complete
            and safe_recent_endpoint
            and matches_completed_playback_alias(playback_data)
        )
        match = direct_match or terminal_alias or fallback_match or endpoint_alias_match
        if not match or time.monotonic() - self._last_trigger < cooldown:
            return False

        self._last_trigger = time.monotonic()
        self.recognizer.Reset()
        self.playback_recognizer.Reset()
        self._clear_playback_evidence()
        return True

    def reset(self) -> None:
        self.recognizer.Reset()
        self.playback_recognizer.Reset()
        self._rate_state = None
        self._playback_sample_position = 0
        self._clear_playback_evidence()

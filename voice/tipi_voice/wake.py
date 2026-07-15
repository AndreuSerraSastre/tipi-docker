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
_PLAYBACK_GRAMMAR_WORDS = {"tipi", "tip"}
_PLAYBACK_ACOUSTIC_TOKENS = {"tv", "pipi", "tibi"}
_PLAYBACK_COMMAND_TOKENS = {"calla", "callate", "escucha", "para", "silencio"}
_PLAYBACK_FALSE_PREDECESSORS = {"tipo", "tipos", "tipica", "tipico"}


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
        # "tv" or "ti para". A constrained recognizer recovers sensitivity,
        # but it is never trusted alone: feed() requires an independent,
        # uncommon acoustic cue from the open transcript.
        playback_grammar = json.dumps(["tipi", "tip", "[unk]"])
        self.playback_recognizer = KaldiRecognizer(self.model, 16_000, playback_grammar)
        self._rate_state: Any = None
        self._last_trigger = 0.0
        self._playback_sample_position = 0
        self._last_acoustic_cue_sample: int | None = None
        self._last_constrained_wake_sample: int | None = None

    def _clear_playback_evidence(self) -> None:
        self._last_acoustic_cue_sample = None
        self._last_constrained_wake_sample = None

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
        playback_complete = False
        playback_phrase = ""
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
            strict
            and matches_wake_phrase(
                playback_phrase, _PLAYBACK_GRAMMAR_WORDS, strict=True
            )
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
        match = direct_match or terminal_alias or fallback_match
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

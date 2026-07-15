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
PLAYBACK_PARTIAL_HITS = 4
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
        self._partial_wake_hits = 0

    def feed(self, pcm_48khz: bytes, *, strict: bool = False) -> bool:
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
        cooldown = (
            PLAYBACK_WAKE_COOLDOWN_SECONDS if strict else NORMAL_WAKE_COOLDOWN_SECONDS
        )
        if not phrase:
            if strict:
                self._partial_wake_hits = 0
            return False
        if time.monotonic() - self._last_trigger < cooldown:
            return False
        direct_match = matches_wake_phrase(phrase, self.words, strict=strict)
        fallback_match = bool(
            strict
            and matches_wake_phrase(
                playback_phrase, _PLAYBACK_GRAMMAR_WORDS, strict=True
            )
            and matches_playback_acoustic_cue(phrase)
        )
        match = direct_match or fallback_match
        if not match:
            self._partial_wake_hits = 0
            return False
        if fallback_match and not direct_match:
            # The constrained recognizer can force an ordinary final word into
            # "tipi". Require a stable run even when both recognizers just
            # closed an utterance; a genuine short name remains stable across
            # several 20 ms frames, while guesses such as "tipico" mutate.
            self._partial_wake_hits += 1
            if self._partial_wake_hits < PLAYBACK_PARTIAL_HITS:
                return False
        else:
            # An exact match from the open recognizer is independent evidence
            # and should stop playback on its first partial hypothesis.
            self._partial_wake_hits = 0
        if match:
            self._last_trigger = time.monotonic()
            self.recognizer.Reset()
            self.playback_recognizer.Reset()
            self._partial_wake_hits = 0
        return match

    def reset(self) -> None:
        self.recognizer.Reset()
        self.playback_recognizer.Reset()
        self._rate_state = None
        self._partial_wake_hits = 0

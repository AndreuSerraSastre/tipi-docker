from __future__ import annotations

import audioop
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from vosk import KaldiRecognizer, Model, SetLogLevel


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


class WakeWordDetector:
    def __init__(self, model_path: Path, wake_words: tuple[str, ...]):
        SetLogLevel(-1)
        self.words = {normalize_phrase(word) for word in wake_words}
        self.model = Model(str(model_path))
        # Use the model's full vocabulary. A grammar containing only the wake
        # word and ``[unk]`` forces acoustically similar ordinary words (for
        # example "tipo" or "típico") toward "tipi" and creates false wakes.
        self.recognizer = KaldiRecognizer(self.model, 16_000)
        self._rate_state: Any = None
        self._last_trigger = 0.0
        self._partial_phrase = ""
        self._partial_hits = 0

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
        if not phrase or time.monotonic() - self._last_trigger < 2:
            return False
        if not complete:
            # During playback there may be no silence for Vosk to close the
            # utterance. Require the same partial twice before interrupting.
            if phrase == self._partial_phrase:
                self._partial_hits += 1
            else:
                self._partial_phrase = phrase
                self._partial_hits = 1
            if self._partial_hits < 2:
                return False
        else:
            self._partial_phrase = ""
            self._partial_hits = 0
        match = matches_wake_phrase(phrase, self.words, strict=strict)
        if match:
            self._last_trigger = time.monotonic()
            self.recognizer.Reset()
            self._partial_phrase = ""
            self._partial_hits = 0
        return match

    def reset(self) -> None:
        self.recognizer.Reset()
        self._partial_phrase = ""
        self._partial_hits = 0

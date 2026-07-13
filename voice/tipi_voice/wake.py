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
        grammar = json.dumps([*sorted(self.words), "[unk]"], ensure_ascii=False)
        self.recognizer = KaldiRecognizer(self.model, 16_000, grammar)
        self._rate_state: Any = None
        self._last_trigger = 0.0

    def feed(self, pcm_48khz: bytes, *, strict: bool = False) -> bool:
        pcm_16khz, self._rate_state = audioop.ratecv(
            pcm_48khz, 2, 1, 48_000, 16_000, self._rate_state
        )
        complete = self.recognizer.AcceptWaveform(pcm_16khz)
        # Partial Vosk hypotheses repeatedly classified ambient speech and
        # noise as the tiny wake-word grammar. Wait for an utterance endpoint
        # before waking so a short-lived partial guess cannot open a session.
        if not complete:
            return False
        raw = self.recognizer.Result()
        data = json.loads(raw)
        phrase = normalize_phrase(data.get("text") or data.get("partial") or "")
        if not phrase or time.monotonic() - self._last_trigger < 2:
            return False
        match = matches_wake_phrase(phrase, self.words, strict=strict)
        if match:
            self._last_trigger = time.monotonic()
            self.recognizer.Reset()
        return match

    def reset(self) -> None:
        self.recognizer.Reset()

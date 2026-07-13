import json

from tipi_voice import wake
from tipi_voice.wake import WakeWordDetector, matches_wake_phrase, normalize_phrase


def test_normalize_phrase_handles_variants() -> None:
    assert normalize_phrase("  TÍPI!! ") == "tipi"
    assert normalize_phrase("Hola, Tippy") == "hola tippy"


def test_strict_wake_phrase_avoids_similar_words_during_playback() -> None:
    words = {"tipi", "tipy", "tip", "tippi", "tippy"}
    assert matches_wake_phrase("Tipi", words, strict=True)
    assert matches_wake_phrase("hola tippy", words, strict=True)
    assert not matches_wake_phrase("este tipo", words, strict=True)


def test_normal_wake_phrase_avoids_prefix_false_positives() -> None:
    words = {"tipi", "tipy", "tippi", "tippy"}
    assert matches_wake_phrase("hola tipi", words)
    assert not matches_wake_phrase("este tipo", words)


def test_detector_ignores_partial_wake_hypothesis(monkeypatch) -> None:
    class Recognizer:
        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            raise AssertionError("partial hypotheses must not wake Tipi")

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = Recognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert not detector.feed(b"ambient speech")


def test_detector_accepts_completed_wake_phrase(monkeypatch) -> None:
    class Recognizer:
        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return True

        def Result(self) -> str:
            return json.dumps({"text": "tipi"})

        def Reset(self) -> None:
            pass

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = Recognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert detector.feed(b"tipi")

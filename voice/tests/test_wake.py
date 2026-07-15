import json

from tipi_voice import wake
from tipi_voice.wake import (
    PLAYBACK_EVIDENCE_WINDOW_SAMPLES,
    WakeWordDetector,
    matches_playback_acoustic_cue,
    matches_playback_terminal_alias,
    matches_wake_phrase,
    normalize_phrase,
)


PCM_FRAME = bytes(1_920)


class SilentRecognizer:
    def AcceptWaveform(self, _pcm: bytes) -> bool:
        return False

    def PartialResult(self) -> str:
        return json.dumps({"partial": ""})

    def Reset(self) -> None:
        pass


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


def test_detector_keeps_open_vocabulary_as_the_primary_recognizer(
    monkeypatch, tmp_path
) -> None:
    calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(wake, "SetLogLevel", lambda _level: None)
    monkeypatch.setattr(wake, "Model", lambda _path: object())
    monkeypatch.setattr(
        wake,
        "KaldiRecognizer",
        lambda *args: calls.append(args) or object(),
    )

    WakeWordDetector(tmp_path, ("tipi",))

    assert len(calls) == 2
    assert len(calls[0]) == 2
    assert len(calls[1]) == 3
    assert json.loads(calls[1][2]) == ["tipi", "tip", "[unk]"]


def test_detector_ignores_partial_wake_hypothesis(monkeypatch) -> None:
    class Recognizer:
        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            raise AssertionError("partial hypotheses must not wake Tipi")

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = Recognizer()
    detector.playback_recognizer = SilentRecognizer()
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
    detector.playback_recognizer = SilentRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert detector.feed(b"tipi")


def test_detector_accepts_stable_partial_during_playback(monkeypatch) -> None:
    class Recognizer:
        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            return json.dumps({"partial": "tipi"})

        def Reset(self) -> None:
            pass

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = Recognizer()
    detector.playback_recognizer = SilentRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert detector.feed(b"tipi", strict=True)


def test_detector_accepts_growing_partial_during_playback(monkeypatch) -> None:
    class Recognizer:
        def __init__(self) -> None:
            self.partials = iter(("tipi", "tipi para"))

        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            return json.dumps({"partial": next(self.partials)})

        def Reset(self) -> None:
            pass

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = Recognizer()
    detector.playback_recognizer = SilentRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert detector.feed(b"tipi", strict=True)


def test_playback_wake_uses_shorter_cooldown(monkeypatch) -> None:
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
    detector.playback_recognizer = SilentRecognizer()
    detector._rate_state = None
    detector._last_trigger = 100.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))
    monkeypatch.setattr(wake.time, "monotonic", lambda: 100.5)

    assert detector.feed(b"tipi", strict=True)


def test_playback_evidence_can_arrive_asynchronously(monkeypatch) -> None:
    class OpenRecognizer:
        def __init__(self) -> None:
            self.partials = iter(("", "", "voy a explicar tv"))

        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            return json.dumps({"partial": next(self.partials)})

        def Reset(self) -> None:
            pass

    detector = WakeWordDetector.__new__(WakeWordDetector)

    class PlaybackRecognizer:
        def __init__(self) -> None:
            self.partials = iter(("tipi", "", ""))

        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            return json.dumps({"partial": next(self.partials)})

        def Reset(self) -> None:
            pass

    detector.words = {"otra"}
    detector.recognizer = OpenRecognizer()
    detector.playback_recognizer = PlaybackRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert not detector.feed(PCM_FRAME, strict=True)
    assert not detector.feed(PCM_FRAME, strict=True)
    assert detector.feed(PCM_FRAME, strict=True)


def test_playback_evidence_expires(monkeypatch) -> None:
    frame_count = PLAYBACK_EVIDENCE_WINDOW_SAMPLES // 960 + 2

    class OpenRecognizer:
        def __init__(self) -> None:
            self.index = 0

        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            self.index += 1
            phrase = "tv callate" if self.index == frame_count else ""
            return json.dumps({"partial": phrase})

    class PlaybackRecognizer(OpenRecognizer):
        def PartialResult(self) -> str:
            self.index += 1
            return json.dumps({"partial": "tipi" if self.index == 1 else ""})

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"otra"}
    detector.recognizer = OpenRecognizer()
    detector.playback_recognizer = PlaybackRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    for _ in range(frame_count):
        assert not detector.feed(PCM_FRAME, strict=True)


def test_playback_consensus_recovers_overlapped_wake_word(monkeypatch) -> None:
    class OpenRecognizer:
        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            return json.dumps({"partial": "voy a explicar tv"})

        def Reset(self) -> None:
            pass

    class PlaybackRecognizer(OpenRecognizer):
        def PartialResult(self) -> str:
            return json.dumps({"partial": "tipi"})

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = OpenRecognizer()
    detector.playback_recognizer = PlaybackRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert detector.feed(PCM_FRAME, strict=True)


def test_playback_terminal_alias_does_not_require_constrained_partial(
    monkeypatch,
) -> None:
    class OpenRecognizer:
        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            return json.dumps({"partial": "estamos voces tv"})

        def Reset(self) -> None:
            pass

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = OpenRecognizer()
    detector.playback_recognizer = SilentRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert detector.feed(PCM_FRAME, strict=True)


def test_playback_consensus_rejects_isolated_complete_guess(monkeypatch) -> None:
    class OpenRecognizer:
        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return True

        def Result(self) -> str:
            return json.dumps({"text": "si ese tipo tv party"})

    class PlaybackRecognizer(OpenRecognizer):
        def Result(self) -> str:
            return json.dumps({"text": "tipi tipi"})

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = OpenRecognizer()
    detector.playback_recognizer = PlaybackRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert not detector.feed(b"ordinary", strict=True)


def test_playback_consensus_rejects_similar_ordinary_word(monkeypatch) -> None:
    class OpenRecognizer:
        def AcceptWaveform(self, _pcm: bytes) -> bool:
            return False

        def PartialResult(self) -> str:
            return json.dumps({"partial": "este tipo de tecnología"})

    class PlaybackRecognizer(OpenRecognizer):
        def PartialResult(self) -> str:
            return json.dumps({"partial": "tipi"})

    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector.words = {"tipi"}
    detector.recognizer = OpenRecognizer()
    detector.playback_recognizer = PlaybackRecognizer()
    detector._rate_state = None
    detector._last_trigger = 0.0
    monkeypatch.setattr(wake.audioop, "ratecv", lambda *_args: (b"pcm", None))

    assert not detector.feed(b"ordinary", strict=True)
    assert not detector.feed(b"ordinary", strict=True)


def test_playback_acoustic_cue_rejects_common_similar_words() -> None:
    assert matches_playback_acoustic_cue("voy a explicar tv")
    assert matches_playback_acoustic_cue("tv callate")
    assert matches_playback_acoustic_cue("ti para")
    assert not matches_playback_acoustic_cue("sí claro")
    assert not matches_playback_acoustic_cue("este tipo")
    assert not matches_playback_acoustic_cue("la típica solución")
    assert not matches_playback_acoustic_cue("para ti tenemos algo")
    assert not matches_playback_acoustic_cue("si ese tipo tv")
    assert not matches_playback_acoustic_cue("si ese tipo tv marti")
    assert not matches_playback_acoustic_cue("tv marti")


def test_playback_terminal_alias_requires_safe_final_context() -> None:
    assert matches_playback_terminal_alias("estamos voces tv")
    assert matches_playback_terminal_alias("pipi")
    assert not matches_playback_terminal_alias("si ese tipo tv")
    assert not matches_playback_terminal_alias("tv marti")

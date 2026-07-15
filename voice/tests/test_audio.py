import queue
import threading
import time
from types import SimpleNamespace

import numpy as np

from tipi_voice.audio import AudioEngine
from tipi_voice.app import TipiVoiceApp


def test_enqueue_output_marks_playback_before_worker_runs() -> None:
    engine = object.__new__(AudioEngine)
    engine.is_playing = threading.Event()
    engine._output_queue = queue.Queue(maxsize=8)

    engine.enqueue_output(b"audio")

    assert engine.is_playing.is_set()
    assert engine._output_queue.get_nowait() == b"audio"


def test_output_done_arms_echo_guard_and_discards_partial_input() -> None:
    app = object.__new__(TipiVoiceApp)
    app.settings = SimpleNamespace(output_echo_guard_seconds=1.2)
    app.last_activity = 0.0
    app._output_echo_guard_until = 0.0
    app._speech_started_at = 1.0
    app._realtime_buffer = bytearray(b"partial")
    app.wake = None
    before = time.monotonic()

    app._on_output_done()

    assert app._output_echo_guard_until >= before + 1.2
    assert app._speech_started_at is None
    assert not app._realtime_buffer


def test_clear_output_discards_queued_audio_immediately() -> None:
    engine = object.__new__(AudioEngine)
    engine._stopping = threading.Event()
    engine.is_playing = threading.Event()
    engine.is_playing.set()
    engine._output_queue = queue.Queue(maxsize=8)
    engine._output_queue.put_nowait(b"audio-1")
    engine._output_queue.put_nowait(b"audio-2")

    engine.clear_output()

    assert engine._output_queue.qsize() == 1
    assert not isinstance(engine._output_queue.get_nowait(), bytes)
    assert not engine.is_playing.is_set()


def test_realtime_output_format_is_applied_and_resampler_is_reset() -> None:
    engine = object.__new__(AudioEngine)
    engine.output_rate = 48_000
    engine.output_channels = 2
    engine._output_rate_state = object()

    engine.set_realtime_output_format(sample_rate=24_000, channels=1)

    assert engine.realtime_output_rate == 24_000
    assert engine._output_rate_state is None


def test_default_chime_pcm_is_valid_mono_pcm16() -> None:
    engine = object.__new__(AudioEngine)
    engine.is_playing = threading.Event()
    engine._output_queue = queue.Queue(maxsize=8)

    engine.play_ready_beep()

    pcm = engine._output_queue.get_nowait()
    samples = np.frombuffer(pcm, dtype="<i2")
    assert samples.size == round(24_000 * 0.18)
    assert np.max(np.abs(samples)) > 0

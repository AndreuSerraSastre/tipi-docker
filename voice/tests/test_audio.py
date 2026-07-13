import queue
import threading

import numpy as np

from tipi_voice.audio import AudioEngine


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
    engine._output_queue = queue.Queue(maxsize=8)

    engine.play_ready_beep()

    pcm = engine._output_queue.get_nowait()
    samples = np.frombuffer(pcm, dtype="<i2")
    assert samples.size == round(24_000 * 0.18)
    assert np.max(np.abs(samples)) > 0

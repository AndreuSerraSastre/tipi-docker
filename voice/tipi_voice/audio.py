from __future__ import annotations

import asyncio
import audioop
import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice as sd

LOGGER = logging.getLogger(__name__)
CANONICAL_RATE = 48_000
REALTIME_OUTPUT_RATE = 24_000
FRAME_MS = 20
FRAME_BYTES = CANONICAL_RATE * FRAME_MS // 1000 * 2
_STOP = object()
_CLEAR = object()
_DONE = object()


def list_devices() -> str:
    lines = ["Dispositivos de audio detectados:"]
    for index, device in enumerate(sd.query_devices()):
        directions: list[str] = []
        if device["max_input_channels"]:
            directions.append(f"entrada:{device['max_input_channels']}")
        if device["max_output_channels"]:
            directions.append(f"salida:{device['max_output_channels']}")
        if directions:
            lines.append(
                f"  [{index}] {device['name']} ({', '.join(directions)}, "
                f"{int(device['default_samplerate'])} Hz)"
            )
    return "\n".join(lines)


def resolve_device(selector: str | int | None, kind: str) -> int | None:
    if selector is None:
        return None
    devices = sd.query_devices()
    if isinstance(selector, int):
        if selector < 0 or selector >= len(devices):
            raise ValueError(f"Índice de audio inexistente: {selector}")
        selected = selector
    else:
        needle = selector.casefold()
        matches = [index for index, item in enumerate(devices) if needle in item["name"].casefold()]
        if not matches:
            raise ValueError(f"No se encontró el dispositivo de {kind}: {selector}")
        selected = matches[0]
    channel_key = "max_input_channels" if kind == "entrada" else "max_output_channels"
    if devices[selected][channel_key] < 1:
        raise ValueError(f"El dispositivo [{selected}] no admite {kind}")
    return selected


class AudioEngine:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        input_queue: asyncio.Queue[bytes],
        input_device: str | int | None,
        output_device: str | int | None,
        input_rate: int,
        output_rate: int,
        output_channels: int,
        input_level: int = 100,
        output_level: int = 100,
        on_output_done: Callable[[], None] | None = None,
    ):
        self.loop = loop
        self.input_queue = input_queue
        self.input_device = resolve_device(input_device, "entrada")
        self.output_device = resolve_device(output_device, "salida")
        self.input_rate = input_rate
        self.output_rate = output_rate
        self.output_channels = output_channels
        self.input_level = input_level
        self.output_level = output_level
        self.on_output_done = on_output_done
        self.input_stream: sd.RawInputStream | None = None
        self.output_stream: sd.RawOutputStream | None = None
        self._capture_rate_state: Any = None
        self._capture_buffer = bytearray()
        self._output_rate_state: Any = None
        self.realtime_output_rate = REALTIME_OUTPUT_RATE
        self._output_queue: queue.Queue[bytes | object] = queue.Queue(maxsize=256)
        self._output_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self.is_playing = threading.Event()
        self.output_error: Exception | None = None

    def start(self) -> None:
        self._open_input()
        self._open_output()
        self._output_thread = threading.Thread(
            target=self._output_worker, name="tipi-audio-output", daemon=True
        )
        self._output_thread.start()
        self.input_stream.start()
        LOGGER.info(
            "Audio iniciado: entrada=%s, salida=%s",
            self._device_name(self.input_device, "entrada"),
            self._device_name(self.output_device, "salida"),
        )

    def _open_input(self) -> None:
        try:
            sd.check_input_settings(
                device=self.input_device, channels=1, dtype="int16", samplerate=self.input_rate
            )
        except sd.PortAudioError:
            info = sd.query_devices(self.input_device, "input")
            fallback = int(info["default_samplerate"])
            LOGGER.warning("La entrada no admite %s Hz; se usará %s Hz", self.input_rate, fallback)
            self.input_rate = fallback
        blocksize = max(1, round(self.input_rate * FRAME_MS / 1000))
        self.input_stream = sd.RawInputStream(
            device=self.input_device,
            samplerate=self.input_rate,
            blocksize=blocksize,
            channels=1,
            dtype="int16",
            callback=self._input_callback,
        )

    def _open_output(self) -> None:
        try:
            sd.check_output_settings(
                device=self.output_device,
                channels=self.output_channels,
                dtype="int16",
                samplerate=self.output_rate,
            )
        except sd.PortAudioError:
            info = sd.query_devices(self.output_device, "output")
            fallback = int(info["default_samplerate"])
            LOGGER.warning("La salida no admite %s Hz; se usará %s Hz", self.output_rate, fallback)
            self.output_rate = fallback
        self.output_stream = sd.RawOutputStream(
            device=self.output_device,
            samplerate=self.output_rate,
            channels=self.output_channels,
            dtype="int16",
        )
        self.output_stream.start()

    def _input_callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        if status:
            LOGGER.debug("Estado de entrada de audio: %s", status)
        pcm = bytes(indata)
        if self.input_level != 100:
            pcm = audioop.mul(pcm, 2, self.input_level / 100)
        if self.input_rate != CANONICAL_RATE:
            pcm, self._capture_rate_state = audioop.ratecv(
                pcm, 2, 1, self.input_rate, CANONICAL_RATE, self._capture_rate_state
            )
        self._capture_buffer.extend(pcm)
        while len(self._capture_buffer) >= FRAME_BYTES:
            frame = bytes(self._capture_buffer[:FRAME_BYTES])
            del self._capture_buffer[:FRAME_BYTES]
            self.loop.call_soon_threadsafe(self._put_input_frame, frame)

    def _put_input_frame(self, frame: bytes) -> None:
        if self.input_queue.full():
            try:
                self.input_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.input_queue.put_nowait(frame)

    def set_realtime_output_format(self, *, sample_rate: int, channels: int = 1) -> None:
        """Adapta la reproducción al formato anunciado por OpenClaw Talk."""
        if sample_rate <= 0:
            raise ValueError("La frecuencia de salida Realtime no es válida")
        if channels != 1:
            raise ValueError("Tipi solo admite PCM16 mono desde OpenClaw Talk")
        self.realtime_output_rate = sample_rate
        self._output_rate_state = None
        LOGGER.info(
            "Formato Realtime confirmado: PCM16 mono a %s Hz; dispositivo a %s Hz/%s canales",
            sample_rate,
            self.output_rate,
            self.output_channels,
        )

    def enqueue_output(self, pcm_mono: bytes) -> None:
        # Close the microphone path before the worker consumes the first
        # chunk, so Tipi never forwards the first syllables of its own voice.
        self.is_playing.set()
        self._output_queue.put_nowait(pcm_mono)

    def play_ready_beep(self) -> None:
        sample_rate = 24_000
        sample_count = round(sample_rate * 0.18)
        times = np.arange(sample_count, dtype=np.float64) / sample_rate
        envelope = np.sin(np.linspace(0, np.pi, sample_count, dtype=np.float64)) ** 2
        samples = np.sin(2 * np.pi * 880 * times) * envelope * 0.20
        self.enqueue_output((samples * 32767).astype("<i2").tobytes())
        self.mark_output_done()

    def play_startup_chime(self) -> None:
        """Dos notas ascendentes para indicar que Tipi ya ha arrancado."""
        sample_rate = 24_000

        def tone(frequency: float, duration: float) -> np.ndarray:
            sample_count = round(sample_rate * duration)
            times = np.arange(sample_count, dtype=np.float64) / sample_rate
            envelope = np.sin(np.linspace(0, np.pi, sample_count, dtype=np.float64)) ** 2
            return np.sin(2 * np.pi * frequency * times) * envelope * 0.16

        silence = np.zeros(round(sample_rate * 0.06), dtype=np.float64)
        samples = np.concatenate((tone(523.25, 0.14), silence, tone(783.99, 0.24)))
        self.enqueue_output((samples * 32767).astype("<i2").tobytes())
        self.mark_output_done()

    def mark_output_done(self) -> None:
        self._output_queue.put_nowait(_DONE)

    def clear_output(self) -> None:
        if self._stopping.is_set():
            return
        # El contador de inactividad no debe quedar bloqueado esperando al hilo
        # de salida después de una cancelación o interrupción.
        self.is_playing.clear()
        while True:
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break
        self._output_queue.put_nowait(_CLEAR)

    def prepare_stop(self) -> None:
        self._stopping.set()

    def _output_worker(self) -> None:
        assert self.output_stream is not None
        try:
            while True:
                item = self._output_queue.get()
                if item is _STOP:
                    return
                if item is _CLEAR:
                    self.output_stream.abort()
                    self.output_stream.start()
                    self._output_rate_state = None
                    self.is_playing.clear()
                    continue
                if item is _DONE:
                    if self._output_queue.empty():
                        self._output_rate_state = None
                        self.is_playing.clear()
                        if self.on_output_done:
                            self.loop.call_soon_threadsafe(self.on_output_done)
                    continue
                assert isinstance(item, bytes)
                self.is_playing.set()
                # PCM16 siempre debe contener muestras completas. Un byte suelto
                # desalinearía todas las muestras siguientes y sonaría como ruido.
                pcm = item[: len(item) - (len(item) % 2)]
                if not pcm:
                    continue
                if self.output_level != 100:
                    pcm = audioop.mul(pcm, 2, self.output_level / 100)
                if self.output_rate != self.realtime_output_rate:
                    pcm, self._output_rate_state = audioop.ratecv(
                        pcm,
                        2,
                        1,
                        self.realtime_output_rate,
                        self.output_rate,
                        self._output_rate_state,
                    )
                if self.output_channels == 2:
                    samples = np.frombuffer(pcm, dtype="<i2")
                    pcm = np.repeat(samples[:, None], 2, axis=1).astype("<i2").tobytes()
                self.output_stream.write(pcm)
        except Exception as exc:
            self.is_playing.clear()
            if not self._stopping.is_set():
                self.output_error = exc
                LOGGER.exception("Falló la reproducción de audio")

    def _device_name(self, device: int | None, kind: str) -> str:
        try:
            return str(sd.query_devices(device, "input" if kind == "entrada" else "output")["name"])
        except Exception:
            return "predeterminado"

    @property
    def input_device_name(self) -> str:
        return self._device_name(self.input_device, "entrada")

    @property
    def output_device_name(self) -> str:
        return self._device_name(self.output_device, "salida")

    def stop(self) -> None:
        self.prepare_stop()
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()
        try:
            self._output_queue.put_nowait(_STOP)
        except queue.Full:
            pass
        if self._output_thread:
            self._output_thread.join(timeout=2)
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()

    def set_input_level(self, level: int) -> None:
        self.input_level = max(25, min(300, level))

    def set_output_level(self, level: int) -> None:
        self.output_level = max(0, min(100, level))

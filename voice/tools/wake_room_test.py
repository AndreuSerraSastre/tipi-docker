from __future__ import annotations

import argparse
import audioop
import wave
from pathlib import Path

from tipi_voice.wake import WakeWordDetector


RATE = 48_000
FRAME_MS = 20
FRAME_BYTES = RATE * 2 * FRAME_MS // 1_000
MODEL_PATH = Path("/models/vosk-model-small-es-0.42")


def read_mono_48k(path: Path) -> bytes:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        source_rate = source.getframerate()
        pcm = source.readframes(source.getnframes())
    if channels == 2:
        pcm = audioop.tomono(pcm, width, 0.5, 0.5)
    elif channels != 1:
        raise RuntimeError(f"unsupported channel count: {channels}")
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if source_rate != RATE:
        pcm, _ = audioop.ratecv(pcm, 2, 1, source_rate, RATE, None)
    return pcm


def silence(duration_ms: int) -> bytes:
    return bytes(RATE * 2 * duration_ms // 1_000)


def normalize(pcm: bytes, peak: int) -> bytes:
    current = audioop.max(pcm, 2)
    if not current:
        raise RuntimeError("generated speech is silent")
    return audioop.mul(pcm, 2, min(peak / current, 4.0))


def mix(base: bytes, overlay: bytes, offset_ms: int) -> bytes:
    offset = RATE * 2 * offset_ms // 1_000
    total = max(len(base), offset + len(overlay))
    return audioop.add(
        base.ljust(total, b"\0"),
        (bytes(offset) + overlay).ljust(total, b"\0"),
        2,
    )


def write_stereo(path: Path, mono: bytes) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(RATE)
        target.writeframes(audioop.tostereo(mono, 2, 1.0, 1.0))


def generate(work: Path) -> None:
    background = normalize(read_mono_48k(work / "background.wav"), 7_500)
    clean = normalize(read_mono_48k(work / "clean.wav"), 24_000)
    negative = normalize(read_mono_48k(work / "negative.wav"), 22_000)

    positive_segment = mix(silence(200) + background + silence(1_000), clean, 1_200)
    positive = silence(500) + (positive_segment + silence(900)) * 3
    negative_segment = silence(300) + negative + silence(900)
    negative_track = silence(500) + negative_segment * 6

    write_stereo(work / "positive-playback.wav", positive)
    write_stereo(work / "negative-playback.wav", negative_track)
    print("ROOM_AUDIO_GENERATED")


def decode(pcm: bytes) -> list[int]:
    detector = WakeWordDetector(MODEL_PATH, ("tipi", "tipy", "tip"))
    triggers: list[int] = []
    for offset in range(0, len(pcm), FRAME_BYTES):
        frame = pcm[offset : offset + FRAME_BYTES].ljust(FRAME_BYTES, b"\0")
        if detector.feed(frame, strict=True):
            triggers.append((offset + FRAME_BYTES) * 1_000 // (RATE * 2))
    return triggers


def detect(path: Path, scenario: str) -> None:
    pcm = read_mono_48k(path)
    peak = audioop.max(pcm, 2)
    rms = audioop.rms(pcm, 2)
    if peak <= 500 or rms <= 30:
        raise RuntimeError(f"room recording is too quiet: {peak=}, {rms=}")
    triggers = decode(pcm)
    clusters: list[int] = []
    for trigger in triggers:
        if not clusters or trigger - clusters[-1] > 1_800:
            clusters.append(trigger)
    print(
        f"ROOM_{scenario.upper()} peak={peak} rms={rms} "
        f"triggers={triggers} clusters={clusters}"
    )
    if scenario == "positive" and len(clusters) < 3:
        raise RuntimeError(f"only {len(clusters)}/3 wake words detected")
    if scenario == "negative" and triggers:
        raise RuntimeError(f"negative room track triggered at {triggers}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("generate", "detect"))
    parser.add_argument("--work", type=Path, default=Path("/work"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--scenario", choices=("positive", "negative"))
    args = parser.parse_args()
    if args.mode == "generate":
        generate(args.work)
        return
    if args.input is None or args.scenario is None:
        parser.error("detect requires --input and --scenario")
    detect(args.input, args.scenario)


if __name__ == "__main__":
    main()

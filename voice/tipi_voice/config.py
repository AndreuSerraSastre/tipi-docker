from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _as_selector(value: str | None) -> str | int | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    return int(value) if value.isdigit() else value


@dataclass(frozen=True)
class Settings:
    gateway_url: str
    gateway_token: str
    session_key: str
    vosk_model: Path
    state_dir: Path
    wake_words: tuple[str, ...]
    idle_timeout_seconds: float
    input_device: str | int | None
    output_device: str | int | None
    input_sample_rate: int
    output_sample_rate: int
    output_channels: int
    vad_mode: int
    barge_in: bool
    speaker_voice: str
    health_file: Path | None
    log_dir: Path
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(override=False)
        state_dir = Path(os.getenv("TIPI_STATE_DIR", "data/voice")).expanduser().resolve()
        log_dir = Path(os.getenv("TIPI_LOG_DIR", "data/logs")).expanduser().resolve()
        health_raw = os.getenv("TIPI_HEALTH_FILE", "").strip()
        wake_words = tuple(
            word.strip().lower()
            for word in os.getenv("TIPI_WAKE_WORDS", "tipi,tipy,tip,tippi,tippy").split(",")
            if word.strip()
        )
        token = os.getenv("TIPI_GATEWAY_TOKEN") or os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
        return cls(
            gateway_url=os.getenv("TIPI_GATEWAY_URL", "ws://127.0.0.1:18789"),
            gateway_token=token.strip(),
            session_key=os.getenv("TIPI_SESSION_KEY", "agent:main:main").strip(),
            vosk_model=Path(
                os.getenv("TIPI_VOSK_MODEL", "data/models/vosk-model-small-es-0.42")
            ).expanduser().resolve(),
            state_dir=state_dir,
            wake_words=wake_words,
            idle_timeout_seconds=float(os.getenv("TIPI_IDLE_TIMEOUT_SECONDS", "5")),
            input_device=_as_selector(os.getenv("TIPI_INPUT_DEVICE")),
            output_device=_as_selector(os.getenv("TIPI_OUTPUT_DEVICE")),
            input_sample_rate=int(os.getenv("TIPI_INPUT_SAMPLE_RATE", "48000")),
            output_sample_rate=int(os.getenv("TIPI_OUTPUT_SAMPLE_RATE", "48000")),
            output_channels=int(os.getenv("TIPI_OUTPUT_CHANNELS", "2")),
            vad_mode=max(0, min(3, int(os.getenv("TIPI_VAD_MODE", "2")))),
            barge_in=_as_bool(os.getenv("TIPI_BARGE_IN"), False),
            speaker_voice=os.getenv("TIPI_REALTIME_SPEAKER_VOICE", "cedar").strip() or "cedar",
            health_file=Path(health_raw) if health_raw else None,
            log_dir=log_dir,
            log_level=os.getenv("TIPI_LOG_LEVEL", "INFO").upper(),
        )

    def validate(self, require_model: bool = True) -> None:
        if not self.gateway_token:
            raise ValueError("Falta OPENCLAW_GATEWAY_TOKEN en .env")
        if not self.wake_words:
            raise ValueError("TIPI_WAKE_WORDS no puede estar vacío")
        if self.idle_timeout_seconds <= 0:
            raise ValueError("TIPI_IDLE_TIMEOUT_SECONDS debe ser mayor que cero")
        if self.output_channels not in {1, 2}:
            raise ValueError("TIPI_OUTPUT_CHANNELS debe ser 1 o 2")
        if require_model and not self.vosk_model.is_dir():
            raise ValueError(f"No existe el modelo Vosk: {self.vosk_model}")

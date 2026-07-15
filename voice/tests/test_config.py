from pathlib import Path

import pytest

from tipi_voice.config import Settings, _as_bool, _as_selector


def test_boolean_and_device_parsing() -> None:
    assert _as_bool("sí") is True
    assert _as_bool("off", True) is False
    assert _as_selector(" 12 ") == 12
    assert _as_selector("soundcore") == "soundcore"
    assert _as_selector(" ") is None


def test_settings_validation_rejects_missing_token(tmp_path: Path) -> None:
    settings = Settings(
        gateway_url="ws://127.0.0.1:18789",
        gateway_token="",
        session_key="agent:main:main",
        vosk_model=tmp_path,
        state_dir=tmp_path,
        wake_words=("tipi",),
        idle_timeout_seconds=5,
        agent_timeout_seconds=75,
        input_device=None,
        output_device=None,
        input_sample_rate=48_000,
        output_sample_rate=48_000,
        output_channels=1,
        vad_mode=2,
        barge_in=False,
        output_echo_guard_seconds=1.2,
        speaker_voice="cedar",
        health_file=None,
        log_dir=tmp_path / "logs",
        log_level="INFO",
    )
    with pytest.raises(ValueError, match="TOKEN"):
        settings.validate()

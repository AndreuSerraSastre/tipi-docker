import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tipi_voice import audio_controls
from tipi_voice.audio_controls import (
    AudioLevelStore,
    SystemAudioController,
    parse_audio_command,
)


def test_parses_output_volume_commands() -> None:
    adjustment = parse_audio_command(
        "Pon el volumen de los auriculares al sesenta por ciento",
        microphone_level=100,
        output_level=80,
    )
    assert adjustment is not None
    assert (adjustment.target, adjustment.previous, adjustment.level) == (
        "salida",
        80,
        60,
    )


def test_five_percent_is_not_confused_with_one_hundred() -> None:
    adjustment = parse_audio_command(
        "Vuelve a bajar el volumen al cinco por ciento",
        microphone_level=100,
        output_level=20,
    )
    assert adjustment is not None
    assert adjustment.level == 5


def test_parses_relative_microphone_sensitivity() -> None:
    adjustment = parse_audio_command(
        "Sube la sensibilidad del micrófono",
        microphone_level=100,
        output_level=80,
    )
    assert adjustment is not None
    assert (adjustment.target, adjustment.previous, adjustment.level) == (
        "microfono",
        100,
        110,
    )


def test_does_not_treat_a_question_as_a_command() -> None:
    assert (
        parse_audio_command(
            "¿Qué significa la sensibilidad de un micrófono?",
            microphone_level=100,
            output_level=100,
        )
        is None
    )


def test_audio_levels_persist(tmp_path: Path) -> None:
    path = tmp_path / "audio-levels.json"
    store = AudioLevelStore(path)
    adjustment = store.parse("Baja el volumen veinte por ciento")
    assert adjustment is not None
    store.apply(adjustment)

    restored = AudioLevelStore(path)
    assert restored.output_level == 80
    assert restored.microphone_level == 100


def test_linux_output_level_uses_selected_alsa_card(monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        if command[-1] == "controls":
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "numid=1,iface=MIXER,name='Speaker Playback Switch'\n"
                    "numid=2,iface=MIXER,name='Speaker Playback Volume'\n"
                ),
            )
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(audio_controls.sys, "platform", "linux")
    monkeypatch.setattr(audio_controls.subprocess, "run", run)
    controller = SystemAudioController(
        "USB Audio Device (hw:2,0)",
        "USB Audio Device (hw:2,0)",
    )

    assert controller.set_level("salida", 100)
    assert [
        "amixer",
        "-q",
        "-c",
        "2",
        "cset",
        "name=Speaker Playback Volume",
        "100%",
    ] in calls
    assert calls[-1] == [
        "amixer",
        "-q",
        "-c",
        "2",
        "cset",
        "name=Speaker Playback Switch",
        "on",
    ]


def test_linux_microphone_above_hardware_limit_uses_100_percent(monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        if command[-1] == "controls":
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "numid=1,iface=MIXER,name='Mic Playback Volume'\n"
                    "numid=2,iface=MIXER,name='Mic Capture Switch'\n"
                    "numid=3,iface=MIXER,name='Mic Capture Volume'\n"
                ),
            )
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(audio_controls.sys, "platform", "linux")
    monkeypatch.setattr(audio_controls.subprocess, "run", run)
    controller = SystemAudioController(
        "USB Audio Device (hw:1,0)",
        "USB Audio Device (hw:1,0)",
    )

    assert controller.set_level("microfono", 180)
    assert [
        "amixer",
        "-q",
        "-c",
        "1",
        "cset",
        "name=Mic Capture Volume",
        "100%",
    ] in calls
    assert all("Mic Playback" not in part for command in calls for part in command)


@pytest.mark.skipif(sys.platform != "win32", reason="pycaw solo se instala en Windows")
def test_windows_audio_api_imports() -> None:
    from pycaw.constants import DEVICE_STATE, EDataFlow
    from pycaw.pycaw import AudioUtilities

    assert DEVICE_STATE.ACTIVE is not None
    assert EDataFlow.eRender is not None
    assert AudioUtilities is not None

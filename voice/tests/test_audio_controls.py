from pathlib import Path

from tipi_voice.audio_controls import AudioLevelStore, parse_audio_command


def test_parses_output_volume_commands() -> None:
    adjustment = parse_audio_command(
        "Pon el volumen de los auriculares al sesenta por ciento",
        microphone_level=100,
        output_level=80,
    )
    assert adjustment is not None
    assert (adjustment.target, adjustment.previous, adjustment.level) == ("salida", 80, 60)


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

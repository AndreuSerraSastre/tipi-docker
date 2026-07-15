import os

from tipi_voice.voices import VoicePreferenceStore, voice_answer_for, voice_request_for


def test_voice_question_is_answered_locally() -> None:
    answer = voice_answer_for("Que voces tienes disponibles?", "cedar")

    assert answer is not None
    assert "Marin" in answer
    assert "Cedar" in answer
    assert "estoy usando Cedar" in answer


def test_voice_change_request_is_prepared_for_next_conversation() -> None:
    answer = voice_answer_for("Pont Mari", "cedar")

    assert answer is not None
    assert "He preparado la voz Marin" in answer
    assert "próxima conversación" in answer


def test_accented_voice_change_request_is_understood() -> None:
    answer = voice_answer_for("Ponme con la voz de Marin.", "cedar")

    assert answer is not None
    assert "He preparado la voz Marin" in answer


def test_unrelated_question_is_not_intercepted() -> None:
    assert voice_answer_for("Quien eres?", "cedar") is None
    assert voice_answer_for("La voz suena un poco floja.", "cedar") is None
    assert voice_answer_for("Quien es Marin?", "cedar") is None
    assert voice_answer_for("Pon a Marina en la lista.", "cedar") is None


def test_voice_change_exposes_the_requested_voice() -> None:
    request = voice_request_for("Cambia a Marin", "cedar")

    assert request is not None
    assert request.requested_voice == "marin"


def test_voice_preference_is_persisted(tmp_path) -> None:
    path = tmp_path / "speaker-voice.json"
    store = VoicePreferenceStore(path, "cedar")

    store.set("marin")
    reloaded = VoicePreferenceStore(path, "cedar")

    assert reloaded.voice == "marin"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600

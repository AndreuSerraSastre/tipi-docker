from tipi_voice.voices import voice_answer_for


def test_voice_question_is_answered_locally() -> None:
    answer = voice_answer_for("Que voces tienes disponibles?", "cedar")

    assert answer is not None
    assert "Marin" in answer
    assert "Cedar" in answer
    assert "estoy usando Cedar" in answer


def test_voice_change_request_explains_restart_requirement() -> None:
    answer = voice_answer_for("Pont Mari", "cedar")

    assert answer is not None
    assert "Marin esta disponible" in answer
    assert "TIPI_REALTIME_SPEAKER_VOICE=marin" in answer
    assert "reinicia Tipi" in answer


def test_accented_voice_change_request_is_understood() -> None:
    answer = voice_answer_for("Ponme con la voz de Marin.", "cedar")

    assert answer is not None
    assert "TIPI_REALTIME_SPEAKER_VOICE=marin" in answer


def test_unrelated_question_is_not_intercepted() -> None:
    assert voice_answer_for("Quien eres?", "cedar") is None
    assert voice_answer_for("La voz suena un poco floja.", "cedar") is None

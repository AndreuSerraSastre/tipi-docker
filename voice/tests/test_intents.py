from tipi_voice.intents import is_stop_command


def test_stop_commands_in_spanish_and_catalan() -> None:
    assert is_stop_command("Cállate")
    assert is_stop_command("Tipi, para de hablar.")
    assert is_stop_command("Para")
    assert is_stop_command("Prou!")
    assert is_stop_command("Atura't")
    assert is_stop_command("Deixa de parlar")


def test_normal_conversation_does_not_close_the_session() -> None:
    assert not is_stop_command("Para la presentación necesitamos una pantalla")
    assert not is_stop_command("¿Puedes hablar más bajo?")
    assert not is_stop_command("Tipi, continúa")

from tipi_voice.intents import is_plausible_visitor_transcript, is_stop_command


def test_stop_commands_in_spanish_and_catalan() -> None:
    assert is_stop_command("Callate")
    assert is_stop_command("Vale, callate.")
    assert is_stop_command("Tipi, para de hablar.")
    assert is_stop_command("Para")
    assert is_stop_command("Prou!")
    assert is_stop_command("Atura't")
    assert is_stop_command("Deixa de parlar")


def test_normal_conversation_does_not_close_the_session() -> None:
    assert not is_stop_command("Para la presentacion necesitamos una pantalla")
    assert not is_stop_command("Puedes hablar mas bajo?")
    assert not is_stop_command("Tipi, continua")


def test_plausible_visitor_transcript_allows_expected_languages() -> None:
    assert is_plausible_visitor_transcript("Hola, me oyes?")
    assert is_plausible_visitor_transcript("Bon dia, com estas?")
    assert is_plausible_visitor_transcript("Hello Tipi")


def test_plausible_visitor_transcript_rejects_unexpected_scripts() -> None:
    assert not is_plausible_visitor_transcript("모르겠어")
    assert not is_plausible_visitor_transcript("你好")

from tipi_voice.app import TipiVoiceApp


def test_second_direct_response_is_blocked_without_new_user_turn() -> None:
    app = object.__new__(TipiVoiceApp)
    app._direct_response_finished = True
    app._turn_consulted = False
    app.pending_tools = set()

    assert app._is_duplicate_direct_response()


def test_openclaw_followup_is_not_blocked() -> None:
    app = object.__new__(TipiVoiceApp)
    app._direct_response_finished = True
    app._turn_consulted = True
    app.pending_tools = set()

    assert not app._is_duplicate_direct_response()

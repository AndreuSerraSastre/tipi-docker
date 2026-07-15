from tipi_voice.app import TipiVoiceApp


def test_second_direct_response_is_blocked_without_new_user_turn() -> None:
    app = object.__new__(TipiVoiceApp)
    app._direct_response_finished = True
    app._turn_consulted = False
    app.pending_tools = set()

    assert app._is_duplicate_direct_response()


def test_openclaw_final_response_is_blocked_after_finishing() -> None:
    app = object.__new__(TipiVoiceApp)
    app._direct_response_finished = True
    app._turn_consulted = True
    app.pending_tools = set()

    assert app._is_duplicate_direct_response()


def test_waiting_message_is_suppressed_only_until_consult_result() -> None:
    app = object.__new__(TipiVoiceApp)
    app._consult_wait_message_finished = True
    app._consult_result_ready = False

    assert app._should_suppress_consult_wait_output()

    app._consult_result_ready = True

    assert not app._should_suppress_consult_wait_output()

import asyncio

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


def test_consult_counts_message_that_finished_before_tool_call() -> None:
    app = object.__new__(TipiVoiceApp)
    app._direct_response_finished = True
    app._consult_wait_message_finished = False
    app._consult_result_ready = False
    app._consult_wait_output_cancelled = False

    app._begin_consult_wait()

    assert app._should_suppress_consult_wait_output()
    assert not app._direct_response_finished


def test_output_start_discards_pending_microphone_batches() -> None:
    app = object.__new__(TipiVoiceApp)
    app._speech_started_at = 1.0
    app._realtime_rate_state = object()
    app._realtime_buffer = bytearray(b"partial")
    app._audio_sender_queue = asyncio.Queue()
    app._audio_sender_queue.put_nowait(b"queued")

    app._discard_pending_microphone_audio()

    assert app._speech_started_at is None
    assert app._realtime_rate_state is None
    assert not app._realtime_buffer
    assert app._audio_sender_queue.empty()

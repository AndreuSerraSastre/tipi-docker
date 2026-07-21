import asyncio
import json
from types import SimpleNamespace

import pytest

from tipi_voice import app as app_module
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
    app.mic_queue = asyncio.Queue()
    app.mic_queue.put_nowait(b"captured")
    app._audio_sender_queue = asyncio.Queue()
    app._audio_sender_queue.put_nowait(b"queued")

    app._discard_pending_microphone_audio()

    assert app._speech_started_at is None
    assert app._realtime_rate_state is None
    assert not app._realtime_buffer
    assert app.mic_queue.empty()
    assert app._audio_sender_queue.empty()


@pytest.mark.asyncio
async def test_wake_interruption_stops_output_but_keeps_active_consult() -> None:
    class Audio:
        def __init__(self) -> None:
            self.clear_count = 0
            self.ready_count = 0

        def clear_output(self) -> None:
            self.clear_count += 1

        def play_ready_beep(self) -> None:
            self.ready_count += 1

    class Gateway:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict[str, object]]] = []

        async def request(
            self, method: str, params: dict[str, object], timeout: int
        ) -> None:
            self.requests.append((method, params))

    app = object.__new__(TipiVoiceApp)
    app.session_id = "relay-1"
    app.audio = Audio()
    app.gateway = Gateway()
    app.pending_tools = {"consult-1"}
    app._barge_in_cancelled = False
    app._turn_interrupted = False
    app._suppress_output_until_user = False
    app._turn_number = 1
    app._turn_user_final_at = None
    app.last_activity = 0.0
    app.conversation_log = SimpleNamespace(event=lambda *_args, **_kwargs: None)

    await app._interrupt_for_wake_word()

    assert app.pending_tools == {"consult-1"}
    assert app._suppress_output_until_user
    assert app.audio.clear_count == 2
    assert app.audio.ready_count == 1
    assert app.gateway.requests[0][0] == "talk.session.cancelOutput"


@pytest.mark.asyncio
async def test_stale_audio_is_suppressed_after_wake_interruption() -> None:
    class Audio:
        def __init__(self) -> None:
            self.enqueued: list[bytes] = []

        def enqueue_output(self, pcm: bytes) -> None:
            self.enqueued.append(pcm)

    app = object.__new__(TipiVoiceApp)
    app.session_id = "relay-1"
    app.audio = Audio()
    app._suppress_output_until_user = True

    await app._handle_talk_event(
        {"relaySessionId": "relay-1", "type": "audio", "audioBase64": "YXVkaW8="}
    )

    assert app.audio.enqueued == []


@pytest.mark.asyncio
async def test_agent_consult_returns_one_final_tool_result() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict[str, object]]] = []

        async def request(
            self, method: str, params: dict[str, object], timeout: float
        ) -> dict[str, str]:
            self.requests.append((method, params))
            return {"runId": "run-1"} if method == "talk.client.toolCall" else {}

        async def wait_for_chat_result(self, run_id: str, timeout: float) -> str:
            assert (run_id, timeout) == ("run-1", 75)
            return "La temperatura comprobada es de 24 grados."

    app = object.__new__(TipiVoiceApp)
    app.gateway = Gateway()
    app.session_id = "relay-1"
    app.settings = SimpleNamespace(
        session_key="agent:main:tipi-voice",
        speaker_voice="cedar",
        agent_timeout_seconds=75,
    )
    app.voice_preferences = SimpleNamespace(voice="cedar")
    app.pending_tools = {"call-1"}
    app._turn_number = 1
    app._turn_user_final_at = None
    app._turn_consulted = False
    app._consult_result_ready = False
    app._consult_wait_output_cancelled = False
    app._direct_response_finished = False
    app.last_activity = 0.0
    app.conversation_log = SimpleNamespace(event=lambda *_args, **_kwargs: None)

    await app._handle_tool_call(
        {
            "callId": "call-1",
            "name": "openclaw_agent_consult",
            "args": {"question": "Comprueba la temperatura real."},
        }
    )

    submissions = [
        params
        for method, params in app.gateway.requests
        if method == "talk.session.submitToolResult"
    ]
    assert submissions == [
        {
            "sessionId": "relay-1",
            "callId": "call-1",
            "result": {"result": "La temperatura comprobada es de 24 grados."},
        }
    ]
    assert app.pending_tools == set()
    assert app._consult_result_ready


@pytest.mark.asyncio
async def test_agent_timeout_returns_meaningful_error() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict[str, object]]] = []

        async def request(
            self, method: str, params: dict[str, object], timeout: float
        ) -> dict[str, str]:
            self.requests.append((method, params))
            return {"runId": "run-timeout"} if method == "talk.client.toolCall" else {}

        async def wait_for_chat_result(self, _run_id: str, timeout: float) -> str:
            assert timeout == 30
            raise TimeoutError

    app = object.__new__(TipiVoiceApp)
    app.gateway = Gateway()
    app.session_id = "relay-1"
    app.settings = SimpleNamespace(
        session_key="agent:main:tipi-voice",
        speaker_voice="cedar",
        agent_timeout_seconds=30,
    )
    app.voice_preferences = SimpleNamespace(voice="cedar")
    app.pending_tools = {"call-timeout"}
    app._turn_number = 1
    app._turn_user_final_at = None
    app._turn_consulted = False
    app._consult_result_ready = False
    app._consult_wait_output_cancelled = False
    app._direct_response_finished = False
    app.last_activity = 0.0
    app.conversation_log = SimpleNamespace(event=lambda *_args, **_kwargs: None)

    await app._handle_tool_call(
        {
            "callId": "call-timeout",
            "name": "openclaw_agent_consult",
            "args": {"question": "Haz una consulta que tarda demasiado."},
        }
    )

    submission = next(
        params
        for method, params in app.gateway.requests
        if method == "talk.session.submitToolResult"
    )
    assert submission["result"] == {"error": "OpenClaw no respondió en 30 segundos"}


def test_health_file_reports_the_devices_opened_by_the_running_process(
    tmp_path,
) -> None:
    app = object.__new__(TipiVoiceApp)
    app.settings = SimpleNamespace(health_file=tmp_path / "tipi-voice.health")
    app.gateway = SimpleNamespace(disconnected=asyncio.Event())
    app.session_id = None
    app.pending_tools = set()
    app.audio = SimpleNamespace(
        input_device_name="USB Audio Device (hw:1,0)",
        output_device_name="USB Audio Device (hw:1,0)",
    )
    app.audio_levels = SimpleNamespace(microphone_level=100, output_level=100)
    app.voice_preferences = SimpleNamespace(voice="cedar")

    app._touch_health_file()

    health = json.loads(app.settings.health_file.read_text(encoding="utf-8"))
    assert health["gatewayConnected"] is True
    assert health["inputDevice"] == "USB Audio Device (hw:1,0)"
    assert health["outputDevice"] == "USB Audio Device (hw:1,0)"
    assert health["outputLevel"] == 100


@pytest.mark.asyncio
async def test_partial_startup_failure_closes_gateway(monkeypatch, tmp_path) -> None:
    class Gateway:
        instance = None

        def __init__(self, *_args: object) -> None:
            self.closed = False
            self.disconnected = asyncio.Event()
            Gateway.instance = self

        async def connect(self) -> None:
            return None

        def on(self, _event: str, _handler: object) -> None:
            return None

        async def close(self) -> None:
            self.closed = True

    settings = SimpleNamespace(
        vad_mode=3,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
        gateway_url="ws://gateway:18789",
        gateway_token="token",
        vosk_model=tmp_path / "vosk-model",
        wake_words=("tipi",),
        speaker_voice="cedar",
        validate=lambda: None,
    )
    monkeypatch.setattr(
        app_module.DeviceIdentity, "load_or_create", lambda _path: object()
    )
    monkeypatch.setattr(app_module, "GatewayClient", Gateway)
    monkeypatch.setattr(
        app_module,
        "WakeWordDetector",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("modelo corrupto")),
    )
    app = TipiVoiceApp(settings)

    with pytest.raises(RuntimeError, match="modelo corrupto"):
        await app.run()

    assert Gateway.instance is not None
    assert Gateway.instance.closed


@pytest.mark.asyncio
async def test_new_session_uses_the_persisted_voice() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.create_params = None

        async def request(self, method: str, params: dict, timeout: float) -> dict:
            assert method == "talk.session.create"
            self.create_params = params
            return {
                "relaySessionId": "relay-voice",
                "audio": {
                    "outputEncoding": "pcm16",
                    "outputSampleRateHz": 24_000,
                    "outputChannels": 1,
                },
            }

    class Audio:
        def set_realtime_output_format(
            self, *, sample_rate: int, channels: int
        ) -> None:
            assert (sample_rate, channels) == (24_000, 1)

        def play_ready_beep(self) -> None:
            return None

    app = object.__new__(TipiVoiceApp)
    app.gateway = Gateway()
    app.audio = Audio()
    app.settings = SimpleNamespace(session_key="agent:main:tipi-voice")
    app.voice_preferences = SimpleNamespace(voice="marin")
    app.mic_queue = asyncio.Queue()
    app._wake_detected_at = None
    app._realtime_rate_state = None
    app._realtime_buffer = bytearray()
    app.conversation_log = SimpleNamespace(event=lambda *_args, **_kwargs: None)

    await app._open_session()

    assert app.gateway.create_params["voice"] == "marin"
    app.session_id = None
    app._audio_sender_task.cancel()
    await asyncio.gather(app._audio_sender_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_wake_responds_locally_without_internet() -> None:
    spoken: list[str] = []
    events: list[tuple[object, ...]] = []

    class Wake:
        def __init__(self) -> None:
            self.reset_count = 0

        def reset(self) -> None:
            self.reset_count += 1

    async def internet_unavailable() -> bool:
        return False

    app = object.__new__(TipiVoiceApp)
    app.audio = SimpleNamespace(play_local_speech=spoken.append)
    app.wake = Wake()
    app.mic_queue = asyncio.Queue()
    app.mic_queue.put_nowait(b"pregunta")
    app._wake_detected_at = 1.0
    app._speech_started_at = 2.0
    app._internet_available = internet_unavailable
    app.conversation_log = SimpleNamespace(
        event=lambda *args, **kwargs: events.append((*args, kwargs))
    )

    await app._start_conversation()

    assert spoken == [app_module.OFFLINE_MESSAGE]
    assert app.wake.reset_count == 1
    assert app.mic_queue.empty()
    assert app._wake_detected_at is None
    assert app._speech_started_at is None
    assert events[0][0] == "SIN_INTERNET"


@pytest.mark.asyncio
async def test_new_session_forwards_audio_captured_while_connecting_before_beep() -> (
    None
):
    events: list[object] = []

    class Gateway:
        async def request(self, method: str, params: dict, timeout: float) -> dict:
            assert method == "talk.session.create"
            app.mic_queue.put_nowait(b"question-1")
            app.mic_queue.put_nowait(b"question-2")
            return {"relaySessionId": "relay-startup"}

    class Audio:
        def set_realtime_output_format(
            self, *, sample_rate: int, channels: int
        ) -> None:
            assert (sample_rate, channels) == (24_000, 1)

        def play_ready_beep(self) -> None:
            events.append("beep")

    class Vad:
        def is_speech(self, frame: bytes, sample_rate: int) -> bool:
            assert sample_rate == 48_000
            return frame == b"question-1"

    async def queue_frame(frame: bytes) -> None:
        events.append(frame)

    app = object.__new__(TipiVoiceApp)
    app.gateway = Gateway()
    app.audio = Audio()
    app.settings = SimpleNamespace(session_key="agent:main:tipi-voice")
    app.voice_preferences = SimpleNamespace(voice="marin")
    app.mic_queue = asyncio.Queue()
    app._vad = Vad()
    app._wake_detected_at = None
    app._speech_started_at = None
    app._realtime_rate_state = None
    app._realtime_buffer = bytearray()
    app._queue_realtime_frame = queue_frame
    app.conversation_log = SimpleNamespace(event=lambda *_args, **_kwargs: None)

    await app._open_session()

    assert events == [b"question-1", b"question-2", "beep"]
    assert app.mic_queue.empty()
    assert app._speech_started_at is not None
    app.session_id = None
    app._audio_sender_task.cancel()
    await asyncio.gather(app._audio_sender_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_voice_tool_call_persists_the_next_voice() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.requests = []

        async def request(self, method: str, params: dict, timeout: float) -> dict:
            self.requests.append((method, params))
            return {}

    class Preferences:
        voice = "cedar"

        def set(self, voice: str) -> None:
            self.voice = voice

    app = object.__new__(TipiVoiceApp)
    app.gateway = Gateway()
    app.session_id = "relay-voice"
    app.settings = SimpleNamespace(session_key="agent:main:tipi-voice")
    app.voice_preferences = Preferences()
    app.pending_tools = {"voice-call"}
    app._turn_number = 1
    app._turn_user_final_at = None
    app._consult_result_ready = False
    app._consult_wait_output_cancelled = False
    app._direct_response_finished = False
    app.last_activity = 0.0
    app.conversation_log = SimpleNamespace(event=lambda *_args, **_kwargs: None)

    await app._handle_tool_call(
        {
            "callId": "voice-call",
            "name": "openclaw_agent_consult",
            "args": {"question": "Pont Mari"},
        }
    )

    assert app.voice_preferences.voice == "marin"
    submission = next(
        params
        for method, params in app.gateway.requests
        if method == "talk.session.submitToolResult"
    )
    assert "próxima conversación" in submission["result"]["result"]

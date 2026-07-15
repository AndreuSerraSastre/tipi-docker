from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import webrtcvad

from . import __version__
from .audio import AudioEngine
from .audio_controls import AudioAdjustment, AudioLevelStore, SystemAudioController
from .config import Settings
from .conversation_log import ConversationLogger
from .gateway import GatewayClient, GatewayError
from .identity import DeviceIdentity
from .intents import is_plausible_visitor_transcript, is_stop_command
from .voices import VoicePreferenceStore, voice_request_for
from .wake import WakeWordDetector

LOGGER = logging.getLogger(__name__)
REALTIME_BATCH_BYTES = 24_000 * 160 // 1000 * 2


class TipiVoiceApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.gateway: GatewayClient | None = None
        self.audio: AudioEngine | None = None
        self.system_audio: SystemAudioController | None = None
        self.wake: WakeWordDetector | None = None
        self.mic_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=300)
        self.session_id: str | None = None
        self.last_activity = time.monotonic()
        self.pending_tools: set[str] = set()
        self._tool_tasks: set[asyncio.Task[None]] = set()
        self._audio_sender_queue: asyncio.Queue[bytes] | None = None
        self._audio_sender_task: asyncio.Task[None] | None = None
        self._realtime_rate_state: Any = None
        self._realtime_buffer = bytearray()
        self._closing_session = False
        self._barge_in_cancelled = False
        self._vad = webrtcvad.Vad(settings.vad_mode)
        self.conversation_log = ConversationLogger(settings.log_dir)
        self.audio_levels = AudioLevelStore(settings.state_dir / "audio-levels.json")
        self.voice_preferences = VoicePreferenceStore(
            settings.state_dir / "speaker-voice.json", settings.speaker_voice
        )
        self._wake_detected_at: float | None = None
        self._session_started_at: float | None = None
        self._speech_started_at: float | None = None
        self._turn_number = 0
        self._turn_user_final_at: float | None = None
        self._turn_first_audio_ms: int | None = None
        self._turn_consulted = False
        self._turn_interrupted = False
        self._direct_response_finished = False
        self._duplicate_output_cancelled = False
        self._output_echo_guard_until = 0.0
        self._consult_wait_message_finished = False
        self._consult_result_ready = False
        self._consult_wait_output_cancelled = False
        self._suppress_output_until_user = False

    async def run(self) -> None:
        self.settings.validate()
        self.conversation_log.event(
            "ARRANQUE",
            "Tipi Voice iniciado",
            archivo=str(self.conversation_log.latest_readable_path),
            sensibilidad_microfono=self.audio_levels.microphone_level,
            volumen_salida=self.audio_levels.output_level,
        )
        tasks: list[asyncio.Task[Any]] = []
        try:
            identity = DeviceIdentity.load_or_create(self.settings.state_dir)
            self.gateway = GatewayClient(
                self.settings.gateway_url, self.settings.gateway_token, identity
            )
            await self.gateway.connect()
            self.gateway.on("talk.event", self._handle_talk_event)

            self.wake = WakeWordDetector(
                self.settings.vosk_model, self.settings.wake_words
            )
            loop = asyncio.get_running_loop()
            self.audio = AudioEngine(
                loop=loop,
                input_queue=self.mic_queue,
                input_device=self.settings.input_device,
                output_device=self.settings.output_device,
                input_rate=self.settings.input_sample_rate,
                output_rate=self.settings.output_sample_rate,
                output_channels=self.settings.output_channels,
                on_output_done=self._on_output_done,
            )
            self.system_audio = SystemAudioController(
                self.audio.input_device_name,
                self.audio.output_device_name,
            )
            self._set_active_audio_level(
                "microfono", self.audio_levels.microphone_level
            )
            self._set_active_audio_level("salida", self.audio_levels.output_level)
            self.audio.start()
            self.audio.play_startup_chime()
            await asyncio.sleep(0.65)
            self._drain_microphone_queue()
            LOGGER.info(
                'Tipi está atento. Di "%s" para hablar.', self.settings.wake_words[0]
            )
            LOGGER.info(
                "Registro de conversación: %s",
                self.conversation_log.latest_readable_path,
            )

            tasks = [
                asyncio.create_task(self._microphone_loop(), name="microphone-loop"),
                asyncio.create_task(self._inactivity_loop(), name="inactivity-loop"),
                asyncio.create_task(self._health_loop(), name="health-loop"),
                asyncio.create_task(
                    self.gateway.disconnected.wait(), name="gateway-watch"
                ),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                error = task.exception()
                if error:
                    raise error
            if self.gateway.disconnected.is_set():
                raise GatewayError("Se perdió la conexión con OpenClaw")
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self._close_session(notify_gateway=True, reason="aplicación detenida")
            if self.audio:
                with suppress(Exception):
                    self.audio.stop()
            if self.gateway:
                await self.gateway.close()
            self.conversation_log.event("APAGADO", "Tipi Voice detenido")

    async def _microphone_loop(self) -> None:
        assert self.wake is not None
        while True:
            frame = await self.mic_queue.get()
            if self.session_id is None:
                if self.wake.feed(frame):
                    self._wake_detected_at = time.monotonic()
                    LOGGER.info("Palabra de activación detectada")
                    self.conversation_log.event("ACTIVACION", "Palabra Tipi detectada")
                    await self._open_session()
                continue

            assert self.audio is not None
            output_active = self._output_is_active()
            if output_active and self.wake.feed(frame, strict=True):
                await self._interrupt_for_wake_word()
                continue
            speaking = self._vad.is_speech(frame, 48_000)
            if speaking and (not output_active or self.settings.barge_in):
                if self._speech_started_at is None:
                    self._speech_started_at = time.monotonic()
                    # Una voz nueva concede un turno completo, pero el ruido continuo no
                    # puede reiniciar indefinidamente el cierre por silencio.
                    self._mark_activity()
            if output_active:
                if not self.settings.barge_in:
                    continue
                if speaking and not self._barge_in_cancelled:
                    self._barge_in_cancelled = True
                    asyncio.create_task(self._cancel_output())
            await self._queue_realtime_frame(frame)

    async def _open_session(self) -> None:
        assert self.gateway is not None
        create_started_at = time.monotonic()
        result = await self.gateway.request(
            "talk.session.create",
            {
                "sessionKey": self.settings.session_key,
                "provider": "openai",
                "mode": "realtime",
                "transport": "gateway-relay",
                "brain": "agent-consult",
                "voice": self.voice_preferences.voice,
            },
            timeout=30,
        )
        session_id = result.get("relaySessionId") or result.get("sessionId")
        if not session_id:
            raise GatewayError("OpenClaw no devolvió un identificador de Talk")
        audio_format = (
            result.get("audio") if isinstance(result.get("audio"), dict) else {}
        )
        output_encoding = str(audio_format.get("outputEncoding") or "pcm16").lower()
        output_rate = int(audio_format.get("outputSampleRateHz") or 24_000)
        output_channels = int(audio_format.get("outputChannels") or 1)
        if output_encoding not in {"pcm16", "pcm_s16le", "s16le"}:
            raise GatewayError(
                f"OpenClaw devolvió un formato de audio no compatible: {output_encoding}"
            )
        self.session_id = session_id
        self._session_started_at = time.monotonic()
        self.last_activity = time.monotonic()
        self._barge_in_cancelled = False
        self._realtime_rate_state = None
        self._realtime_buffer.clear()
        self._audio_sender_queue = asyncio.Queue(maxsize=40)
        self._audio_sender_task = asyncio.create_task(
            self._audio_sender(), name="audio-sender"
        )
        LOGGER.info("Conversación Realtime iniciada")
        self.conversation_log.event(
            "SESION_INICIADA",
            "Conversación Realtime preparada",
            conexion_ms=self._elapsed_ms(create_started_at),
            desde_activacion_ms=(
                self._elapsed_ms(self._wake_detected_at)
                if self._wake_detected_at
                else None
            ),
            sesion=session_id[:8],
        )
        assert self.audio is not None
        self.audio.set_realtime_output_format(
            sample_rate=output_rate,
            channels=output_channels,
        )
        self.audio.play_ready_beep()

    async def _queue_realtime_frame(self, frame_48khz: bytes) -> None:
        if self.session_id is None or self._audio_sender_queue is None:
            return
        pcm, self._realtime_rate_state = audioop.ratecv(
            frame_48khz, 2, 1, 48_000, 24_000, self._realtime_rate_state
        )
        self._realtime_buffer.extend(pcm)
        while len(self._realtime_buffer) >= REALTIME_BATCH_BYTES:
            batch = bytes(self._realtime_buffer[:REALTIME_BATCH_BYTES])
            del self._realtime_buffer[:REALTIME_BATCH_BYTES]
            if self._audio_sender_queue.full():
                LOGGER.warning(
                    "Se descarta audio porque el Gateway no responde a tiempo"
                )
                with suppress(asyncio.QueueEmpty):
                    self._audio_sender_queue.get_nowait()
            self._audio_sender_queue.put_nowait(batch)

    async def _audio_sender(self) -> None:
        assert self.gateway is not None
        assert self._audio_sender_queue is not None
        while self.session_id:
            pcm = await self._audio_sender_queue.get()
            session_id = self.session_id
            if not session_id:
                return
            await self.gateway.request(
                "talk.session.appendAudio",
                {
                    "sessionId": session_id,
                    "audioBase64": base64.b64encode(pcm).decode("ascii"),
                    "timestamp": round(time.monotonic() * 1000),
                },
                timeout=10,
            )

    async def _handle_talk_event(self, event: dict[str, Any]) -> None:
        if not self.session_id or event.get("relaySessionId") != self.session_id:
            return
        event_type = event.get("type")
        if event_type in {"ready", "inputAudio"}:
            return
        if event_type == "audio" and event.get("audioBase64"):
            assert self.audio is not None
            if self._suppress_output_until_user:
                return
            if self._should_suppress_consult_wait_output():
                if not self._consult_wait_output_cancelled:
                    self._consult_wait_output_cancelled = True
                    LOGGER.warning(
                        "Se bloqueó una respuesta adicional mientras OpenClaw trabaja"
                    )
                    self.conversation_log.event(
                        "RESPUESTA_ESPERA_BLOQUEADA",
                        "Realtime intentó volver a hablar antes del resultado de OpenClaw",
                        turno=self._turn_number,
                    )
                    asyncio.create_task(
                        self._cancel_output(reason="consult-wait-suppression")
                    )
                return
            if self._is_duplicate_direct_response():
                if not self._duplicate_output_cancelled:
                    self._duplicate_output_cancelled = True
                    LOGGER.warning(
                        "Se bloqueó una segunda respuesta Realtime sin nueva pregunta"
                    )
                    self.conversation_log.event(
                        "RESPUESTA_DUPLICADA_BLOQUEADA",
                        "Realtime intentó hablar otra vez sin una nueva intervención",
                        turno=self._turn_number,
                    )
                    await self._cancel_output(reason="duplicate-direct-response")
                return
            if not self.audio.is_playing.is_set():
                if self.wake:
                    self.wake.reset()
                self._discard_pending_microphone_audio()
            self._mark_activity()
            if (
                self._turn_user_final_at is not None
                and self._turn_first_audio_ms is None
            ):
                self._turn_first_audio_ms = self._elapsed_ms(self._turn_user_final_at)
                self.conversation_log.event(
                    "REALTIME_PRIMER_AUDIO",
                    "Realtime comenzó a responder",
                    turno=self._turn_number,
                    respuesta_inicial_ms=self._turn_first_audio_ms,
                )
            try:
                self.audio.enqueue_output(base64.b64decode(event["audioBase64"]))
            except Exception:
                LOGGER.exception("No se pudo encolar el audio de respuesta")
            return
        if event_type == "audioDone":
            assert self.audio is not None
            self.audio.mark_output_done()
            return
        if event_type == "clear":
            assert self.audio is not None
            self.audio.clear_output()
            self._mark_activity()
            return
        if event_type == "transcript":
            text = str(event.get("text") or "").strip()
            if text and event.get("final") is True:
                role = str(event.get("role") or "")
                if role == "user":
                    if not is_plausible_visitor_transcript(text):
                        LOGGER.info(
                            "Transcripción descartada por idioma inesperado: %s", text
                        )
                        self.conversation_log.event(
                            "TRANSCRIPCION_DESCARTADA",
                            text,
                            motivo="idioma_inesperado",
                        )
                        self._speech_started_at = None
                        return
                    now = time.monotonic()
                    self._suppress_output_until_user = False
                    self._barge_in_cancelled = False
                    self._turn_number += 1
                    self._turn_user_final_at = now
                    self._turn_first_audio_ms = None
                    self._turn_consulted = False
                    self._turn_interrupted = False
                    self._direct_response_finished = False
                    self._duplicate_output_cancelled = False
                    transcription_ms = (
                        self._elapsed_ms(self._speech_started_at)
                        if self._speech_started_at is not None
                        else None
                    )
                    self._speech_started_at = None
                    LOGGER.info("Persona: %s", text)
                    self.conversation_log.event(
                        "PERSONA",
                        text,
                        turno=self._turn_number,
                        transcripcion_ms=transcription_ms,
                    )
                    if is_stop_command(text):
                        LOGGER.info(
                            "Orden de silencio detectada; se cierra la conversación"
                        )
                        self.conversation_log.event(
                            "ORDEN_SILENCIO",
                            text,
                            turno=self._turn_number,
                        )
                        await self._cancel_output(reason="stop-command")
                        await self._close_session(
                            notify_gateway=True,
                            reason="orden de silencio",
                        )
                        return
                    self._apply_spoken_audio_adjustment(text)
                else:
                    if self._suppress_output_until_user:
                        return
                    if self._should_suppress_consult_wait_output():
                        LOGGER.warning(
                            "Transcripción de espera adicional ignorada: %s", text
                        )
                        return
                    if self._is_duplicate_direct_response():
                        LOGGER.warning(
                            "Transcripción de respuesta duplicada ignorada: %s", text
                        )
                        return
                    complete_ms = (
                        self._elapsed_ms(self._turn_user_final_at)
                        if self._turn_user_final_at is not None
                        else None
                    )
                    LOGGER.info("Tipi: %s", text)
                    self.conversation_log.event(
                        "REALTIME_RESPUESTA",
                        text,
                        turno=self._turn_number,
                        consulto_openclaw=self._turn_consulted,
                        interrumpida=self._turn_interrupted,
                        primera_voz_ms=self._turn_first_audio_ms,
                        respuesta_completa_ms=complete_ms,
                    )
                    if self.pending_tools and not self._consult_result_ready:
                        self._consult_wait_message_finished = True
                    elif not self.pending_tools or self._consult_result_ready:
                        self._direct_response_finished = True
                self._mark_activity()
            return
        if event_type == "toolCall":
            call_id = str(event.get("callId") or "")
            name = str(event.get("name") or "")
            if name == "openclaw_agent_consult":
                self._turn_consulted = True
                if not self.pending_tools:
                    self._begin_consult_wait()
            if (
                call_id
                and name == "openclaw_agent_consult"
                and self.pending_tools
                and call_id not in self.pending_tools
            ):
                self._start_tool_task(
                    self._handle_consult_followup(event), name=f"followup-{call_id[:8]}"
                )
            elif call_id and call_id not in self.pending_tools:
                self.pending_tools.add(call_id)
                self._start_tool_task(
                    self._handle_tool_call(event), name=f"tool-{call_id[:8]}"
                )
            return
        if event_type == "error":
            message = str(event.get("message", "desconocido"))
            LOGGER.error("Error Realtime: %s", message)
            self.conversation_log.event(
                "ERROR_REALTIME", message, turno=self._turn_number
            )
            await self._close_session(notify_gateway=False, reason="error Realtime")
            return
        if event_type == "close":
            await self._close_session(notify_gateway=False, reason="cierre remoto")

    async def _handle_tool_call(self, event: dict[str, Any]) -> None:
        assert self.gateway is not None
        call_id = str(event["callId"])
        tool_started_at = time.monotonic()
        session_id = self.session_id
        if not session_id:
            self.pending_tools.discard(call_id)
            return
        try:
            name = str(event.get("name") or "")
            if name == "openclaw_agent_control":
                args = self._parse_args(event.get("args"))
                mode = str(args.get("mode") or "").strip()
                control_text = str(args.get("text") or "").strip()
                if not control_text:
                    control_text = (
                        "Comprueba el estado de la consulta activa."
                        if mode == "status"
                        else "Continúa con la consulta activa."
                    )
                self.conversation_log.event(
                    "OPENCLAW_CONTROL",
                    control_text,
                    turno=self._turn_number,
                    modo=mode or None,
                )
                result = await self.gateway.request(
                    "talk.session.steer",
                    {
                        "sessionId": session_id,
                        "sessionKey": self.settings.session_key,
                        "text": control_text,
                        **({"mode": mode} if mode else {}),
                    },
                    timeout=30,
                )
                await self._submit_tool_result(session_id, call_id, result)
                return
            if name != "openclaw_agent_consult":
                await self._submit_tool_result(
                    session_id,
                    call_id,
                    {"error": f'Herramienta no disponible: "{name}"'},
                )
                return
            args = self._parse_args(event.get("args"))
            question = self._consult_question(args)
            voice_request = voice_request_for(question, self.voice_preferences.voice)
            if voice_request:
                if voice_request.requested_voice:
                    previous_voice = self.voice_preferences.voice
                    self.voice_preferences.set(voice_request.requested_voice)
                    self.conversation_log.event(
                        "CAMBIO_VOZ",
                        voice_request.answer,
                        turno=self._turn_number,
                        voz_anterior=previous_voice,
                        voz_nueva=self.voice_preferences.voice,
                    )
                self.conversation_log.event(
                    "RESPUESTA_LOCAL",
                    voice_request.answer,
                    turno=self._turn_number,
                    consulta=question,
                    motivo="voces_realtime",
                )
                self._allow_consult_result_output()
                await self._submit_tool_result(
                    session_id, call_id, {"result": voice_request.answer}
                )
                return
            self._turn_consulted = True
            self.conversation_log.event(
                "OPENCLAW_CONSULTA",
                question,
                turno=self._turn_number,
                desde_pregunta_ms=(
                    self._elapsed_ms(self._turn_user_final_at)
                    if self._turn_user_final_at is not None
                    else None
                ),
                forzada=bool(event.get("forced")),
                argumentos=args,
            )
            if event.get("forced"):
                await self._submit_tool_result(
                    session_id,
                    call_id,
                    {
                        "status": "working",
                        "message": "Indica brevemente que lo estás comprobando y espera el resultado final.",
                    },
                    options={"willContinue": True},
                )
            response = await self.gateway.request(
                "talk.client.toolCall",
                {
                    "sessionKey": self.settings.session_key,
                    "callId": call_id,
                    "name": name,
                    "args": event.get("args") or {},
                    "relaySessionId": session_id,
                },
                timeout=30,
            )
            run_id = response.get("runId") or response.get("idempotencyKey")
            if not run_id:
                raise GatewayError("La consulta a OpenClaw no devolvió runId")
            answer = await self.gateway.wait_for_chat_result(
                run_id, timeout=self.settings.agent_timeout_seconds
            )
            self.conversation_log.event(
                "OPENCLAW_RESULTADO",
                answer,
                turno=self._turn_number,
                consulta=question,
                duracion_ms=self._elapsed_ms(tool_started_at),
            )
            self._allow_consult_result_output()
            await self._submit_tool_result(session_id, call_id, {"result": answer})
        except TimeoutError:
            message = (
                "OpenClaw no respondió en "
                f"{self.settings.agent_timeout_seconds:g} segundos"
            )
            LOGGER.warning("%s", message)
            self.conversation_log.event(
                "OPENCLAW_TIMEOUT",
                message,
                turno=self._turn_number,
                duracion_ms=self._elapsed_ms(tool_started_at),
            )
            with suppress(Exception):
                self._allow_consult_result_output()
                await self._submit_tool_result(session_id, call_id, {"error": message})
        except GatewayError as exc:
            message = str(exc)
            if not self.session_id or "aborted" in message.lower():
                LOGGER.info("Consulta del agente cancelada por cierre de conversacion")
            else:
                LOGGER.exception("Fallo la consulta del agente")
            self.conversation_log.event(
                "OPENCLAW_ERROR",
                message,
                turno=self._turn_number,
                duracion_ms=self._elapsed_ms(tool_started_at),
            )
            with suppress(Exception):
                self._allow_consult_result_output()
                await self._submit_tool_result(session_id, call_id, {"error": message})
        except Exception as exc:
            LOGGER.exception("Falló la consulta del agente")
            self.conversation_log.event(
                "OPENCLAW_ERROR",
                str(exc),
                turno=self._turn_number,
                duracion_ms=self._elapsed_ms(tool_started_at),
            )
            with suppress(Exception):
                self._allow_consult_result_output()
                await self._submit_tool_result(session_id, call_id, {"error": str(exc)})
        finally:
            self.pending_tools.discard(call_id)
            self._mark_activity()

    async def _handle_consult_followup(self, event: dict[str, Any]) -> None:
        """Incorpora otra frase a la consulta activa sin abrir un segundo agente."""
        assert self.gateway is not None
        followup_started_at = time.monotonic()
        call_id = str(event.get("callId") or "")
        session_id = self.session_id
        if not call_id or not session_id:
            return
        try:
            args = self._parse_args(event.get("args"))
            text = str(
                args.get("question")
                or args.get("prompt")
                or args.get("query")
                or args.get("task")
                or ""
            ).strip()
            if text:
                self.conversation_log.event(
                    "OPENCLAW_SEGUIMIENTO",
                    text,
                    turno=self._turn_number,
                )
                await self.gateway.request(
                    "talk.session.steer",
                    {
                        "sessionId": session_id,
                        "sessionKey": self.settings.session_key,
                        "text": text,
                        "mode": "steer",
                    },
                    timeout=30,
                )
                LOGGER.info("La nueva frase se ha añadido a la consulta activa")
                self.conversation_log.event(
                    "OPENCLAW_SEGUIMIENTO_ACEPTADO",
                    text,
                    turno=self._turn_number,
                    duracion_ms=self._elapsed_ms(followup_started_at),
                )
            await self._submit_tool_result(
                session_id,
                call_id,
                {
                    "status": "accepted",
                    "message": "La indicación se añadió a la consulta activa.",
                },
                options={"suppressResponse": True},
            )
        except Exception as exc:
            LOGGER.exception("No se pudo añadir la frase a la consulta activa")
            self.conversation_log.event(
                "OPENCLAW_SEGUIMIENTO_ERROR",
                str(exc),
                turno=self._turn_number,
                duracion_ms=self._elapsed_ms(followup_started_at),
            )
            with suppress(Exception):
                await self._submit_tool_result(session_id, call_id, {"error": str(exc)})
        finally:
            self._mark_activity()

    async def _submit_tool_result(
        self,
        session_id: str,
        call_id: str,
        result: Any,
        options: dict[str, bool] | None = None,
    ) -> None:
        assert self.gateway is not None
        params: dict[str, Any] = {
            "sessionId": session_id,
            "callId": call_id,
            "result": result,
        }
        if options:
            params["options"] = options
        await self.gateway.request("talk.session.submitToolResult", params, timeout=30)

    async def _interrupt_for_wake_word(self) -> None:
        if not self.session_id or not self.audio:
            return
        LOGGER.info('Interrupción detectada: la persona ha dicho "Tipi"')
        self.conversation_log.event(
            "INTERRUPCION_POR_TIPI",
            "Respuesta detenida; Tipi vuelve a escuchar",
            turno=self._turn_number,
            desde_pregunta_ms=(
                self._elapsed_ms(self._turn_user_final_at)
                if self._turn_user_final_at is not None
                else None
            ),
        )
        self._barge_in_cancelled = True
        self._turn_interrupted = True
        self._suppress_output_until_user = True
        self.audio.clear_output()
        await self._cancel_output(reason="wake-word")
        await asyncio.sleep(0.05)
        self.audio.clear_output()
        self.audio.play_ready_beep()
        self._speech_started_at = None
        self._mark_activity()

    async def _cancel_output(self, reason: str = "barge-in") -> None:
        if not self.session_id or not self.gateway:
            return
        with suppress(Exception):
            await self.gateway.request(
                "talk.session.cancelOutput",
                {"sessionId": self.session_id, "reason": reason},
                timeout=10,
            )

    def _start_tool_task(self, coroutine: Any, *, name: str) -> None:
        task = asyncio.create_task(coroutine, name=name)
        self._tool_tasks.add(task)
        task.add_done_callback(self._tool_tasks.discard)

    async def _cancel_tool_tasks(self) -> None:
        tasks = tuple(self._tool_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.pending_tools.clear()

    async def _inactivity_loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            if not self.session_id or not self.audio:
                continue
            if self._audio_sender_task and self._audio_sender_task.done():
                sender_error = self._audio_sender_task.exception()
                if sender_error:
                    raise GatewayError(f"Falló el envío de audio: {sender_error}")
            if self.audio.output_error:
                raise self.audio.output_error
            if self.audio.is_playing.is_set() or self.pending_tools:
                continue
            if (
                time.monotonic() - self.last_activity
                >= self.settings.idle_timeout_seconds
            ):
                LOGGER.info(
                    "Conversación cerrada tras %.1f s de silencio",
                    self.settings.idle_timeout_seconds,
                )
                await self._close_session(notify_gateway=True, reason="silencio")

    async def _close_session(
        self, notify_gateway: bool, reason: str = "solicitado"
    ) -> None:
        if self._closing_session:
            return
        self._closing_session = True
        try:
            session_id, self.session_id = self.session_id, None
            if self._audio_sender_task:
                self._audio_sender_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._audio_sender_task
            self._audio_sender_task = None
            self._audio_sender_queue = None
            self._realtime_buffer.clear()
            await self._cancel_tool_tasks()
            if self.audio:
                self.audio.clear_output()
            if self.wake:
                self.wake.reset()
            self._drain_microphone_queue()
            if notify_gateway and session_id and self.gateway:
                with suppress(Exception):
                    await self.gateway.request(
                        "talk.session.close", {"sessionId": session_id}, timeout=10
                    )
            if session_id:
                self.conversation_log.event(
                    "SESION_CERRADA",
                    reason,
                    sesion=session_id[:8],
                    turnos=self._turn_number,
                    duracion_ms=(
                        self._elapsed_ms(self._session_started_at)
                        if self._session_started_at is not None
                        else None
                    ),
                )
                LOGGER.info(
                    'Tipi vuelve a estar atento a la palabra "%s"',
                    self.settings.wake_words[0],
                )
            self._session_started_at = None
            self._wake_detected_at = None
            self._speech_started_at = None
            self._turn_user_final_at = None
            self._turn_first_audio_ms = None
            self._turn_consulted = False
            self._turn_interrupted = False
            self._direct_response_finished = False
            self._duplicate_output_cancelled = False
            self._output_echo_guard_until = 0.0
            self._consult_wait_message_finished = False
            self._consult_result_ready = False
            self._consult_wait_output_cancelled = False
            self._suppress_output_until_user = False
            self._turn_number = 0
        finally:
            self._closing_session = False

    async def _health_loop(self) -> None:
        while True:
            self._touch_health_file()
            await asyncio.sleep(10)

    def _touch_health_file(self) -> None:
        path: Path | None = self.settings.health_file
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": time.time(),
            "version": __version__,
            "gatewayConnected": bool(
                self.gateway and not self.gateway.disconnected.is_set()
            ),
            "sessionActive": self.session_id is not None,
            "pendingTools": len(self.pending_tools),
            "inputDevice": self.audio.input_device_name if self.audio else None,
            "outputDevice": self.audio.output_device_name if self.audio else None,
            "microphoneLevel": self.audio_levels.microphone_level,
            "outputLevel": self.audio_levels.output_level,
            "speakerVoice": self.voice_preferences.voice,
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _mark_activity(self) -> None:
        self.last_activity = time.monotonic()

    def _is_duplicate_direct_response(self) -> bool:
        return self._direct_response_finished and not self.pending_tools

    def _output_is_active(self) -> bool:
        return bool(
            self.audio
            and (
                self.audio.is_playing.is_set()
                or time.monotonic() < self._output_echo_guard_until
            )
        )

    def _should_suppress_consult_wait_output(self) -> bool:
        return self._consult_wait_message_finished and not self._consult_result_ready

    def _begin_consult_wait(self) -> None:
        # Realtime may finish saying "Un momento" immediately before the
        # toolCall event arrives. Count that response as the waiting message.
        self._consult_wait_message_finished = self._direct_response_finished
        self._consult_result_ready = False
        self._consult_wait_output_cancelled = False
        self._direct_response_finished = False

    def _allow_consult_result_output(self) -> None:
        self._consult_result_ready = True
        self._consult_wait_output_cancelled = False
        self._direct_response_finished = False

    def _discard_pending_microphone_audio(self) -> None:
        self._speech_started_at = None
        self._realtime_rate_state = None
        self._realtime_buffer.clear()
        self._drain_microphone_queue()
        if self._audio_sender_queue is None:
            return
        while True:
            try:
                self._audio_sender_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _drain_microphone_queue(self) -> None:
        while True:
            try:
                self.mic_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

    def _on_output_done(self) -> None:
        self._mark_activity()
        self._output_echo_guard_until = (
            time.monotonic() + self.settings.output_echo_guard_seconds
        )
        self._speech_started_at = None
        self._realtime_buffer.clear()

    def _apply_spoken_audio_adjustment(self, text: str) -> None:
        if not self.audio:
            return
        started_at = time.monotonic()
        adjustment: AudioAdjustment | None = self.audio_levels.parse(text)
        if adjustment is None:
            return
        self.audio_levels.apply(adjustment)
        hardware_control = self._set_active_audio_level(
            adjustment.target, adjustment.level
        )
        if adjustment.target == "microfono":
            label = "sensibilidad del micrófono"
        else:
            label = "volumen de salida"
        LOGGER.info(
            "Ajustado %s: %s%% → %s%%",
            label,
            adjustment.previous,
            adjustment.level,
        )
        self.conversation_log.event(
            "AJUSTE_AUDIO",
            text,
            objetivo=adjustment.target,
            valor_anterior=adjustment.previous,
            valor_nuevo=adjustment.level,
            control_dispositivo=hardware_control,
            duracion_ms=self._elapsed_ms(started_at),
        )

    def _set_active_audio_level(self, target: str, level: int) -> bool:
        if not self.audio:
            return False
        hardware_control = bool(
            self.system_audio and self.system_audio.set_level(target, level)
        )
        if target == "microfono":
            digital_level = max(100, level) if hardware_control else level
            self.audio.set_input_level(digital_level)
        else:
            self.audio.set_output_level(100 if hardware_control else level)
        return hardware_control

    @staticmethod
    def _elapsed_ms(started_at: float | None) -> int | None:
        if started_at is None:
            return None
        return max(0, round((time.monotonic() - started_at) * 1000))

    @staticmethod
    def _consult_question(args: dict[str, Any]) -> str:
        return str(
            args.get("question")
            or args.get("prompt")
            or args.get("query")
            or args.get("task")
            or "Consulta sin texto"
        ).strip()

    @staticmethod
    def _parse_args(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        return {}

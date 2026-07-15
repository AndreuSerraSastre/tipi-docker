from __future__ import annotations

import asyncio
import inspect
import json
import logging
import platform
import sys
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from . import __version__
from .identity import DeviceIdentity, build_auth_payload

LOGGER = logging.getLogger(__name__)
PROTOCOL_VERSION = 4
EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class GatewayError(RuntimeError):
    pass


class GatewayClient:
    def __init__(self, url: str, token: str, identity: DeviceIdentity):
        self.url = url
        self.token = token
        self.identity = identity
        self.ws: Any = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._event_handlers: dict[str, list[EventHandler]] = {}
        self._event_queue: asyncio.Queue[
            tuple[str, dict[str, Any], tuple[EventHandler, ...]]
        ] = asyncio.Queue(maxsize=2048)
        self._event_task: asyncio.Task[None] | None = None
        self._recv_task: asyncio.Task[None] | None = None
        self._challenge: asyncio.Future[str] | None = None
        self._chat_waiters: dict[str, asyncio.Future[str]] = {}
        self._chat_results: OrderedDict[str, str | Exception] = OrderedDict()
        self.disconnected = asyncio.Event()

    async def connect(self) -> dict[str, Any]:
        self.disconnected.clear()
        self.ws = await websockets.connect(
            self.url,
            max_size=25 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        )
        loop = asyncio.get_running_loop()
        self._challenge = loop.create_future()
        self._event_task = asyncio.create_task(
            self._event_dispatch_loop(), name="gateway-events"
        )
        self._recv_task = asyncio.create_task(self._recv_loop(), name="gateway-recv")
        try:
            nonce = await asyncio.wait_for(self._challenge, timeout=10)
            params = self._connect_params(nonce)
            hello = await self.request("connect", params, timeout=15)
            LOGGER.info(
                "Conectado a OpenClaw Gateway (protocolo v%s)", PROTOCOL_VERSION
            )
            return hello
        except Exception:
            await self.close()
            raise

    def _connect_params(self, nonce: str) -> dict[str, Any]:
        client_id = "gateway-client"
        client_mode = "backend"
        role = "operator"
        scopes = ["operator.read", "operator.write", "operator.admin"]
        signed_at_ms = int(time.time() * 1000)
        current_platform = (
            "win32" if sys.platform == "win32" else platform.system().lower()
        )
        payload = build_auth_payload(
            identity=self.identity,
            client_id=client_id,
            client_mode=client_mode,
            role=role,
            scopes=scopes,
            signed_at_ms=signed_at_ms,
            token=self.token,
            nonce=nonce,
            platform=current_platform,
        )
        return {
            "minProtocol": PROTOCOL_VERSION,
            "maxProtocol": PROTOCOL_VERSION,
            "client": {
                "id": client_id,
                "displayName": "Tipi Voice",
                "version": __version__,
                "platform": current_platform,
                "mode": client_mode,
            },
            "caps": ["tool-events"],
            "role": role,
            "scopes": scopes,
            "auth": {"token": self.token},
            "device": {
                "id": self.identity.device_id,
                "publicKey": self.identity.public_key_base64url,
                "signature": self.identity.sign(payload),
                "signedAt": signed_at_ms,
                "nonce": nonce,
            },
        }

    async def request(
        self, method: str, params: Any = None, timeout: float = 30
    ) -> Any:
        if self.ws is None:
            raise GatewayError("Gateway no conectado")
        request_id = str(uuid.uuid4())
        frame: dict[str, Any] = {"type": "req", "id": request_id, "method": method}
        if params is not None:
            frame["params"] = params
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.ws.send(json.dumps(frame, ensure_ascii=False))
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    async def wait_for_chat_result(self, run_id: str, timeout: float = 120) -> str:
        cached = self._chat_results.pop(run_id, None)
        if cached is not None:
            if isinstance(cached, Exception):
                raise cached
            return cached
        future = asyncio.get_running_loop().create_future()
        self._chat_waiters[run_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._chat_waiters.pop(run_id, None)

    def on(self, event: str, handler: EventHandler) -> None:
        self._event_handlers.setdefault(event, []).append(handler)

    async def _recv_loop(self) -> None:
        try:
            async for raw in self.ws:
                message = json.loads(raw)
                if message.get("type") == "res":
                    self._handle_response(message)
                elif message.get("type") == "event":
                    self._handle_event(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Conexión con Gateway terminada: %s", exc)
            self._fail_pending(GatewayError(f"Conexión con Gateway terminada: {exc}"))
        finally:
            error = GatewayError("Conexión con Gateway terminada")
            self._fail_pending(error)
            if self._challenge and not self._challenge.done():
                self._challenge.set_exception(error)
            self.disconnected.set()

    def _handle_response(self, message: dict[str, Any]) -> None:
        future = self._pending.get(message.get("id", ""))
        if future is None or future.done():
            return
        if message.get("ok"):
            future.set_result(message.get("payload"))
            return
        error = message.get("error") or {}
        future.set_exception(
            GatewayError(error.get("message", "Error desconocido del Gateway"))
        )

    def _handle_event(self, message: dict[str, Any]) -> None:
        event = message.get("event", "")
        payload = message.get("payload") or {}
        if (
            event == "connect.challenge"
            and self._challenge
            and not self._challenge.done()
        ):
            nonce = payload.get("nonce")
            if isinstance(nonce, str) and nonce.strip():
                self._challenge.set_result(nonce.strip())
            return
        if event == "chat":
            self._handle_chat_event(payload)
        handlers = tuple(self._event_handlers.get(event, ()))
        if not handlers:
            return
        try:
            self._event_queue.put_nowait((event, payload, handlers))
        except asyncio.QueueFull as exc:
            raise GatewayError("La cola de eventos del Gateway se ha saturado") from exc

    async def _event_dispatch_loop(self) -> None:
        """Preserva el orden de eventos sin bloquear el receptor de respuestas."""
        while True:
            event, payload, handlers = await self._event_queue.get()
            try:
                for handler in handlers:
                    try:
                        result = handler(payload)
                        if inspect.isawaitable(result):
                            await result
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        LOGGER.exception("Error en manejador de evento %s", event)
            finally:
                self._event_queue.task_done()

    def _handle_chat_event(self, payload: dict[str, Any]) -> None:
        run_id = payload.get("runId")
        state = payload.get("state")
        if not run_id or state not in {"final", "error", "aborted"}:
            return
        if state == "final":
            content = (payload.get("message") or {}).get("content") or []
            result: str | Exception = "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("text")
            )
        else:
            result = GatewayError(payload.get("errorMessage") or f"Ejecución {state}")
        waiter = self._chat_waiters.get(run_id)
        if waiter is not None and not waiter.done():
            waiter.set_exception(result) if isinstance(
                result, Exception
            ) else waiter.set_result(result)
            return
        self._chat_results[run_id] = result
        while len(self._chat_results) > 32:
            self._chat_results.popitem(last=False)

    def _fail_pending(self, error: Exception) -> None:
        for future in list(self._pending.values()) + list(self._chat_waiters.values()):
            if not future.done():
                future.set_exception(error)

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception as exc:
                LOGGER.debug("Error al cerrar el WebSocket del Gateway: %s", exc)
        if self._recv_task:
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass
        self._fail_pending(GatewayError("Conexión con Gateway cerrada"))
        self.ws = None
        self._recv_task = None
        self._event_task = None

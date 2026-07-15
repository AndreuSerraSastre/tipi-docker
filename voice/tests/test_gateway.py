import asyncio
from types import SimpleNamespace

import pytest

from tipi_voice.gateway import GatewayClient


def _client() -> GatewayClient:
    return GatewayClient(
        "ws://gateway:18789",
        "test-token",
        SimpleNamespace(device_id="device"),
    )


@pytest.mark.asyncio
async def test_event_handlers_run_in_gateway_order() -> None:
    client = _client()
    release = asyncio.Event()
    seen: list[str] = []

    async def handler(payload: dict[str, int]) -> None:
        seen.append(f"start-{payload['sequence']}")
        if payload["sequence"] == 1:
            await release.wait()
        seen.append(f"end-{payload['sequence']}")

    client.on("talk.event", handler)
    client._event_task = asyncio.create_task(client._event_dispatch_loop())
    try:
        client._handle_event({"event": "talk.event", "payload": {"sequence": 1}})
        client._handle_event({"event": "talk.event", "payload": {"sequence": 2}})
        await asyncio.sleep(0)

        assert seen == ["start-1"]

        release.set()
        await asyncio.wait_for(client._event_queue.join(), timeout=1)
        assert seen == ["start-1", "end-1", "start-2", "end-2"]
    finally:
        client._event_task.cancel()
        await asyncio.gather(client._event_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_chat_result_is_delivered_while_event_handler_waits() -> None:
    client = _client()
    release = asyncio.Event()

    async def blocked_handler(_payload: dict[str, object]) -> None:
        await release.wait()

    client.on("talk.event", blocked_handler)
    client._event_task = asyncio.create_task(client._event_dispatch_loop())
    waiter = asyncio.get_running_loop().create_future()
    client._chat_waiters["run-1"] = waiter
    try:
        client._handle_event({"event": "talk.event", "payload": {"type": "audio"}})
        await asyncio.sleep(0)
        client._handle_event(
            {
                "event": "chat",
                "payload": {
                    "runId": "run-1",
                    "state": "final",
                    "message": {"content": [{"text": "resultado"}]},
                },
            }
        )

        assert await asyncio.wait_for(waiter, timeout=0.1) == "resultado"
    finally:
        release.set()
        await asyncio.wait_for(client._event_queue.join(), timeout=1)
        client._event_task.cancel()
        await asyncio.gather(client._event_task, return_exceptions=True)

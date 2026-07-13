from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import warnings

from .app import TipiVoiceApp
from .audio import list_devices
from .config import Settings
from .gateway import GatewayClient
from .identity import DeviceIdentity


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Puente local de voz para Tipi")
    parser.add_argument("--list-devices", action="store_true", help="muestra entradas y salidas")
    parser.add_argument("--check", action="store_true", help="comprueba configuración y Gateway")
    return parser.parse_args()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="audioop")


async def _check(settings: Settings) -> None:
    settings.validate()
    identity = DeviceIdentity.load_or_create(settings.state_dir)
    client = GatewayClient(settings.gateway_url, settings.gateway_token, identity)
    await client.connect()
    try:
        catalog = await client.request("talk.catalog", {}, timeout=20)
        realtime = catalog.get("realtime") or {}
        active_provider = realtime.get("activeProvider")
        providers = realtime.get("providers") or []
        if not any(
            provider.get("configured")
            and (not active_provider or provider.get("id") == active_provider)
            for provider in providers
            if isinstance(provider, dict)
        ):
            raise RuntimeError("OpenClaw Talk Realtime no figura como preparado")
        print("Configuración, modelo de activación y OpenClaw Talk: OK")
    finally:
        await client.close()


async def _run_with_reconnect(settings: Settings) -> None:
    delay = 2
    while True:
        try:
            await TipiVoiceApp(settings).run()
            delay = 2
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.getLogger(__name__).error("Tipi Voice se reiniciará: %s", exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


def main() -> int:
    args = _arguments()
    settings = Settings.from_env()
    _configure_logging(settings.log_level)
    if args.list_devices:
        print(list_devices())
        return 0
    try:
        if args.check:
            asyncio.run(_check(settings))
        else:
            asyncio.run(_run_with_reconnect(settings))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


AudioTarget = Literal["microfono", "salida"]
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioAdjustment:
    target: AudioTarget
    previous: int
    level: int


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9%]+", " ", value).strip()


_NUMBER_WORDS = {
    "cero": 0,
    "cinco": 5,
    "diez": 10,
    "quince": 15,
    "veinte": 20,
    "veinticinco": 25,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
    "ciento cincuenta": 150,
    "doscientos": 200,
    "doscientos cincuenta": 250,
    "trescientos": 300,
}


def _spoken_number(text: str) -> int | None:
    digit = re.search(r"\b(\d{1,3})\s*(?:%|por ciento)?\b", text)
    if digit:
        return int(digit.group(1))
    text = re.sub(r"\bpor ciento\b", "", text)
    for phrase, number in sorted(_NUMBER_WORDS.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return number
    return None


def parse_audio_command(
    text: str,
    *,
    microphone_level: int,
    output_level: int,
) -> AudioAdjustment | None:
    normalized = _normalize(text)
    microphone_target = bool(
        re.search(r"\b(microfono|micro|sensibilidad|entrada)\b", normalized)
    )
    output_target = bool(
        re.search(r"\b(volumen|auriculares|altavoces|altavoz|sonido|voz)\b", normalized)
    )
    if not microphone_target and not output_target:
        return None
    target: AudioTarget = "microfono" if microphone_target else "salida"
    current = microphone_level if target == "microfono" else output_level

    increase = bool(
        re.search(r"\b(sube|subir|aumenta|aumentar|incrementa|incrementar)\b", normalized)
        or "mas alto" in normalized
        or "mas fuerte" in normalized
    )
    decrease = bool(
        re.search(r"\b(baja|bajar|reduce|reducir|disminuye|disminuir)\b", normalized)
        or "mas bajo" in normalized
        or "menos fuerte" in normalized
    )
    set_level = bool(
        re.search(r"\b(pon|poner|ajusta|ajustar|fija|fijar|establece|deja)\b", normalized)
    )
    silence = bool(re.search(r"\b(silencia|silenciar|mutea|mutear|mudo)\b", normalized))
    maximum = bool(re.search(r"\b(maximo|maxima|tope)\b", normalized))
    minimum = bool(re.search(r"\b(minimo|minima)\b", normalized))
    number = _spoken_number(normalized)
    absolute_number = number is not None and bool(
        re.search(r"\b(al|a|en)\s+(?:\d{1,3}|[a-z]+)", normalized)
    )
    if not any((increase, decrease, set_level, silence, maximum, minimum, absolute_number)):
        return None

    lower, upper = (25, 300) if target == "microfono" else (0, 100)
    if silence and target == "salida":
        requested = 0
    elif maximum:
        requested = upper
    elif minimum:
        requested = lower
    elif set_level or absolute_number:
        if number is None:
            return None
        requested = number
    elif increase:
        requested = current + (number if number is not None else 10)
    elif decrease:
        requested = current - (number if number is not None else 10)
    else:
        return None
    return AudioAdjustment(target, current, max(lower, min(upper, requested)))


class AudioLevelStore:
    def __init__(self, path: Path):
        self.path = path
        self.microphone_level = 100
        self.output_level = 100
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.microphone_level = max(25, min(300, int(data["microphone_level"])))
            self.output_level = max(0, min(100, int(data["output_level"])))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return

    def parse(self, text: str) -> AudioAdjustment | None:
        return parse_audio_command(
            text,
            microphone_level=self.microphone_level,
            output_level=self.output_level,
        )

    def apply(self, adjustment: AudioAdjustment) -> None:
        if adjustment.target == "microfono":
            self.microphone_level = adjustment.level
        else:
            self.output_level = adjustment.level
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "microphone_level": self.microphone_level,
                    "output_level": self.output_level,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class SystemAudioController:
    """Controla los endpoints reales de Windows; en otros sistemas usa el respaldo digital."""

    def __init__(self, input_device_name: str, output_device_name: str):
        self.input_device_name = input_device_name
        self.output_device_name = output_device_name

    def set_level(self, target: AudioTarget, level: int) -> bool:
        if sys.platform != "win32":
            return False
        try:
            from pycaw.constants import DEVICE_STATE, EDataFlow
            from pycaw.pycaw import AudioUtilities

            flow = EDataFlow.eCapture if target == "microfono" else EDataFlow.eRender
            expected_name = self.input_device_name if target == "microfono" else self.output_device_name
            expected = _normalize(expected_name)
            devices = AudioUtilities.GetAllDevices(flow.value, DEVICE_STATE.ACTIVE.value)
            device = next(
                (
                    candidate
                    for candidate in devices
                    if expected in _normalize(candidate.FriendlyName)
                    or _normalize(candidate.FriendlyName) in expected
                ),
                None,
            )
            if device is None:
                LOGGER.warning("No se encontró el endpoint de Windows para %s", expected_name)
                return False
            scalar = max(0.0, min(1.0, level / 100))
            device.EndpointVolume.SetMasterVolumeLevelScalar(scalar, None)
            device.EndpointVolume.SetMute(1 if level == 0 else 0, None)
            actual = round(device.EndpointVolume.GetMasterVolumeLevelScalar() * 100)
            LOGGER.info("Nivel real de Windows ajustado: %s al %s%%", device.FriendlyName, actual)
            return abs(actual - min(level, 100)) <= 1
        except Exception:
            LOGGER.exception("No se pudo ajustar el nivel real del dispositivo; se usará control digital")
            return False

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:proj|live|test)?-?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bATATT[A-Za-z0-9_=-]{12,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(api[_ -]?key|token|password|contraseña)(\s*[:=]\s*)([^\s,;]+)"),
)


def _redact_text(value: str) -> str:
    redacted = value
    for index, pattern in enumerate(_SECRET_PATTERNS):
        if index == len(_SECRET_PATTERNS) - 1:
            redacted = pattern.sub(r"\1\2[REDACTADO]", redacted)
        else:
            redacted = pattern.sub("[REDACTADO]", redacted)
    return redacted


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = re.sub(r"[^a-z0-9]", "", key_text.lower())
            if any(
                secret_name in normalized_key
                for secret_name in ("apikey", "token", "password", "contraseña")
            ):
                safe[key_text] = "[REDACTADO]"
            else:
                safe[key_text] = _redact(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class ConversationLogger:
    """Registro diario legible y JSONL de la conversación, sin credenciales."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def latest_readable_path(self) -> Path:
        return self.directory / f"tipi-{datetime.now().astimezone():%Y-%m-%d}.log"

    def event(self, event_type: str, message: str = "", **fields: Any) -> None:
        now = datetime.now().astimezone()
        safe_message = (
            _redact_text(message).replace("\r", " ").replace("\n", " ").strip()
        )
        safe_fields = _redact(fields)
        record = {
            "timestamp": now.isoformat(timespec="milliseconds"),
            "event": event_type,
            "message": safe_message,
            **safe_fields,
        }
        readable_path = self.directory / f"tipi-{now:%Y-%m-%d}.log"
        jsonl_path = self.directory / f"tipi-{now:%Y-%m-%d}.jsonl"
        detail = " | ".join(
            f"{key}={self._format_readable(value)}"
            for key, value in safe_fields.items()
        )
        readable = f"{now:%Y-%m-%d %H:%M:%S.%f}"[:-3] + f" | {event_type}"
        if safe_message:
            readable += f" | {safe_message}"
        if detail:
            readable += f" | {detail}"
        with self._lock:
            with readable_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(readable + "\n")
            with jsonl_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                )

    @staticmethod
    def _format_readable(value: Any) -> str:
        if isinstance(value, bool):
            return "sí" if value else "no"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value)

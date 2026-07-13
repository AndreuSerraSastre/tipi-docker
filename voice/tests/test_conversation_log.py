import json
from pathlib import Path

from tipi_voice.conversation_log import ConversationLogger


def test_conversation_log_writes_readable_and_jsonl(tmp_path: Path) -> None:
    log = ConversationLogger(tmp_path)
    log.event("PERSONA", "¿Qué hora es?", turno=1, transcripcion_ms=420)

    readable = next(tmp_path.glob("tipi-*.log")).read_text(encoding="utf-8")
    record = json.loads(next(tmp_path.glob("tipi-*.jsonl")).read_text(encoding="utf-8"))
    assert "PERSONA | ¿Qué hora es?" in readable
    assert "transcripcion_ms=420" in readable
    assert record["message"] == "¿Qué hora es?"


def test_conversation_log_redacts_credentials(tmp_path: Path) -> None:
    log = ConversationLogger(tmp_path)
    log.event(
        "PRUEBA",
        "api_key=" + "sk-" + "test-1234567890abcdefghijkl",
        argumentos={"access_token": "un-secreto-no-reconocible"},
    )

    contents = "".join(path.read_text(encoding="utf-8") for path in tmp_path.iterdir())
    assert "test-1234567890abcdefghijkl" not in contents
    assert "un-secreto-no-reconocible" not in contents
    assert "[REDACTADO]" in contents

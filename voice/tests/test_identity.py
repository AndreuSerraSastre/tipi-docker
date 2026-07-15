import base64
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tipi_voice.identity import DeviceIdentity, build_auth_payload


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_identity_is_stable_and_signs_openclaw_v3_payload(tmp_path: Path) -> None:
    first = DeviceIdentity.load_or_create(tmp_path)
    second = DeviceIdentity.load_or_create(tmp_path)
    assert first == second
    assert first.device_id == hashlib.sha256(first.public_key_raw).hexdigest()

    payload = build_auth_payload(
        identity=first,
        client_id="gateway-client",
        client_mode="backend",
        role="operator",
        scopes=["operator.read", "operator.write"],
        signed_at_ms=1234,
        token="secret",
        nonce="nonce",
        platform="Win32",
    )
    assert payload == (
        f"v3|{first.device_id}|gateway-client|backend|operator|"
        "operator.read,operator.write|1234|secret|nonce|win32|"
    )
    Ed25519PublicKey.from_public_bytes(first.public_key_raw).verify(
        _decode(first.sign(payload)), payload.encode()
    )

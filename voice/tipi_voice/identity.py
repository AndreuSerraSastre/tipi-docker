from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    private_key_raw: bytes
    public_key_raw: bytes

    @classmethod
    def load_or_create(cls, state_dir: Path) -> "DeviceIdentity":
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / "device-identity.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            private_raw = _b64url_decode(data["privateKey"])
            key = Ed25519PrivateKey.from_private_bytes(private_raw)
            public_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            device_id = hashlib.sha256(public_raw).hexdigest()
            return cls(device_id, private_raw, public_raw)

        key = Ed25519PrivateKey.generate()
        private_raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        public_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        device_id = hashlib.sha256(public_raw).hexdigest()
        payload = {
            "version": 1,
            "deviceId": device_id,
            "privateKey": _b64url(private_raw),
            "publicKey": _b64url(public_raw),
        }
        temporary = path.with_suffix(".tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, indent=2) + "\n")
        temporary.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return cls(device_id, private_raw, public_raw)

    @property
    def public_key_base64url(self) -> str:
        return _b64url(self.public_key_raw)

    def sign(self, payload: str) -> str:
        key = Ed25519PrivateKey.from_private_bytes(self.private_key_raw)
        return _b64url(key.sign(payload.encode("utf-8")))


def build_auth_payload(
    *,
    identity: DeviceIdentity,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: str,
    nonce: str,
    platform: str,
    device_family: str = "",
) -> str:
    values = [
        "v3",
        identity.device_id,
        client_id,
        client_mode,
        role,
        ",".join(scopes),
        str(signed_at_ms),
        token,
        nonce,
        platform.strip().lower(),
        device_family.strip().lower(),
    ]
    return "|".join(values)

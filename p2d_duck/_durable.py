from __future__ import annotations

import base64
import uuid
from typing import Any, Dict, Optional, Tuple

try:
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False


def _b64u_int(i: int) -> str:
    length = (i.bit_length() + 7) // 8 or 1
    return base64.urlsafe_b64encode(i.to_bytes(length, "big")).rstrip(b"=").decode()


_FALLBACK_JWK = {
    "alg": "RSA-OAEP-256",
    "e": "AQAB",
    "ext": True,
    "key_ops": ["encrypt"],
    "kty": "RSA",
    "n": (
        "v_5E_s7W6bpLjeNqftiEP8r0GqzkiK38XWtuYB0zQyEtINgr7CIoTjlUohX89-LZrOE5"
        "Y7cSFDkMSvu6oaTDuwEdr8qk2--bCfFzZ7eYGJxv0YpQVL4n5d2g7sV4QvQXWFXEKsoH"
        "vYtyvzYqQwT3oH-3v8b6m4HXJqgJ8c-Q3Px4_4qjZqXgN1nZ7gRxYvLhOZk1mY2pZqA1"
        "kHvZK1Bp7XB6JjhPq5oA8VsZsnv_HoCe2qsYjZqe5pHVZsHqI8TmQX-Vp7nW0xKmjvhc"
        "GhGJzWvN6e7TmPzv5sLNqXWEt8aLZ4yCzbOtPGdN3qkHaJYP9JmVwVpSf3aRwI3rWZx9"
        "TpHwRcD0aSGq1cF8N7XpQTwjXLqJ0xvVzDYqEd2qFYbmQ"
    ),
    "use": "enc",
}


def generate_jwk() -> Dict[str, Any]:
    if not _HAS_CRYPTO:
        return dict(_FALLBACK_JWK)
    key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nums = key.public_key().public_numbers()
    return {
        "alg": "RSA-OAEP-256",
        "e": _b64u_int(nums.e),
        "ext": True,
        "key_ops": ["encrypt"],
        "kty": "RSA",
        "n": _b64u_int(nums.n),
        "use": "enc",
    }


def make_durable_stream(jwk: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "messageId": str(uuid.uuid4()),
        "conversationId": str(uuid.uuid4()),
        "publicKey": jwk or generate_jwk(),
    }

import hashlib
import hmac
import time
import uuid
from urllib.parse import urlencode


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_canonical_string(
    timestamp: str,
    nonce: str,
    method: str,
    path: str,
    query_string: str,
    body: bytes,
) -> str:
    body_hash = sha256_hex(body)
    return f"{timestamp}\n{nonce}\n{method}\n{path}\n{query_string}\n{body_hash}"


def compute_signature(signing_key: str, canonical_string: str) -> str:
    """signing_key is sha256(raw_secret). Both client and server use the hash as HMAC key."""
    return hmac.new(signing_key.encode(), canonical_string.encode(), hashlib.sha256).hexdigest()


def build_canonical_query_string(query_params: dict) -> str:
    if not query_params:
        return ""
    return urlencode(sorted(query_params.items()))


# --- Client-side helper (for testing / bot SDK) ---

def sign_request(
    api_key: str,
    secret_key_raw: str,
    method: str,
    path: str,
    query_params: dict | None = None,
    body: bytes = b"",
) -> dict:
    """Build auth headers.
    signing_key = sha256(secret_key_raw) — consistent with server which stores sha256 hash.
    """
    signing_key = sha256_hex(secret_key_raw.encode())
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    qs = build_canonical_query_string(query_params or {})
    canonical = build_canonical_string(timestamp, nonce, method.upper(), path, qs, body)
    signature = compute_signature(signing_key, canonical)
    return {
        "X-API-KEY": api_key,
        "X-TIMESTAMP": timestamp,
        "X-NONCE": nonce,
        "X-SIGNATURE": signature,
    }

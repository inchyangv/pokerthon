import hashlib
import secrets


def generate_api_key() -> str:
    return "pk_live_" + secrets.token_urlsafe(32)


def generate_secret_key() -> str:
    return "sk_live_" + secrets.token_urlsafe(40)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def verify_secret(secret: str, secret_hash: str) -> bool:
    return hash_secret(secret) == secret_hash

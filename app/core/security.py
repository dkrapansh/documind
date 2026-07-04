import hashlib
import secrets

def generate_api_key() -> str:
    return f"dm_{secrets.token_urlsafe(32)}"

def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
import hashlib
from pathlib import Path

from app.config import settings

def compute_content_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()

def save_file(content_hash: str, original_filename: str, file_bytes: bytes) -> Path:
    storage_path = Path(settings.storage_dir)
    storage_path.mkdir(parents=True, exist_ok=True)

    extension = Path(original_filename).suffix
    destination = storage_path / f"{content_hash}{extension}"

    if not destination.exists():
        destination.write_bytes(file_bytes)

    return destination
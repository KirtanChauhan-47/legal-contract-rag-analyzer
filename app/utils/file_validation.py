import os

from app.core.config import get_settings
from app.core.exceptions import ValidationError


def validate_upload(filename: str, contents: bytes) -> None:
    """Reject empty files, disallowed extensions, and oversized uploads
    before anything touches disk or the DB."""
    settings = get_settings()

    if not contents:
        raise ValidationError("Uploaded file is empty.")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in settings.allowed_extensions:
        allowed = ", ".join(settings.allowed_extensions)
        raise ValidationError(f"Unsupported file type '{ext}'. Allowed types: {allowed}")

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise ValidationError(f"File exceeds max size of {settings.max_file_size_mb}MB.")

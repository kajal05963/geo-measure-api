import os
from dataclasses import dataclass

MB = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    db_path: str
    max_upload_bytes: int
    max_uncompressed_bytes: int  # zip-bomb guard
    max_zip_members: int


def get_settings() -> Settings:
    """Read settings from the environment on each call (keeps tests simple)."""
    return Settings(
        db_path=os.getenv("GEO_DB_PATH", "data/geo.db"),
        max_upload_bytes=int(os.getenv("GEO_MAX_UPLOAD_MB", "50")) * MB,
        max_uncompressed_bytes=int(os.getenv("GEO_MAX_UNCOMPRESSED_MB", "300")) * MB,
        max_zip_members=int(os.getenv("GEO_MAX_ZIP_MEMBERS", "200")),
    )

"""Local runtime settings for receipt intake."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# A phone photo or flatbed scan of a retail receipt fits comfortably in 10 MB.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Multipart bodies include boundaries and headers around the file bytes.
MULTIPART_OVERHEAD_BYTES = 256 * 1024
# Reject decompression bombs while still allowing a high-resolution receipt photo.
MAX_IMAGE_PIXELS = 80_000_000

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "receipt_evidence"
STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int = MAX_UPLOAD_BYTES
    allow_preview_embedding: bool = False

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "evidence.sqlite"

    # Persistence rule (Nov 4, 2026): every database lives UNDER data_dir,
    # which is the path mounted as the Docker volume. The previous
    # data_dir.parent layout put all DBs except evidence.sqlite inside
    # the container filesystem, so every container rebuild wiped
    # purchases, pantry, memory, extractions and corrections.
    @property
    def extraction_db_path(self) -> Path:
        return self.data_dir / "receipt_extraction" / "extractions.sqlite"

    @property
    def confirmed_db_path(self) -> Path:
        return self.data_dir / "confirmed_purchases" / "confirmed.sqlite"

    @property
    def memory_db_path(self) -> Path:
        return self.data_dir / "purchase_memory" / "memory.sqlite"

    @property
    def visual_db_path(self) -> Path:
        return self.data_dir / "visual_recall" / "visual.sqlite"

    @property
    def max_upload_megabytes(self) -> int:
        return self.max_upload_bytes // (1024 * 1024)


def load_settings() -> Settings:
    override = os.environ.get("PIA_DATA_DIR")
    data_dir = Path(override) if override else DEFAULT_DATA_DIR
    return Settings(
        data_dir=data_dir,
        allow_preview_embedding=bool(os.environ.get("REPLIT_DEV_DOMAIN")),
    )


def size_limit_message(max_upload_bytes: int = MAX_UPLOAD_BYTES) -> str:
    megabytes = max_upload_bytes // (1024 * 1024)
    return f"File exceeds the {megabytes} MB limit."

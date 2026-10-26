from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.config import OUTPUT_DIR


class Status(Enum):
    PENDING = ("Chờ tải", "#8a8f98")
    DOWNLOADING = ("Đang tải", "#4ea1ff")
    READY = ("Sẵn sàng", "#3ecf8e")
    PROCESSING = ("Đang xử lý", "#f5a524")
    RENDERING = ("Đang render", "#f5a524")
    UPLOADING = ("Đang upload", "#b07cff")
    DONE = ("Hoàn tất", "#2fbf71")
    ERROR = ("Lỗi", "#ff5c5c")

    def __init__(self, label: str, color: str):
        self.label = label
        self.color = color

    @property
    def busy(self) -> bool:
        return self in (Status.DOWNLOADING, Status.PROCESSING, Status.RENDERING, Status.UPLOADING)


@dataclass
class BlurRegion:
    """Vùng làm mờ, toạ độ chuẩn hoá 0..1 theo khung video."""
    x: float
    y: float
    w: float
    h: float
    start_ms: int = 0
    end_ms: int | None = None  # None = áp dụng toàn bộ video
    strength: int = 20


@dataclass
class SubtitleLine:
    start_ms: int
    end_ms: int
    text: str = ""          # sub mới sẽ chèn vào vùng mờ
    original: str = ""      # sub gốc (OCR / nhận dạng)
    audio_path: Path | None = None  # audio voice AI đã tạo cho dòng này


@dataclass
class VoiceInfo:
    id: str
    name: str
    locale: str
    gender: str
    provider: str


@dataclass
class VoiceSettings:
    provider: str = "edge"
    voice_id: str = "vi-VN-HoaiMyNeural"
    rate: int = 0    # %
    pitch: int = 0   # Hz
    volume: int = 0  # %


@dataclass
class SubStyle:
    font_family: str = "Arial"
    font_size: int = 56  # px theo độ phân giải gốc của video
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    bold: bool = True


@dataclass
class ExportSettings:
    output_dir: Path = OUTPUT_DIR
    renderer_id: str = "ffmpeg"
    resolution: str = "original"
    apply_blur: bool = True
    burn_subs: bool = True
    add_voice: bool = True
    keep_original_audio: bool = True
    original_volume: int = 20  # %
    uploader_id: str = "mock"
    drive_folder: str = ""
    auto_upload: bool = False


@dataclass
class VideoProject:
    url: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    local_path: Path | None = None
    status: Status = Status.PENDING
    progress: int = 0
    error: str = ""
    regions: list[BlurRegion] = field(default_factory=list)
    subtitles: list[SubtitleLine] = field(default_factory=list)
    output_path: Path | None = None
    drive_link: str = ""

    @property
    def display_name(self) -> str:
        if self.title:
            return self.title
        if self.local_path:
            return self.local_path.stem
        return self.url

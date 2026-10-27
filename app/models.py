from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.config import DEFAULT_GEMINI_API_KEYS, OUTPUT_DIR


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
    text: str = ""  # dòng chữ OCR đọc được trong vùng này -> xoá vùng thì bỏ đúng dòng đó khỏi sub gốc


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
    custom: bool = False  # giọng người dùng tự thêm (clone), xoá được


@dataclass
class VoiceSettings:
    provider: str = "vieneu"
    voice_id: str = "Hải Đăng"  # giọng mặc định của VieNeu-TTS v3 Turbo
    rate: int = 0    # %
    pitch: int = 0   # nửa cung
    volume: int = 0  # %


@dataclass
class TranslateSettings:
    provider: str = "subtrans"
    source_lang: str = "Chinese"
    target_lang: str = "Vietnamese"
    # Gemini API key, thử lần lượt từ trên xuống (xem MODEL_CHAIN trong services/translate/subtrans.py)
    api_keys: list[str] = field(default_factory=lambda: [k for k in DEFAULT_GEMINI_API_KEYS if k])
    model: str = "gemini-3.8-flash"  # model bắt đầu; lỗi / hết lượt thì xuống 3.6-flash, rồi 3.5-flash-lite
    skip_analysis: bool = False  # bỏ lượt 1 (phân tích ngữ cảnh): nhanh hơn, kém nhất quán hơn
    fit_duration: bool = True    # lượt 3: rút gọn câu dịch dài hơn thời lượng câu -> giọng đọc khớp hình


@dataclass
class SubStyle:
    font_family: str = "Arial"
    font_size: int = 56  # px theo độ phân giải gốc của video
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    bold: bool = True
    bg_box: bool = False        # False = nền trong suốt (chữ có viền); True = khung màu sau chữ
    bg_color: str = "#000000"
    bg_opacity: int = 60        # % độ đậm của khung nền


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
    uploader_id: str = "gdrive"
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
    goal: str = "dub"                      # mục tiêu: "blur" | "subs" | "dub" (xem ui/workflow.py)
    busy_step: str | None = None           # bước đang chạy cho video này
    waiting_step: str | None = None        # bước đang xếp hàng chờ video khác chạy xong (tìm sub / lồng tiếng)
    step_progress: tuple[int, str] = (0, "")
    step_errors: dict[str, str] = field(default_factory=dict)
    rev: int = 0                           # tăng mỗi lần dữ liệu đổi (vùng mờ, sub, giọng, kiểu chữ)
    exported_rev: int = -1                 # rev lúc xuất lần gần nhất -> khác rev = video xuất đã cũ

    @property
    def display_name(self) -> str:
        if self.title:
            return self.title
        if self.local_path:
            return self.local_path.stem
        return self.url

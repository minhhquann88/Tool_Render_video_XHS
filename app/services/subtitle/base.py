from abc import ABC, abstractmethod
from pathlib import Path

from app.models import BlurRegion, SubtitleLine
from app.services.common import ProgressFn, no_progress


class RegionDetector(ABC):
    """Tự động tìm vùng có sub gốc để làm mờ."""
    id: str = ""
    name: str = ""

    @abstractmethod
    def detect(self, video_path: Path, progress: ProgressFn = no_progress) -> list[BlurRegion]: ...

    def forget(self, video_path: Path) -> None:
        """Bỏ kết quả đã nhớ của video này -> lần detect sau quét lại thật (nút "Tìm lại")."""


class SubtitleSource(ABC):
    """Sinh danh sách sub mới (OCR + dịch, Whisper, ...)."""
    id: str = ""
    name: str = ""

    @abstractmethod
    def generate(self, video_path: Path, regions: list[BlurRegion], duration_ms: int,
                 progress: ProgressFn = no_progress) -> list[SubtitleLine]: ...

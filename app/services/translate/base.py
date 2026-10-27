from abc import ABC, abstractmethod

from app.models import SubtitleLine, TranslateSettings
from app.services.common import ProgressFn, no_progress


class Translator(ABC):
    """Dịch sub gốc -> sub mới. Mỗi nguồn dịch (subtrans/OpenAI, ...) là một provider."""
    id: str = ""
    name: str = ""

    @abstractmethod
    def translate(self, lines: list[SubtitleLine], title: str, settings: TranslateSettings,
                  progress: ProgressFn = no_progress) -> list[str]:
        """Trả về bản dịch theo đúng thứ tự `lines` (cùng số phần tử)."""

    def shorten(self, lines: list[SubtitleLine], indices: list[int], settings: TranslateSettings,
                progress: ProgressFn = no_progress) -> dict[int, str]:
        """Rút gọn câu sub mới `indices` (trong `lines`) cho vừa thời lượng -> {chỉ số: câu mới}."""
        raise NotImplementedError(f"{self.name} chưa hỗ trợ rút gọn câu")

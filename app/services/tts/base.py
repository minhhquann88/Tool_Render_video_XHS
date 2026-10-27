import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import TTS_CACHE_DIR
from app.models import VoiceInfo, VoiceSettings
from app.services.common import ProgressFn, no_progress

# câu nghe thử mặc định; provider có thể tạo sẵn audio cho câu này để nghe ngay
SAMPLE_TEXT = "Xin chào, đây là giọng đọc thử cho video của bạn."


class TTSProvider(ABC):
    """Mỗi nguồn voice AI (VieNeu, ElevenLabs, FPT...) là một provider."""
    id: str = ""
    name: str = ""
    supports_clone: bool = False

    @abstractmethod
    def list_voices(self, refresh: bool = False, progress: ProgressFn = no_progress) -> list[VoiceInfo]: ...

    @abstractmethod
    def synthesize(self, text: str, settings: VoiceSettings, out_path: Path,
                   progress: ProgressFn = no_progress) -> Path: ...

    def warm_up(self, progress: ProgressFn = no_progress) -> None:
        """Nạp sẵn mô hình ở nền để lần tạo giọng đầu không phải chờ."""

    def cached_preview(self, text: str, settings: VoiceSettings) -> Path | None:
        """Audio nghe thử đã có sẵn (gọi trên luồng UI, không được chạy mô hình)."""
        path = self._preview_path(text, settings)
        return path if path.exists() else None

    def preview(self, text: str, settings: VoiceSettings, progress: ProgressFn = no_progress) -> Path:
        return self.cached_preview(text, settings) or \
            self.synthesize(text, settings, self._preview_path(text, settings), progress)

    def clone_voice(self, name: str, audio_path: Path, progress: ProgressFn = no_progress) -> VoiceInfo:
        raise NotImplementedError(f"{self.name} không hỗ trợ clone giọng")

    def remove_voice(self, voice_id: str) -> None:
        raise NotImplementedError(f"{self.name} không hỗ trợ xoá giọng")

    @staticmethod
    def _preview_path(text: str, settings: VoiceSettings) -> Path:
        key = hashlib.sha1(f"{settings}|{text}".encode("utf-8")).hexdigest()[:16]
        return TTS_CACHE_DIR / "preview" / f"{key}.wav"

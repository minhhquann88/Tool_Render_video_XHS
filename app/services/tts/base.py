from abc import ABC, abstractmethod
from pathlib import Path

from app.models import VoiceInfo, VoiceSettings
from app.services.common import ProgressFn, no_progress


class TTSProvider(ABC):
    """Mỗi nguồn voice AI (Edge, ElevenLabs, FPT...) là một provider."""
    id: str = ""
    name: str = ""

    @abstractmethod
    def list_voices(self, refresh: bool = False, progress: ProgressFn = no_progress) -> list[VoiceInfo]: ...

    @abstractmethod
    def synthesize(self, text: str, settings: VoiceSettings, out_path: Path,
                   progress: ProgressFn = no_progress) -> Path: ...

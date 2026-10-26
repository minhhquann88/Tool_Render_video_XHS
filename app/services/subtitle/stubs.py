"""Chỗ cắm cho các công nghệ sẽ chốt sau."""
from pathlib import Path

from app.models import BlurRegion, SubtitleLine
from app.services.common import ProgressFn, no_progress
from app.services.subtitle.base import SubtitleSource


class WhisperSource(SubtitleSource):
    id = "whisper"
    name = "Nhận dạng giọng nói (chưa cài)"

    def generate(self, video_path: Path, regions: list[BlurRegion], duration_ms: int,
                 progress: ProgressFn = no_progress) -> list[SubtitleLine]:
        # TODO: tách audio -> Whisper -> dịch
        raise NotImplementedError("nhận dạng giọng nói")

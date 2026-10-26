from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.models import ExportSettings, SubStyle, VideoProject, VoiceSettings
from app.services.common import ProgressFn, no_progress


@dataclass
class RenderContext:
    style: SubStyle
    voice: VoiceSettings
    export: ExportSettings


class Renderer(ABC):
    id: str = ""
    name: str = ""

    @abstractmethod
    def render(self, project: VideoProject, ctx: RenderContext, out_path: Path,
               progress: ProgressFn = no_progress) -> Path: ...

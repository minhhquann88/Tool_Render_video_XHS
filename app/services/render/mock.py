import shutil
import time
from pathlib import Path

from app.models import VideoProject
from app.services.common import ProgressFn, no_progress
from app.services.render.base import RenderContext, Renderer


class MockRenderer(Renderer):
    """Giả lập các bước render rồi copy file gốc ra output.

    Bản thật (FFmpeg) sẽ: boxblur theo từng BlurRegion -> burn sub (ASS) vào vùng mờ
    -> trộn audio voice AI theo mốc thời gian, giảm âm lượng tiếng gốc -> encode H.264.
    """
    id = "mock"
    name = "Giả lập (chưa có FFmpeg)"

    def render(self, project: VideoProject, ctx: RenderContext, out_path: Path,
               progress: ProgressFn = no_progress) -> Path:
        steps = []
        if ctx.export.apply_blur and project.regions:
            steps.append(f"Làm mờ {len(project.regions)} vùng")
        if ctx.export.burn_subs and project.subtitles:
            steps.append(f"Chèn {len(project.subtitles)} dòng sub")
        if ctx.export.add_voice:
            steps.append("Ghép giọng đọc AI")
        steps.append("Mã hoá video")

        ticks = 12
        for i, step in enumerate(steps):
            for k in range(ticks):
                time.sleep(0.06)
                progress(int((i * ticks + k + 1) / (len(steps) * ticks) * 100), step)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project.local_path, out_path)
        return out_path

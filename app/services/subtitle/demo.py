"""Bản giả lập để chạy thử giao diện khi chưa chốt công nghệ OCR / dịch."""
import time
from pathlib import Path

from app.models import BlurRegion, SubtitleLine
from app.services.common import ProgressFn, no_progress
from app.services.subtitle.base import RegionDetector, SubtitleSource

_SAMPLES = [
    ("大家好，欢迎来到我的频道", "Xin chào mọi người, chào mừng đến với kênh của mình"),
    ("今天给大家分享一个小技巧", "Hôm nay mình chia sẻ với các bạn một mẹo nhỏ"),
    ("只需要三个步骤就可以完成", "Chỉ cần ba bước là có thể hoàn thành"),
    ("记得点赞收藏哦", "Nhớ thả tim và lưu lại nhé"),
]


class BottomBandDetector(RegionDetector):
    id = "demo_bottom"
    name = "Dải dưới (demo)"

    def detect(self, video_path: Path, progress: ProgressFn = no_progress) -> list[BlurRegion]:
        for i in range(10):
            time.sleep(0.08)
            progress((i + 1) * 10, "Đang quét khung hình…")
        return [BlurRegion(x=0.06, y=0.78, w=0.88, h=0.09)]


class DemoSubtitleSource(SubtitleSource):
    id = "demo"
    name = "Sub mẫu (demo)"

    def generate(self, video_path: Path, regions: list[BlurRegion], duration_ms: int,
                 progress: ProgressFn = no_progress) -> list[SubtitleLine]:
        total = duration_ms or 12_000
        seg = total // len(_SAMPLES)
        lines = []
        for i, (zh, vi) in enumerate(_SAMPLES):
            time.sleep(0.15)
            progress(int((i + 1) / len(_SAMPLES) * 100), "Đang tạo sub…")
            lines.append(SubtitleLine(i * seg, (i + 1) * seg - 150, text=vi, original=zh))
        return lines

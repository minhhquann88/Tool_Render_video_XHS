"""Luồng VideoSubFinder -> RapidOCR.

1. VideoSubFinderWXW.exe (C++, CPU) quét video, lọc ra mỗi câu sub một ảnh đại diện + start/end.
2. RapidOCR chạy trên vài chục ảnh đó: lấy chữ (xuất .srt) và box chữ (vùng làm mờ theo thời gian).

Một lần chạy phục vụ cả nút "Tự động tìm sub" lẫn "Tạo sub" (kết quả cache theo video).
"""
from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from app.config import OUTPUT_DIR, VSF_WORK_DIR
from app.models import BlurRegion, SubtitleLine
from app.services.common import ProgressFn, no_progress
from app.services.subtitle.base import RegionDetector, SubtitleSource
from app.services.subtitle.geometry import Rect, iou, merge_same_line, pad, union
from app.services.subtitle.vsf import VsfImage, list_images, run_vsf
from app.utils.srt import to_srt


@dataclass
class _Frame:
    """Kết quả OCR của một ảnh VSF: các dòng chữ (toạ độ chuẩn hoá theo khung video gốc)."""
    start_ms: int
    end_ms: int
    lines: list[tuple[Rect, str]]


@dataclass
class VsfResult:
    regions: list[BlurRegion]
    lines: list[SubtitleLine]
    srt_path: Path | None = None
    static_texts: list[str] = field(default_factory=list)


class VsfRapidPipeline:
    def __init__(self, top: float = 0.75, bottom: float = 0.03, min_score: float = 0.8,
                 static_ratio: float = 0.8, pad_ratio: float = 0.3, join_gap_ms: int = 300,
                 keep_work_dir: bool = False):
        self.top = top                    # dải VSF quét, tỉ lệ chiều cao tính từ đáy khung
        self.bottom = bottom
        self.min_score = min_score        # ngưỡng tin cậy của OCR
        self.static_ratio = static_ratio  # dòng có mặt ở >= tỉ lệ này số ảnh -> chữ cố định (cảnh báo, watermark…)
        self.pad_ratio = pad_ratio        # nới vùng mờ theo chiều cao chữ
        self.join_gap_ms = join_gap_ms    # 2 ảnh liền nhau cùng chữ cách nhau ít hơn mức này -> gộp
        self.keep_work_dir = keep_work_dir
        self._engine = None
        self._cache: dict[tuple[str, float], VsfResult] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def run(self, video_path: Path, progress: ProgressFn = no_progress) -> VsfResult:
        key = (str(video_path.resolve()), video_path.stat().st_mtime)
        with self._lock:  # bấm 2 nút liền nhau -> lần sau chờ rồi dùng cache, không quét lại
            if key not in self._cache:
                self._cache[key] = self._run(video_path, progress)
            return self._cache[key]

    # ------------------------------------------------------------------ các bước
    def _run(self, video_path: Path, progress: ProgressFn) -> VsfResult:
        width, height, duration_s = _video_info(video_path)
        work_dir = VSF_WORK_DIR / f"{video_path.stem}_{uuid.uuid4().hex[:6]}"
        try:
            rgb_dir = run_vsf(video_path, work_dir, duration_s, top=self.top, bottom=self.bottom,
                              progress=lambda pct, msg: progress(int(pct * 0.7), msg))
            images = list_images(rgb_dir)
            frames = self._ocr(images, width, height, progress)
        finally:
            if not self.keep_work_dir:
                shutil.rmtree(work_dir, ignore_errors=True)

        progress(97, "Đang gộp câu sub…")
        static, frames = self._split_static(frames)
        frames = self._join_frames(frames)
        regions = self._to_regions(static, frames, width, height)
        lines = [SubtitleLine(f.start_ms, f.end_ms, text=_text(f), original=_text(f)) for f in frames if f.lines]

        srt_path = None
        if lines:
            srt_path = OUTPUT_DIR / f"{video_path.stem}.srt"
            srt_path.write_text(to_srt(lines), encoding="utf-8")
        progress(100, "Xong")
        return VsfResult(regions, lines, srt_path, static_texts=[t for _, t in static])

    def _get_engine(self):
        if self._engine is None:
            from rapidocr import RapidOCR
            self._engine = RapidOCR(params={"Global.log_level": "error"})
        return self._engine

    def _ocr(self, images: list[VsfImage], width: int, height: int, progress: ProgressFn) -> list[_Frame]:
        if not images:
            return []
        progress(70, "Đang nạp mô hình OCR…")
        engine = self._get_engine()
        frames = []
        for i, im in enumerate(images, 1):
            res = engine(str(im.path), use_cls=False)
            # VSF ghi kích thước khung gốc vào tên file; ưu tiên số đó, dự phòng bằng kích thước đọc từ video
            fw, fh = im.frame_w or width, im.frame_h or height
            items = []
            if res.boxes is not None:
                for box, txt, score in zip(res.boxes, res.txts, res.scores):
                    if score < self.min_score or not txt.strip():
                        continue
                    x0, y0 = map(float, box.min(axis=0))
                    x1, y1 = map(float, box.max(axis=0))
                    rect = (max(0.0, (x0 + im.xmin) / fw), max(0.0, (y0 + im.ymin) / fh),
                            min(1.0, (x1 + im.xmin) / fw), min(1.0, (y1 + im.ymin) / fh))
                    if (rect[3] - rect[1]) < 0.012:  # chữ quá nhỏ, thường là nhiễu
                        continue
                    items.append((rect, txt.strip()))
            lines = sorted(merge_same_line(items, fw, fh), key=lambda it: it[0][1])
            frames.append(_Frame(im.start_ms, im.end_ms, lines))
            progress(70 + int(i / len(images) * 27), f"OCR {i}/{len(images)} câu sub…")
        return frames

    def _split_static(self, frames: list[_Frame]) -> tuple[list[tuple[Rect, str]], list[_Frame]]:
        """Tách chữ cố định (xuất hiện ở hầu hết các ảnh, cùng chỗ, cùng nội dung) khỏi sub."""
        groups: list[tuple[Rect, str, int]] = []  # rect gộp, chữ đại diện, số ảnh có mặt
        for f in frames:
            for rect, txt in f.lines:
                for i, (g_rect, g_txt, n) in enumerate(groups):
                    if iou(g_rect, rect) >= 0.5 and _similar(g_txt, txt):
                        groups[i] = (union(g_rect, rect), g_txt, n + 1)
                        break
                else:
                    groups.append((rect, txt, 1))
        need = max(3, self.static_ratio * len(frames))
        static = [(rect, txt) for rect, txt, n in groups if n >= need]
        if not static:
            return [], frames

        def is_static(rect: Rect, txt: str) -> bool:
            return any(iou(s_rect, rect) >= 0.5 and _similar(s_txt, txt) for s_rect, s_txt in static)

        kept = [_Frame(f.start_ms, f.end_ms, [(r, t) for r, t in f.lines if not is_static(r, t)]) for f in frames]
        return static, kept

    def _join_frames(self, frames: list[_Frame]) -> list[_Frame]:
        """VSF đôi khi tách một câu thành 2 ảnh liền nhau -> gộp lại."""
        out: list[_Frame] = []
        for f in frames:
            if not f.lines:
                continue
            prev = out[-1] if out else None
            if prev and f.start_ms - prev.end_ms <= self.join_gap_ms and _similar(_text(prev), _text(f)):
                prev.end_ms = max(prev.end_ms, f.end_ms)
                if len(prev.lines) == len(f.lines):
                    prev.lines = [(union(a[0], b[0]), a[1]) for a, b in zip(prev.lines, f.lines)]
                continue
            out.append(_Frame(f.start_ms, f.end_ms, list(f.lines)))
        return out

    def _to_regions(self, static: list[tuple[Rect, str]], frames: list[_Frame],
                    width: int, height: int) -> list[BlurRegion]:
        regions = []
        for rect, _ in static:
            x0, y0, x1, y1 = pad(rect, self.pad_ratio, width, height)
            regions.append(BlurRegion(x=x0, y=y0, w=x1 - x0, h=y1 - y0, start_ms=0, end_ms=None))
        for f in frames:
            for rect, _ in f.lines:
                x0, y0, x1, y1 = pad(rect, self.pad_ratio, width, height)
                regions.append(BlurRegion(x=x0, y=y0, w=x1 - x0, h=y1 - y0, start_ms=f.start_ms, end_ms=f.end_ms))
        regions.sort(key=lambda r: (r.start_ms, r.y))
        return regions


def _text(frame: _Frame) -> str:
    return "\n".join(txt for _, txt in frame.lines)


def _similar(a: str, b: str) -> bool:
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.8


def _video_info(video_path: Path) -> tuple[int, int, float]:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Không mở được video: {video_path}")
    try:
        width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        duration_s = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    finally:
        cap.release()
    return width, height, duration_s


class VsfRegionDetector(RegionDetector):
    id = "vsf"
    name = "VideoSubFinder + RapidOCR (nhanh)"

    def __init__(self, pipeline: VsfRapidPipeline):
        self.pipeline = pipeline

    def detect(self, video_path: Path, progress: ProgressFn = no_progress) -> list[BlurRegion]:
        return list(self.pipeline.run(video_path, progress).regions)


class VsfOcrSource(SubtitleSource):
    id = "vsf_ocr"
    name = "OCR sub gốc (VideoSubFinder + RapidOCR)"

    def __init__(self, pipeline: VsfRapidPipeline):
        self.pipeline = pipeline

    def generate(self, video_path: Path, regions: list[BlurRegion], duration_ms: int,
                 progress: ProgressFn = no_progress) -> list[SubtitleLine]:
        result = self.pipeline.run(video_path, progress)
        # bản sao: người dùng sửa bảng sub không làm hỏng cache
        return [SubtitleLine(l.start_ms, l.end_ms, text=l.text, original=l.original) for l in result.lines]

"""Tìm vùng sub gốc bằng RapidOCR (DBNet + CRNN, ONNX, chạy CPU).

Ý tưởng lấy từ RapidVideOCR: OCR khung hình -> gộp các box cùng dòng (so sánh toạ độ y) ->
gộp theo thời gian. Khác RapidVideOCR (phải có VideoSubFinder.exe), ở đây lấy mẫu khung hình
bằng OpenCV, theo dõi từng "dòng chữ" qua các khung để ra vùng + khoảng thời gian chính xác.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.models import BlurRegion
from app.services.common import ProgressFn, no_progress
from app.services.subtitle.base import RegionDetector
from app.services.subtitle.geometry import Rect, iou, merge_same_line, pad, union


@dataclass
class _Track:
    rect: Rect
    first: int
    last: int
    hits: int = 1
    texts: list[str] = field(default_factory=list)


class RapidOcrRegionDetector(RegionDetector):
    id = "rapidocr"
    name = "RapidOCR (tự động, theo thời gian)"

    def __init__(self, sample_fps: float = 4.0, min_score: float = 0.5, max_gap_s: float = 1.0,
                 min_duration_s: float = 0.4, static_ratio: float = 0.8, include_static: bool = True,
                 pad_ratio: float = 0.3, max_area: float = 0.4):
        self.sample_fps = sample_fps          # số khung lấy mẫu mỗi giây
        self.min_score = min_score            # ngưỡng tin cậy của OCR
        self.max_gap_s = max_gap_s            # chữ biến mất ngắn hơn mức này vẫn coi là cùng dòng
        self.min_duration_s = min_duration_s  # ngắn hơn -> coi là nhiễu
        self.static_ratio = static_ratio      # tồn tại >= tỉ lệ này của video -> chữ cố định (watermark…)
        self.include_static = include_static
        self.pad_ratio = pad_ratio            # nới vùng theo chiều cao chữ, tránh sót viền chữ
        self.max_area = max_area              # vùng lớn hơn tỉ lệ diện tích khung này bị loại
        self._engine = None

    # ------------------------------------------------------------------ public
    def detect(self, video_path: Path, progress: ProgressFn = no_progress) -> list[BlurRegion]:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Không mở được video: {video_path}")
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            step = max(1, round(fps / self.sample_fps))
            interval_ms = step / fps * 1000
            n_samples = max(1, (total + step - 1) // step)

            progress(0, "Đang nạp mô hình OCR…")
            engine = self._get_engine()
            gap = max(1, round(self.max_gap_s * fps / step))

            tracks: list[_Track] = []
            open_tracks: list[_Track] = []
            frame_idx = sample_idx = 0
            while True:
                if frame_idx % step:
                    if not cap.grab():
                        break
                    frame_idx += 1
                    continue
                ok, frame = cap.read()
                if not ok:
                    break
                lines = self._detect_lines(engine, frame)
                open_tracks = self._update_tracks(open_tracks, tracks, lines, sample_idx, gap)
                sample_idx += 1
                frame_idx += 1
                progress(int(sample_idx / n_samples * 95), "Đang quét khung hình tìm sub…")
            tracks.extend(open_tracks)
        finally:
            cap.release()

        progress(97, "Đang gộp vùng sub…")
        return self._to_regions(tracks, sample_idx, interval_ms, width, height)

    # ------------------------------------------------------------------ OCR
    def _get_engine(self):
        if self._engine is None:
            from rapidocr import RapidOCR
            # chỉ cần vị trí chữ: det ở 480px đủ cho sub lớn và nhanh hơn ~5-10 lần so với mặc định 736
            self._engine = RapidOCR(params={"Global.log_level": "error", "Det.limit_side_len": 480,
                                            "Det.limit_type": "max"})
        return self._engine

    def _detect_lines(self, engine, frame) -> list[tuple[Rect, str]]:
        h, w = frame.shape[:2]
        res = engine(frame, use_det=True, use_cls=False, use_rec=False)
        if res.boxes is None:
            return []
        items = []
        for box, score in zip(res.boxes, res.scores):
            txt = ""
            if score < self.min_score:
                continue
            x0, y0 = box.min(axis=0)
            x1, y1 = box.max(axis=0)
            rect = (max(0.0, x0 / w), max(0.0, y0 / h), min(1.0, x1 / w), min(1.0, y1 / h))
            bw, bh = (rect[2] - rect[0]) * w, (rect[3] - rect[1]) * h
            if bh < h * 0.012 or bw < bh * 0.8:  # quá nhỏ hoặc dọc
                continue
            items.append((rect, txt))
        return merge_same_line(items, w, h)

    # ------------------------------------------------------------------ theo dõi
    @staticmethod
    def _update_tracks(open_tracks: list[_Track], done: list[_Track],
                       lines: list[tuple[Rect, str]], idx: int, gap: int) -> list[_Track]:
        used: set[int] = set()
        for rect, txt in lines:
            best = None
            for t in open_tracks:
                if id(t) in used:
                    continue
                if iou(t.rect, rect) >= 0.35:
                    best = t
                    break
            if best is None:
                open_tracks.append(_Track(rect, idx, idx, texts=[txt]))
            else:
                used.add(id(best))
                best.rect = union(best.rect, rect)
                best.last = idx
                best.hits += 1
                if txt not in best.texts:
                    best.texts.append(txt)

        still_open = []
        for t in open_tracks:
            (still_open if idx - t.last <= gap else done).append(t)
        return still_open

    @staticmethod
    def _merge_tracks(tracks: list[_Track], gap: int) -> list[_Track]:
        """Gộp track cùng vị trí (IoU cao) mà thời gian chồng/sát nhau — vd. dòng cố định bị đứt đoạn."""
        tracks = sorted(tracks, key=lambda t: t.first)
        changed = True
        while changed:
            changed = False
            for i, a in enumerate(tracks):
                for b in tracks[i + 1:]:
                    if b.first - a.last <= gap and iou(a.rect, b.rect) >= 0.5:
                        a.rect = union(a.rect, b.rect)
                        a.first, a.last = min(a.first, b.first), max(a.last, b.last)
                        a.hits += b.hits
                        tracks.remove(b)
                        changed = True
                        break
                if changed:
                    break
        return tracks

    # ------------------------------------------------------------------ kết quả
    def _to_regions(self, tracks: list[_Track], n_samples: int, interval_ms: float,
                    width: float, height: float) -> list[BlurRegion]:
        min_hits = max(2, round(self.min_duration_s * self.sample_fps))
        gap = max(1, round(self.max_gap_s * self.sample_fps))
        tracks = self._merge_tracks(tracks, gap)
        regions = []
        for t in tracks:
            if t.hits < min_hits:
                continue
            if (t.rect[2] - t.rect[0]) * (t.rect[3] - t.rect[1]) > self.max_area:  # khung outro, không phải sub
                continue
            is_static = (t.last - t.first + 1) >= self.static_ratio * n_samples
            if is_static and not self.include_static:
                continue

            x0, y0, x1, y1 = pad(t.rect, self.pad_ratio, width, height)

            if is_static:
                start_ms, end_ms = 0, None
            else:
                start_ms = max(0, int(t.first * interval_ms - interval_ms))
                end_ms = int((t.last + 1) * interval_ms + interval_ms)
            regions.append(BlurRegion(x=x0, y=y0, w=x1 - x0, h=y1 - y0, start_ms=start_ms, end_ms=end_ms))
        regions.sort(key=lambda r: (r.start_ms, r.y))
        return regions

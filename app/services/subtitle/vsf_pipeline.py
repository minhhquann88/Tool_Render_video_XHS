"""Luồng VideoSubFinder -> RapidOCR.

1. VideoSubFinderWXW.exe (C++, CPU) quét video, lọc ra mỗi câu sub một ảnh đại diện + start/end.
2. RapidOCR chạy trên vài chục ảnh đó: lấy chữ (xuất .srt) và box chữ (vùng làm mờ theo thời gian).

Một lần chạy phục vụ cả nút "Tự động tìm sub" lẫn "Tạo sub" (kết quả cache theo video).
"""
from __future__ import annotations

import math
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
from app.services.subtitle.geometry import Rect, iou, merge_same_line, pad, union, v_overlap
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
                 static_ratio: float = 0.8, pad_ratio: float = 0.3, join_gap_ms: int = 300, same_text_gap_ms: int = 1500,
                 max_line_h: float = 0.08, max_off_center: float = 0.12, keep_work_dir: bool = False):
        self.top = top                    # dải VSF quét, tỉ lệ chiều cao tính từ đáy khung
        self.bottom = bottom
        self.min_score = min_score        # ngưỡng tin cậy của OCR
        self.static_ratio = static_ratio  # dòng có mặt ở >= tỉ lệ này số ảnh -> chữ cố định (cảnh báo, watermark…)
        self.pad_ratio = pad_ratio        # nới vùng mờ theo chiều cao chữ
        self.join_gap_ms = join_gap_ms    # 2 ảnh liền nhau cùng chữ cách nhau ít hơn mức này -> gộp
        self.same_text_gap_ms = same_text_gap_ms  # chữ giống hệt (sub nháy mất rồi hiện lại) -> gộp dù cách xa hơn
        # 1 dòng sub cao ~2-5% khung; box cao hơn mức này là OCR nhận nhầm hình (vd. cái bát thành chữ "9")
        self.max_line_h = max_line_h
        # sub luôn căn giữa; dòng ngắn lệch hẳn sang bên là chữ trên đồ vật (bao bì, biển hiệu), không phải sub
        self.max_off_center = max_off_center
        self.keep_work_dir = keep_work_dir
        self._engine = None
        self._strip_engine = None
        self._cache: dict[tuple[str, float], VsfResult] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def run(self, video_path: Path, progress: ProgressFn = no_progress) -> VsfResult:
        key = (str(video_path.resolve()), video_path.stat().st_mtime)
        with self._lock:  # bấm 2 nút liền nhau -> lần sau chờ rồi dùng cache, không quét lại
            if key not in self._cache:
                self._cache[key] = self._run(video_path, progress)
            return self._cache[key]

    def forget(self, video_path: Path) -> None:
        with self._lock:
            path = str(video_path.resolve())
            for key in [k for k in self._cache if k[0] == path]:
                del self._cache[key]

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
        # sub mới để trống: người dùng gõ / nhập vào, tránh chèn lại chữ gốc lên vùng vừa che
        lines = [SubtitleLine(f.start_ms, f.end_ms, text="", original=_text(f)) for f in frames if f.lines]

        srt_path = None
        if lines:  # file .srt của sub gốc
            srt_path = OUTPUT_DIR / f"{video_path.stem}.srt"
            srt_path.write_text(to_srt([SubtitleLine(l.start_ms, l.end_ms, text=l.original) for l in lines]),
                                encoding="utf-8")
        progress(100, "Xong")
        return VsfResult(regions, lines, srt_path, static_texts=[t for _, t in static])

    def _get_engine(self):
        if self._engine is None:
            from rapidocr import RapidOCR
            self._engine = RapidOCR(params={"Global.log_level": "error"})
        return self._engine

    def _get_strip_engine(self):
        """Bộ tìm chữ cho dải hẹp: không phóng ảnh (mặc định phóng cạnh ngắn lên 736px -> dải 83px bị phóng ~9 lần,
        mỗi dải mất ~1s). Chỉ dùng để tìm vị trí; nhận dạng chữ vẫn qua bộ chính."""
        if self._strip_engine is None:
            from rapidocr import RapidOCR
            self._strip_engine = RapidOCR(params={"Global.log_level": "error", "Det.limit_type": "max",
                                                  "Det.limit_side_len": 960})
        return self._strip_engine

    def _ocr(self, images: list[VsfImage], width: int, height: int, progress: ProgressFn) -> list[_Frame]:
        if not images:
            return []
        progress(70, "Đang nạp mô hình OCR…")
        engine = self._get_engine()
        frames = []
        for i, im in enumerate(images, 1):
            # VSF ghi kích thước khung gốc vào tên file; ưu tiên số đó, dự phòng bằng kích thước đọc từ video
            fw, fh = im.frame_w or width, im.frame_h or height
            items, noisy_rows = self._read(engine, str(im.path), im.xmin, im.ymin, fw, fh)
            if noisy_rows:
                # có chữ nghiêng / box quá to (bao bì, biển hiệu): OCR dễ gộp luôn câu sub nằm chồng lên thành 1 box
                # nghiêng rồi đọc sai -> đọc lại theo dải ngang ở đoạn đó, câu sub nằm ngang sẽ tách ra được
                items += self._read_strips(engine, im, fw, fh, noisy_rows)
            items = _dedupe(items)
            lines = sorted((it for it in merge_same_line(items, fw, fh) if self._is_sub_line(it[0])),
                           key=lambda it: it[0][1])
            frames.append(_Frame(im.start_ms, im.end_ms, lines))
            progress(70 + int(i / len(images) * 27), f"OCR {i}/{len(images)} câu sub…")
        return frames

    def _read(self, engine, image, dx: float, dy: float, fw: float, fh: float
              ) -> tuple[list[tuple[Rect, str, float]], tuple[float, float] | None]:
        """OCR cả ảnh -> (các dòng nằm ngang hợp lệ, đoạn chiều cao (px trong ảnh) có box nghiêng / quá cao)."""
        # ghi rõ cả 3 cờ: RapidOCR giữ cờ của lần gọi trước (lần nhận dạng riêng ở _read_strips tắt use_det)
        res = engine(image, use_det=True, use_cls=False, use_rec=True)
        items, rows = [], None
        if res.boxes is None:
            return items, rows
        for box, txt, score in zip(res.boxes, res.txts, res.scores):
            x0, y0 = map(float, box.min(axis=0))
            x1, y1 = map(float, box.max(axis=0))
            if _tilt(box) > _MAX_TILT or (y1 - y0) / fh > self.max_line_h:  # sub luôn nằm ngang, 1 dòng không cao vậy
                rows = (min(rows[0], y0), max(rows[1], y1)) if rows else (y0, y1)
                continue
            if score < self.min_score or not txt.strip():
                continue
            rect = (max(0.0, (x0 + dx) / fw), max(0.0, (y0 + dy) / fh),
                    min(1.0, (x1 + dx) / fw), min(1.0, (y1 + dy) / fh))
            if (rect[3] - rect[1]) < 0.012:  # chữ quá nhỏ, thường là nhiễu
                continue
            items.append((rect, txt.strip(), float(score)))
        return items, rows

    def _read_strips(self, engine, im: VsfImage, fw: float, fh: float,
                     rows: tuple[float, float]) -> list[tuple[Rect, str, float]]:
        """Cắt đoạn có chữ nghiêng thành dải ngang hẹp chồng nửa nhau; mỗi dải chỉ tìm vị trí chữ, rồi chỉ nhận dạng
        khung nằm ngang, trọn trong dải, có dáng sub (mẩu chữ nghiêng bị bỏ trước khi nhận dạng -> nhanh)."""
        import cv2
        import numpy as np

        img = cv2.imdecode(np.fromfile(str(im.path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        h = img.shape[0]
        # dải hẹp (~2 lần 1 dòng sub thường) để chữ nghiêng xung quanh bị cắt vụn, không gộp được với câu sub
        strip = max(40, int(fh * _STRIP_RATIO))
        det = self._get_strip_engine()
        out = []
        first = max(0, int(rows[0]) - strip // 2)
        last = min(h, int(rows[1]) + strip // 2)
        for top in range(first, max(first + 1, last - strip // 2), strip // 2):
            part = img[top:top + strip]
            res = det(part, use_det=True, use_cls=False, use_rec=False)
            if res.boxes is None:
                continue
            for box in res.boxes:
                x0, y0 = map(float, box.min(axis=0))
                x1, y1 = map(float, box.max(axis=0))
                if _tilt(box) > _MAX_TILT or y0 <= 2 or y1 >= part.shape[0] - 2:  # nghiêng / bị cắt dở ở mép dải
                    continue
                rect = ((x0 + im.xmin) / fw, (y0 + im.ymin + top) / fh,
                        (x1 + im.xmin) / fw, (y1 + im.ymin + top) / fh)
                if (rect[3] - rect[1]) < 0.012 or not self._is_sub_line(rect):
                    continue
                crop = part[max(0, int(y0) - 2):int(y1) + 3, max(0, int(x0) - 2):int(x1) + 3]
                rec = engine(crop, use_det=False, use_cls=False, use_rec=True)
                txt, score = (rec.txts[0], float(rec.scores[0])) if rec.txts else ("", 0.0)
                if score >= self.min_score and txt.strip():
                    out.append((rect, txt.strip(), score))
        return out

    def _is_sub_line(self, rect: Rect) -> bool:
        x0, y0, x1, y1 = rect
        if y1 - y0 > self.max_line_h:
            return False
        centered = abs((x0 + x1) / 2 - 0.5) <= self.max_off_center
        return centered or x1 - x0 >= 0.5  # dòng dài gần hết bề ngang: vẫn giữ dù lệch tâm

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
        """VSF đôi khi tách một câu thành 2 ảnh liền nhau -> gộp lại (nếu không, câu bị dịch + đọc 2 lần)."""
        out: list[_Frame] = []
        for f in frames:
            if not f.lines:
                continue
            prev = out[-1] if out else None
            gap = f.start_ms - prev.end_ms if prev else 0
            same = prev and _text(prev).strip() == _text(f).strip()
            if prev and ((gap <= self.join_gap_ms and _similar(_text(prev), _text(f)))
                         or (same and gap <= self.same_text_gap_ms)):
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
            for rect, txt in f.lines:
                x0, y0, x1, y1 = pad(rect, self.pad_ratio, width, height)
                regions.append(BlurRegion(x=x0, y=y0, w=x1 - x0, h=y1 - y0, start_ms=f.start_ms, end_ms=f.end_ms,
                                          text=txt))
        regions.sort(key=lambda r: (r.start_ms, r.y))
        return regions


_STRIP_RATIO = 0.065  # chiều cao dải đọc lại, tỉ lệ khung (720x1280: 83px)
_MAX_TILT = 6  # độ; box chữ nghiêng hơn mức này là chữ trên đồ vật, không phải sub


def _tilt(box) -> float:
    """Độ nghiêng (độ) của cạnh trên box chữ."""
    return abs(math.degrees(math.atan2(box[1][1] - box[0][1], box[1][0] - box[0][0])))


def _dedupe(items: list[tuple[Rect, str, float]]) -> list[tuple[Rect, str]]:
    """Gộp các lần đọc trùng 1 dòng (ảnh đầy đủ + các dải chồng nhau): giữ bản tin cậy nhất."""
    out: list[tuple[Rect, str, float]] = []
    for rect, txt, score in sorted(items, key=lambda it: -it[2]):
        if any(iou(rect, r) > 0.3 or (v_overlap(rect, r) > 0.6 and _similar(txt, t)) for r, t, _ in out):
            continue
        out.append((rect, txt, score))
    return [(r, t) for r, t, _ in out]


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

    def forget(self, video_path: Path) -> None:
        self.pipeline.forget(video_path)


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

"""Chạy VideoSubFinderWXW.exe (CLI, CPU) để lọc ra các khung đại diện cho từng câu sub.

Mỗi ảnh trong RGBImages ứng với một câu sub, tên file mang sẵn thời gian và vị trí ảnh cắt:
    0_00_01_234__0_00_03_456_<ln:1><xmin:4><ymin:4><w:4><h:4><W:4><H:4>.jpeg
(xem FormatImInfoAddData trong VideoSubFinder/Components/IPAlgorithms/IPAlgorithms.cpp).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import VSF_EXE
from app.services.common import ProgressFn, no_progress

_NAME = re.compile(r"^(\d+)_(\d+)_(\d+)_(\d+)__(\d+)_(\d+)_(\d+)_(\d+)_\d(\d{4})(\d{4})(\d{4})(\d{4})(\d{4})(\d{4})")
_IMAGE_EXTS = {".jpeg", ".jpg", ".png", ".bmp"}


@dataclass
class VsfImage:
    path: Path
    start_ms: int
    end_ms: int
    xmin: int  # vị trí ảnh cắt trong khung video gốc (px)
    ymin: int
    frame_w: int  # kích thước khung video gốc (px)
    frame_h: int


def parse_image_name(path: Path) -> VsfImage | None:
    m = _NAME.match(path.stem)
    if not m:
        return None
    g = [int(v) for v in m.groups()]
    to_ms = lambda h, mi, s, ms: ((h * 60 + mi) * 60 + s) * 1000 + ms
    return VsfImage(path, to_ms(*g[0:4]), to_ms(*g[4:8]), xmin=g[8], ymin=g[9], frame_w=g[12], frame_h=g[13])


def list_images(rgb_dir: Path) -> list[VsfImage]:
    images = [parse_image_name(p) for p in rgb_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS]
    return sorted((im for im in images if im), key=lambda im: im.start_ms)


def run_vsf(video_path: Path, out_dir: Path, duration_s: float, top: float = 0.75, bottom: float = 0.03,
            threads: int | None = None, timeout_s: float | None = None,
            progress: ProgressFn = no_progress) -> Path:
    """Quét video, trả về thư mục RGBImages. `top`/`bottom` là tỉ lệ chiều cao tính từ đáy khung.

    progress chạy 0..100 theo ước lượng thời gian (CLI không in tiến độ).
    """
    if not VSF_EXE.exists():
        raise NotImplementedError(f"chưa có VideoSubFinder ({VSF_EXE})")
    threads = threads or min(8, os.cpu_count() or 4)
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)

    cmd = [str(VSF_EXE), "-c", "-r", "-ovffmpeg", "-te", str(top), "-be", str(bottom),
           "-le", "0", "-re", "1", "-nthr", str(threads),
           "-i", str(video_path.resolve()), "-o", str(out_dir.resolve())]  # exe chạy với cwd riêng
    proc = subprocess.Popen(cmd, cwd=VSF_EXE.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    rgb_dir = out_dir / "RGBImages"
    expected_s = max(5.0, duration_s * 0.9)  # đo thực tế: ~0.6-0.8x độ dài video với 720p, 8 luồng
    timeout_s = timeout_s or max(300.0, duration_s * 10)
    started = time.monotonic()
    try:
        while proc.poll() is None:
            elapsed = time.monotonic() - started
            if elapsed > timeout_s:
                raise RuntimeError(f"VideoSubFinder chạy quá {int(timeout_s)}s")
            found = len(list(rgb_dir.iterdir())) if rgb_dir.exists() else 0
            progress(min(99, int(elapsed / expected_s * 100)), f"VideoSubFinder đang quét video ({found} câu)…")
            time.sleep(0.5)
    finally:
        if proc.poll() is None:
            proc.kill()
    if not rgb_dir.exists():
        raise RuntimeError(f"VideoSubFinder không tạo được kết quả (mã thoát {proc.returncode})")
    progress(100, "VideoSubFinder xong")
    return rgb_dir

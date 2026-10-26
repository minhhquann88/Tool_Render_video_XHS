"""Hàm hình học cho box chữ, toạ độ chuẩn hoá 0..1 theo khung video."""
from __future__ import annotations

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 chuẩn hoá 0..1


def v_overlap(a: Rect, b: Rect) -> float:
    """Tỉ lệ chồng lấn theo chiều dọc so với box thấp hơn."""
    inter = min(a[3], b[3]) - max(a[1], b[1])
    return inter / max(1e-6, min(a[3] - a[1], b[3] - b[1]))


def iou(a: Rect, b: Rect) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / (area(a) + area(b) - inter)


def union(a: Rect, b: Rect) -> Rect:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def merge_same_line(items: list[tuple[Rect, str]], w: float, h: float) -> list[tuple[Rect, str]]:
    """Gộp các box cùng dòng (y chồng lấn, khoảng hở ngang nhỏ) thành một dòng sub."""
    items = sorted(items, key=lambda it: it[0][0])
    merged: list[tuple[Rect, str]] = []
    for rect, txt in items:
        for i, (m, mt) in enumerate(merged):
            line_h = min(m[3] - m[1], rect[3] - rect[1]) * h
            gap_px = (rect[0] - m[2]) * w
            if v_overlap(m, rect) > 0.6 and gap_px < line_h * 1.5:
                merged[i] = (union(m, rect), f"{mt} {txt}".strip())
                break
        else:
            merged.append((rect, txt))
    return merged


def pad(rect: Rect, ratio: float, width: float, height: float) -> Rect:
    """Nới box theo tỉ lệ chiều cao chữ, tránh sót viền chữ."""
    x0, y0, x1, y1 = rect
    pad_px = ratio * (y1 - y0) * height
    px, py = pad_px / width, pad_px / height
    return max(0.0, x0 - px), max(0.0, y0 - py), min(1.0, x1 + px), min(1.0, y1 + py)

"""Quy trình theo mục tiêu: mỗi mục tiêu là một dãy bước; trạng thái từng bước tính từ dữ liệu của video."""
from __future__ import annotations

from dataclasses import dataclass

from app.models import VideoProject

DETECT, TRANSLATE, VOICE, EXPORT = "detect", "translate", "voice", "export"
STEPS = (DETECT, TRANSLATE, VOICE, EXPORT)

GOALS = [  # (id, tên, mô tả)
    ("blur", "Chỉ che sub", "Xoá sub gốc, giữ nguyên tiếng gốc"),
    ("subs", "Thêm sub Việt", "Che sub gốc, chèn sub tiếng Việt"),
    ("dub", "Việt hoá trọn gói", "Sub tiếng Việt và giọng đọc AI"),
]
ORDER = {
    "blur": [DETECT, EXPORT],
    "subs": [DETECT, TRANSLATE, EXPORT],
    "dub": [DETECT, TRANSLATE, VOICE, EXPORT],
}
TITLES = {DETECT: "Tìm & che sub gốc", TRANSLATE: "Dịch sub", VOICE: "Lồng tiếng AI", EXPORT: "Xuất video"}
SHORT = {DETECT: "Che sub", TRANSLATE: "Dịch sub", VOICE: "Lồng tiếng", EXPORT: "Xuất video"}
OUTPUT_SUFFIX = {"blur": "_che-sub", "subs": "_sub", "dub": ""}


@dataclass
class StepInfo:
    done: bool
    status: str
    tone: str = ""  # "" | ok | warn | run | error


def stale_voice_count(project: VideoProject | None) -> int:
    """Số câu có sub mới nhưng chưa có giọng, tính khi video đã từng tạo giọng (tức là câu sửa/thêm sau đó)."""
    lines = project.subtitles if project else []
    if not any(l.audio_path for l in lines):
        return 0
    return sum(1 for l in lines if l.text.strip() and not l.audio_path)


def step_info(project: VideoProject, key: str, has_key: bool) -> StepInfo:
    lines = project.subtitles
    if project.waiting_step == key:
        return StepInfo(False, "Đang chờ video khác làm xong…", "run")
    if project.busy_step == key:
        pct, _ = project.step_progress
        return StepInfo(False, f"Đang chạy… {pct}%", "run")
    if key in project.step_errors:
        return StepInfo(False, f"Lỗi: {project.step_errors[key]}", "error")

    if key == DETECT:
        timed = sum(1 for r in project.regions if r.end_ms is not None)
        fixed = len(project.regions) - timed
        if not project.regions:
            return StepInfo(False, "Chưa làm")
        parts = [f"{timed} câu sub đã che"] if timed else []
        if fixed:
            parts.append(f"{fixed} vùng cố định")
        return StepInfo(True, " · ".join(parts), "ok")

    if key == TRANSLATE:
        n_orig = sum(1 for l in lines if l.original.strip())
        n_text = sum(1 for l in lines if l.text.strip())
        if n_text:
            return StepInfo(True, f"{n_text}/{max(n_orig, n_text)} câu đã có sub mới", "ok")
        if not lines:
            return StepInfo(False, "Cần tìm sub trước")
        if not has_key:
            return StepInfo(False, "Cần Gemini API key", "warn")
        return StepInfo(False, "Chưa làm")

    if key == VOICE:
        n_voices = sum(1 for l in lines if l.audio_path)
        n_stale = stale_voice_count(project)
        if n_stale:
            return StepInfo(False, f"{n_stale} câu đã sửa, cần tạo lại giọng", "warn")
        if n_voices:
            return StepInfo(True, f"{n_voices} câu đã có giọng", "ok")
        if not any(l.text.strip() for l in lines):
            return StepInfo(False, "Cần sub mới trước")
        return StepInfo(False, "Chưa làm")

    # EXPORT
    if project.output_path and project.exported_rev == project.rev:
        return StepInfo(True, f"Đã xuất {project.output_path.name}", "ok")
    if project.output_path:
        return StepInfo(False, "Có thay đổi sau lần xuất trước", "warn")
    return StepInfo(False, "Chưa xuất")


def pending_steps(project: VideoProject, has_key: bool) -> list[str]:
    return [k for k in ORDER[project.goal] if not step_info(project, k, has_key).done]


def progress_text(project: VideoProject, has_key: bool) -> tuple[str, str]:
    """Dòng trạng thái ngắn cho danh sách video: (chữ, màu)."""
    if project.busy_step:
        return f"{SHORT[project.busy_step]} · {project.step_progress[0]}%", "#f5a524"
    if project.waiting_step:
        return f"Chờ {SHORT[project.waiting_step].lower()}…", "#f5a524"
    if project.status.busy or not project.local_path:  # đang tải / chưa tải / lỗi tải
        text = project.status.label
        if project.status.busy:
            text += f" · {project.progress}%"
        return text, project.status.color
    steps = ORDER[project.goal]
    done = len(steps) - len(pending_steps(project, has_key))
    if done == len(steps):
        return "Hoàn tất · đã xuất", "#3ecf8e"
    if any(k in project.step_errors for k in steps):
        return f"Lỗi · {done}/{len(steps)} bước xong", "#ff5c5c"
    return (f"{done}/{len(steps)} bước xong" if done else "Đã tải · chưa xử lý"), "#9aa0a9"

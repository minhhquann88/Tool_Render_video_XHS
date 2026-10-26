"""Render thật bằng FFmpeg (bản kèm imageio-ffmpeg: libx264 + libass).

- Làm mờ: mỗi BlurRegion = crop -> gblur -> overlay lại đúng chỗ, chỉ bật trong [start, end].
- Sub mới: file ASS, mỗi dòng đặt giữa vùng mờ của câu sub đang chạy (không có vùng thì đặt dưới khung).
- Giọng đọc: mỗi đoạn audio adelay tới mốc của dòng, amix với tiếng gốc đã giảm âm lượng.
Mỗi phần bật/tắt độc lập theo ExportSettings -> chỉ che sub rồi xuất cũng được.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.models import BlurRegion, SubStyle, SubtitleLine, VideoProject
from app.services.common import ProgressFn, no_progress
from app.services.render.base import RenderContext, Renderer

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_EDGE_MS = 80  # nới thời gian vùng mờ 2 đầu, tránh lộ sub ở khung chuyển


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
    except ImportError:
        raise NotImplementedError("chưa có FFmpeg (pip install imageio-ffmpeg)") from None
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(video: Path) -> tuple[int, int, float, bool]:
    """(width, height, duration_s, has_audio) đọc từ output của `ffmpeg -i`."""
    res = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(video)], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    info = res.stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    if not dur or not size:
        raise RuntimeError(f"Không đọc được thông tin video: {video.name}")
    h, m, s = dur.groups()
    return int(size.group(1)), int(size.group(2)), int(h) * 3600 + int(m) * 60 + float(s), "Audio:" in info


class FFmpegRenderer(Renderer):
    id = "ffmpeg"
    name = "FFmpeg (H.264)"

    def __init__(self, crf: int = 20, preset: str = "veryfast"):
        self.crf = crf
        self.preset = preset

    def render(self, project: VideoProject, ctx: RenderContext, out_path: Path,
               progress: ProgressFn = no_progress) -> Path:
        exp = ctx.export
        width, height, duration, has_audio = probe(project.local_path)
        regions = [r for r in project.regions if r.w > 0 and r.h > 0] if exp.apply_blur else []
        subs = [l for l in project.subtitles if l.text.strip()] if exp.burn_subs else []
        voices = [l for l in project.subtitles if l.audio_path and Path(l.audio_path).exists()] \
            if exp.add_voice else []
        if not (regions or subs or voices) and exp.resolution == "original":
            raise ValueError("Không có gì để xử lý: chưa có vùng mờ / sub mới / giọng đọc nào được chọn")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="render_"))
        try:
            graph, v_out = self._video_graph(regions, subs, project.regions, ctx.style, width, height,
                                             exp.resolution, work)
            inputs = ["-i", str(project.local_path)]
            for line in voices:
                inputs += ["-i", str(line.audio_path)]
            a_graph, a_map, a_codec = self._audio_graph(voices, has_audio, exp.keep_original_audio,
                                                        exp.original_volume)
            graph += a_graph
            (work / "graph.txt").write_text(";\n".join(graph), encoding="utf-8")

            cmd = [ffmpeg_exe(), "-hide_banner", "-y", "-nostats", "-progress", "pipe:1", *inputs,
                   "-filter_complex_script", "graph.txt", "-map", v_out, *a_map,
                   "-c:v", "libx264", "-preset", self.preset, "-crf", str(self.crf), "-pix_fmt", "yuv420p",
                   *a_codec, "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out_path.resolve())]
            steps = [s for s, on in (("làm mờ", regions), ("chèn sub", subs), ("ghép giọng", voices)) if on]
            self._run(cmd, work, duration, f"Đang render ({', '.join(steps) or 'mã hoá'})…", progress)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        progress(100, "Render xong")
        return out_path

    # ------------------------------------------------------------------ video
    def _video_graph(self, regions: list[BlurRegion], subs: list[SubtitleLine], all_regions: list[BlurRegion],
                     style: SubStyle, width: int, height: int, resolution: str, work: Path) -> tuple[list[str], str]:
        graph: list[str] = []
        cur = "0:v"
        if regions:
            n = len(regions)
            graph.append(f"[0:v]split={n + 1}[base]" + "".join(f"[s{i}]" for i in range(n)))
            cur = "base"
            for i, reg in enumerate(regions):
                x, y, w, h = _px_rect(reg, width, height)
                enable = _enable(reg)
                sigma = max(6, reg.strength)
                graph.append(f"[s{i}]crop={w}:{h}:{x}:{y},gblur=sigma={sigma}:steps=2{enable}[b{i}]")
                graph.append(f"[{cur}][b{i}]overlay={x}:{y}{enable}[o{i}]")
                cur = f"o{i}"
        if subs:
            (work / "subs.ass").write_text(_build_ass(subs, all_regions, style, width, height), encoding="utf-8")
            graph.append(f"[{cur}]ass=subs.ass[subbed]")  # chạy ffmpeg với cwd=work -> đường dẫn tương đối
            cur = "subbed"
        scale = _scale_filter(resolution, width, height)
        graph.append(f"[{cur}]{scale}[vout]" if scale else f"[{cur}]null[vout]")
        return graph, "[vout]"

    # ------------------------------------------------------------------ audio
    @staticmethod
    def _audio_graph(voices: list[SubtitleLine], has_audio: bool, keep_original: bool,
                     original_volume: int) -> tuple[list[str], list[str], list[str]]:
        aac = ["-c:a", "aac", "-b:a", "160k"]
        if not voices:
            if has_audio and keep_original:
                return [], ["-map", "0:a:0"], ["-c:a", "copy"]
            return [], [], ["-an"]
        graph, labels = [], []
        if has_audio and keep_original:
            graph.append(f"[0:a:0]volume={original_volume / 100:.2f}[orig]")
            labels.append("[orig]")
        for i, line in enumerate(voices, 1):
            graph.append(f"[{i}:a]aresample=44100,adelay={line.start_ms}:all=1[v{i}]")
            labels.append(f"[v{i}]")
        graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0"
                     f":dropout_transition=0[aout]")
        return graph, ["-map", "[aout]"], aac

    # ------------------------------------------------------------------ chạy
    @staticmethod
    def _run(cmd: list[str], cwd: Path, duration: float, msg: str, progress: ProgressFn) -> None:
        log_path = cwd / "ffmpeg.log"
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=log, text=True,
                                    encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
            for row in proc.stdout:
                if row.startswith("out_time_us=") and row[12:].strip().isdigit():
                    pct = int(row[12:]) / 1e6 / max(duration, 0.1) * 100
                    progress(min(99, int(pct)), msg)
            proc.wait()
        if proc.returncode != 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]
            raise RuntimeError("FFmpeg lỗi: " + " | ".join(tail))


def _px_rect(reg: BlurRegion, width: int, height: int) -> tuple[int, int, int, int]:
    even = lambda v: max(2, int(v) // 2 * 2)
    x = min(max(0, int(reg.x * width)), width - 2)
    y = min(max(0, int(reg.y * height)), height - 2)
    w = min(even(reg.w * width), (width - x) // 2 * 2)
    h = min(even(reg.h * height), (height - y) // 2 * 2)
    return x, y, w, h


def _enable(reg: BlurRegion) -> str:
    if reg.end_ms is None:
        return ""
    start = max(0, reg.start_ms - _EDGE_MS) / 1000
    end = (reg.end_ms + _EDGE_MS) / 1000
    return f":enable='between(t,{start:.3f},{end:.3f})'"


def _scale_filter(resolution: str, width: int, height: int) -> str:
    if resolution == "original" or not resolution.isdigit():
        return ""
    target = int(resolution)  # 1080/720 = cạnh ngắn, dùng được cho cả video dọc
    if min(width, height) <= target:
        return ""
    return f"scale={target}:-2" if width < height else f"scale=-2:{target}"


# ---------------------------------------------------------------------- ASS
def _ass_color(hex_color: str) -> str:
    c = hex_color.lstrip("#")
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ass_time(ms: int) -> str:
    cs = max(0, int(ms)) // 10
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _anchor(line: SubtitleLine, regions: list[BlurRegion], width: int, height: int) -> tuple[int, int] | None:
    """Tâm vùng mờ (theo thời gian) chồng nhiều nhất với dòng sub; vùng toàn video dùng khi không có vùng riêng."""
    best, best_overlap = None, 0
    for reg in regions:
        end = reg.end_ms if reg.end_ms is not None else line.end_ms
        overlap = min(end, line.end_ms) - max(reg.start_ms, line.start_ms)
        if reg.end_ms is None:
            overlap = overlap * 0.01  # chỉ là dự phòng
        if overlap > best_overlap:
            best, best_overlap = reg, overlap
    if best is None:
        return None
    return int((best.x + best.w / 2) * width), int((best.y + best.h / 2) * height)


def _build_ass(lines: list[SubtitleLine], regions: list[BlurRegion], style: SubStyle,
               width: int, height: int) -> str:
    bold = -1 if style.bold else 0
    outline = max(2, style.font_size // 16)
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style.font_family},{style.font_size},{_ass_color(style.color)},&H000000FF,"
        f"{_ass_color(style.outline_color)},&H00000000,{bold},0,0,0,100,100,0,0,1,{outline},0,"
        f"2,{width // 20},{width // 20},{height // 10},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for line in lines:
        text = line.text.strip().replace("{", "(").replace("}", ")").replace("\n", r"\N")
        pos = _anchor(line, regions, width, height)
        tag = f"{{\\an5\\pos({pos[0]},{pos[1]})}}" if pos else ""
        events.append(f"Dialogue: 0,{_ass_time(line.start_ms)},{_ass_time(line.end_ms)},Default,,0,0,0,,{tag}{text}")
    return head + "\n".join(events) + "\n"

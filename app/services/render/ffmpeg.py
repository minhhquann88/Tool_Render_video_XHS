"""Render thật bằng FFmpeg (bản kèm imageio-ffmpeg: libx264 + libass).

- Làm mờ: vùng cùng dải ngang gom lại, làm mờ dải 1 lần, mặt nạ (drawbox theo [start, end]) chọn chỗ hiện.
- Sub mới: file ASS, mỗi dòng đặt giữa vùng mờ của câu sub đang chạy (không có vùng thì đặt dưới khung).
- Giọng đọc: xếp lịch để các câu không đè nhau (tăng tốc nhẹ / lùi chút khi thiếu chỗ), adelay tới mốc đó, amix với tiếng gốc (giảm âm lượng, tắt hẳn lúc giọng AI đọc).
Mỗi phần bật/tắt độc lập theo ExportSettings -> chỉ che sub rồi xuất cũng được.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
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
        voices = _voice_schedule([l for l in project.subtitles if l.audio_path and Path(l.audio_path).exists()],
                                 duration) if exp.add_voice else []
        subs = _sub_timing(subs, voices)
        if not (regions or subs or voices) and exp.resolution == "original":
            raise ValueError("Không có gì để xử lý: chưa có vùng mờ / sub mới / giọng đọc nào được chọn")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="render_"))
        try:
            graph, v_out = self._video_graph(regions, subs, project.regions, ctx.style, width, height,
                                             exp.resolution, work)
            inputs = ["-i", str(project.local_path)]
            for v in voices:
                inputs += ["-i", str(v.line.audio_path)]
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

    def render_audio(self, project: VideoProject, ctx: RenderContext, out_path: Path,
                     progress: ProgressFn = no_progress) -> Path:
        """Chỉ dựng tiếng như lúc xuất (cùng lịch đọc, tăng tốc, nhạc nền) -> nghe thử, nhanh hơn render cả video."""
        exp = ctx.export
        _, _, duration, has_audio = probe(project.local_path)
        voices = _voice_schedule([l for l in project.subtitles if l.audio_path and Path(l.audio_path).exists()],
                                 duration)
        if not voices:
            raise ValueError("chưa có giọng đọc nào để nghe thử")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="dub_"))
        try:
            inputs = ["-i", str(project.local_path)]
            for v in voices:
                inputs += ["-i", str(v.line.audio_path)]
            graph, a_map, a_codec = self._audio_graph(voices, has_audio, exp.keep_original_audio, exp.original_volume)
            (work / "graph.txt").write_text(";\n".join(graph), encoding="utf-8")
            cmd = [ffmpeg_exe(), "-hide_banner", "-y", "-nostats", "-progress", "pipe:1", *inputs,
                   "-filter_complex_script", "graph.txt", "-vn", *a_map, *a_codec, "-t", f"{duration:.3f}",
                   str(out_path.resolve())]
            self._run(cmd, work, duration, "Đang ghép giọng để nghe thử…", progress)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        progress(100, "Xong")
        return out_path

    # ------------------------------------------------------------------ video
    def _video_graph(self, regions: list[BlurRegion], subs: list[_Sub], all_regions: list[BlurRegion],
                     style: SubStyle, width: int, height: int, resolution: str, work: Path) -> tuple[list[str], str]:
        graph: list[str] = []
        cur = "0:v"
        for k, (band, items) in enumerate(_blur_bands(regions, width, height)):
            # mỗi dải chữ chỉ làm mờ 1 lần; mặt nạ vẽ ô của từng câu theo thời gian quyết định chỗ nào hiện bản mờ.
            # (trước: mỗi vùng 1 nhánh split/crop/gblur/overlay -> 136 câu = 137 luồng, chậm và tốn RAM)
            bx, by, bw, bh = band
            sigma = max(max(6, reg.strength) for reg, _ in items)
            boxes = "".join(f",drawbox=x={x - bx}:y={y - by}:w={w}:h={h}:color=white:t=fill{_enable(reg)}"
                            for reg, (x, y, w, h) in items)
            graph += [
                f"[{cur}]format=yuv420p,split[bb{k}][bs{k}]",
                f"[bs{k}]crop={bw}:{bh}:{bx}:{by},split[bc{k}][bm{k}]",
                f"[bc{k}]gblur=sigma={sigma}:steps=2[bl{k}]",
                # drawbox tô trắng = 235 (dải giới hạn) -> nâng lên 255 cho mặt nạ che kín
                f"[bm{k}]lutyuv=y=0{boxes},lutyuv=y='if(val,255,0)',format=gray[mk{k}]",
                f"[bl{k}][mk{k}]alphamerge[ba{k}]",
                f"[bb{k}][ba{k}]overlay={bx}:{by}[o{k}]",
            ]
            cur = f"o{k}"
        if subs:
            (work / "subs.ass").write_text(_build_ass(subs, all_regions, style, width, height), encoding="utf-8")
            graph.append(f"[{cur}]ass=subs.ass[subbed]")  # chạy ffmpeg với cwd=work -> đường dẫn tương đối
            cur = "subbed"
        scale = _scale_filter(resolution, width, height)
        graph.append(f"[{cur}]{scale}[vout]" if scale else f"[{cur}]null[vout]")
        return graph, "[vout]"

    # ------------------------------------------------------------------ audio
    @staticmethod
    def _audio_graph(voices: list[_Voice], has_audio: bool, keep_original: bool,
                     original_volume: int) -> tuple[list[str], list[str], list[str]]:
        aac = ["-c:a", "aac", "-b:a", "160k"]
        if not voices:
            if has_audio and keep_original:
                return [], ["-map", "0:a:0"], ["-c:a", "copy"]
            return [], [], ["-an"]
        graph, labels = [], []
        if has_audio and keep_original:
            # tắt hẳn tiếng gốc trong lúc giọng AI đọc (không lẫn giọng gốc), ngoài các đoạn đó giữ nhạc nền
            mute = "".join(f",volume=0:enable='between(t,{a:.3f},{b:.3f})'" for a, b in _voice_windows(voices))
            graph.append(f"[0:a:0]volume={original_volume / 100:.2f}{mute}[orig]")
            labels.append("[orig]")
        for i, v in enumerate(voices, 1):
            tempo = f",atempo={v.tempo:.3f}" if v.tempo > 1.001 else ""
            graph.append(f"[{i}:a]aresample=44100{tempo},adelay={round(v.start * 1000)}:all=1[v{i}]")
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


_MAX_TEMPO = 1.35       # tăng tốc giọng đọc tối đa (nhanh hơn nữa nghe gấp, khó nghe)
_VOICE_GAP = 0.08       # giây nghỉ tối thiểu giữa 2 câu đọc
_VOICE_LEAD = 0.3       # được đọc sớm hơn mốc sub tối đa chừng này nếu phía trước còn trống
_REPEAT_GAP_MS = 1500   # câu giống hệt câu ngay trước, cách nhau ít hơn mức này -> sub bị lặp, không đọc lại


@dataclass
class _Voice:
    line: SubtitleLine
    start: float  # giây, lúc bắt đầu phát
    tempo: float  # >1 = đọc nhanh hơn
    end: float    # giây, lúc phát xong (đã tính tempo)


def _voice_schedule(lines: list[SubtitleLine], video_end: float = float("inf")) -> list[_Voice]:
    """Xếp lịch đọc để các câu không đè nhau.

    Mỗi câu bắt đầu ở mốc sub (sớm hơn tối đa _VOICE_LEAD nếu còn trống, hoặc ngay sau câu trước nếu câu trước chưa đọc xong) và nên xong trước mốc sub
    của câu kế; không đủ chỗ thì tăng tốc tới _MAX_TEMPO, vẫn thiếu thì câu sau lùi lại một chút (các câu sau
    có khoảng trống sẽ tự đuổi kịp).
    """
    import soundfile as sf

    kept: list[SubtitleLine] = []
    last_end = 0  # mốc kết thúc của câu đã giữ (gộp cả câu lặp bị bỏ), không sửa dữ liệu project
    for line in sorted(lines, key=lambda l: l.start_ms):
        if kept and line.text.strip() == kept[-1].text.strip() and line.start_ms - last_end <= _REPEAT_GAP_MS:
            last_end = max(last_end, line.end_ms)
            continue
        kept.append(line)
        last_end = line.end_ms
    out: list[_Voice] = []
    cursor = 0.0
    for i, line in enumerate(kept):
        try:
            dur = sf.info(str(line.audio_path)).duration
        except RuntimeError:
            dur = (line.end_ms - line.start_ms) / 1000  # không đọc được độ dài -> coi như vừa khung sub
        start = max(line.start_ms / 1000 - _VOICE_LEAD, cursor + _VOICE_GAP if out else 0.0)
        limit = kept[i + 1].start_ms / 1000 if i + 1 < len(kept) else video_end  # câu cuối xong trước khi hết video
        room = limit - start
        tempo = 1.0 if dur <= room else min(_MAX_TEMPO, dur / max(room, 0.01))
        cursor = start + dur / tempo
        out.append(_Voice(line, start, tempo, cursor))
    return out


@dataclass
class _Sub:
    line: SubtitleLine
    start_ms: int  # lúc hiện trên video (có thể lệch mốc gốc để khớp giọng đọc)
    end_ms: int


_SUB_GAP_MS = 20


def _sub_timing(lines: list[SubtitleLine], voices: list[_Voice]) -> list[_Sub]:
    """Thời gian hiện sub mới. Câu có giọng đọc hiện đúng lúc giọng đọc (lịch đã dời / tăng tốc) để chữ và
    tiếng khớp nhau, giữ ít nhất bằng độ dài gốc nhưng không lấn câu sau; câu lặp đã bỏ giọng thì bỏ cả sub."""
    if not voices:
        return [_Sub(l, l.start_ms, l.end_ms) for l in lines]
    plan = {id(v.line): (k, v) for k, v in enumerate(voices)}
    out: list[_Sub] = []
    for line in lines:
        hit = plan.get(id(line))
        if hit is None:
            if line.audio_path and Path(line.audio_path).exists():
                continue  # có giọng nhưng không có trong lịch = câu lặp, sub đã hiện ở câu trước
            out.append(_Sub(line, line.start_ms, line.end_ms))
            continue
        k, v = hit
        start = round(v.start * 1000)
        end = max(round(v.end * 1000), start + line.end_ms - line.start_ms)
        if k + 1 < len(voices):
            end = min(end, round(voices[k + 1].start * 1000) - _SUB_GAP_MS)
        out.append(_Sub(line, start, max(end, start + 200)))
    return out


def _voice_windows(voices: list[_Voice]) -> list[tuple[float, float]]:
    """Khoảng thời gian (giây) có giọng AI, gộp khoảng sát nhau -> tắt tiếng gốc trong các khoảng này."""
    merged: list[tuple[float, float]] = []
    for v in voices:
        a, b = v.start, max(v.end, v.line.end_ms / 1000)
        if merged and a <= merged[-1][1] + 0.2:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _px_rect(reg: BlurRegion, width: int, height: int) -> tuple[int, int, int, int]:
    even = lambda v: max(2, int(v) // 2 * 2)
    x = min(max(0, int(reg.x * width)), width - 2)
    y = min(max(0, int(reg.y * height)), height - 2)
    w = min(even(reg.w * width), (width - x) // 2 * 2)
    h = min(even(reg.h * height), (height - y) // 2 * 2)
    return x, y, w, h


def _blur_bands(regions: list[BlurRegion], width: int, height: int
                ) -> list[tuple[tuple[int, int, int, int], list[tuple[BlurRegion, tuple[int, int, int, int]]]]]:
    """Gom vùng mờ thành các dải ngang (chồng lấn dọc > 50%): [(dải x,y,w,h px, [(vùng, rect px)])]."""
    bands: list[list] = []  # [x0, y0, x1, y1, items]
    for reg in sorted(regions, key=lambda r: r.y):
        x, y, w, h = _px_rect(reg, width, height)
        for b in bands:
            if min(b[3], y + h) - max(b[1], y) > 0.5 * min(h, b[3] - b[1]):
                b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)
                b[4].append((reg, (x, y, w, h)))
                break
        else:
            bands.append([x, y, x + w, y + h, [(reg, (x, y, w, h))]])
    out = []
    for x0, y0, x1, y1, items in bands:
        x0, y0 = x0 // 2 * 2, y0 // 2 * 2
        out.append(((x0, y0, min(width - x0, (x1 - x0 + 1) // 2 * 2), min(height - y0, (y1 - y0 + 1) // 2 * 2)), items))
    return out


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
def _ass_color(hex_color: str, opacity: int = 100) -> str:
    """#RRGGBB + độ đậm % -> &HAABBGGRR của ASS (AA: 00 = đặc, FF = trong suốt)."""
    c = hex_color.lstrip("#")
    r, g, b = c[0:2], c[2:4], c[4:6]
    alpha = round(255 * (1 - max(0, min(100, opacity)) / 100))
    return f"&H{alpha:02X}{b}{g}{r}".upper()


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


def _build_ass(lines: list[_Sub], regions: list[BlurRegion], style: SubStyle,
               width: int, height: int) -> str:
    bold = -1 if style.bold else 0
    if style.bg_box:
        # BorderStyle 3 = khung đặc sau mỗi dòng chữ, màu khung = OutlineColour, Outline = lề quanh chữ
        border, outline = 3, max(4, style.font_size // 6)
        outline_color = _ass_color(style.bg_color, style.bg_opacity)
    else:
        border, outline = 1, max(2, style.font_size // 16)
        outline_color = _ass_color(style.outline_color)
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style.font_family},{style.font_size},{_ass_color(style.color)},&H000000FF,"
        f"{outline_color},&H00000000,{bold},0,0,0,100,100,0,0,{border},{outline},0,"
        f"2,{width // 20},{width // 20},{height // 10},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for sub in lines:
        line = sub.line
        text = line.text.strip().replace("{", "(").replace("}", ")").replace("\n", r"\N")
        pos = _anchor(line, regions, width, height)  # vị trí theo vùng mờ của chính câu đó (mốc gốc)
        tag = f"{{\\an5\\pos({pos[0]},{pos[1]})}}" if pos else ""
        events.append(f"Dialogue: 0,{_ass_time(sub.start_ms)},{_ass_time(sub.end_ms)},Default,,0,0,0,,{tag}{text}")
    return head + "\n".join(events) + "\n"

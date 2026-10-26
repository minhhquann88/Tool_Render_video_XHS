from __future__ import annotations

import re
from datetime import datetime
from dataclasses import replace
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QMainWindow, QMessageBox, QPlainTextEdit, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from app.config import (
    APP_NAME, DEFAULT_COOKIE_FILE, DOWNLOAD_DIR, PASTED_COOKIE_FILE, TTS_CACHE_DIR, VIDEO_FILTER,
)
from app.models import Status, VideoProject
from app.services import build_services
from app.services.render.base import RenderContext
from app.services.scraper.base import ScrapedVideo, extract_urls
from app.services.scraper.cookies import CookieInfo, load_cookie_file, parse_cookies
from app.ui.panels.detect_panel import DetectPanel
from app.ui.panels.export_panel import ExportPanel
from app.ui.panels.preview_panel import PreviewPanel
from app.ui.panels.queue_panel import QueuePanel
from app.ui.panels.subtitle_panel import SubtitlePanel
from app.ui.panels.voice_panel import VoicePanel
from app.ui.tasks import TaskRunner
from app.ui.widgets.common import StepNav, muted_label
from app.utils.srt import parse_srt, to_srt

_LOG_COLORS = {"info": "#c9ccd1", "ok": "#3ecf8e", "warn": "#f5a524", "error": "#ff5c5c"}
STEP_NAMES = ["Tìm & che sub", "Sub mới", "Giọng đọc", "Xuất video"]
STEP_DETECT, STEP_SUBS, STEP_VOICE, STEP_EXPORT = range(4)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1560, 940)

        self.services = build_services()
        self.runner = TaskRunner(self, on_unhandled_error=lambda m: self.log(m, "error"))
        self.projects: dict[str, VideoProject] = {}
        self.current: VideoProject | None = None
        self._batch: list[VideoProject] = []
        self._batch_export = None  # ExportSettings dùng cho cả lượt xuất
        self._batch_running = False
        self._batch_suffix = ""
        self._scanning: VideoProject | None = None  # video đang được quét tìm sub
        self._settings = QSettings()

        self._build_ui()
        self._connect()
        self.voice_panel.load_settings(self._settings)
        self.export_panel.load_settings(self._settings)
        self._set_current(None)
        self.log("Sẵn sàng. Dán link XHS hoặc mở file video để bắt đầu.")
        self._load_saved_cookie()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 8)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = muted_label(APP_NAME)
        title.setObjectName("AppTitle")
        header.addWidget(title)
        header.addSpacing(12)
        self.video_label = muted_label()
        header.addWidget(self.video_label, 1)
        root.addLayout(header)

        self.queue_panel = QueuePanel()
        self.preview_panel = PreviewPanel()
        self.detect_panel = DetectPanel()
        self.subtitle_panel = SubtitlePanel(self.services.subtitle_sources)
        self.voice_panel = VoicePanel(self.services.tts, self.runner, self.log)
        self.export_panel = ExportPanel(self.services.renderers, self.services.uploaders)

        # cột phải: 4 bước, mỗi bước một trang
        steps = QFrame()
        steps.setObjectName("StepPanel")
        steps.setMinimumWidth(460)
        sv = QVBoxLayout(steps)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)
        self.step_nav = StepNav(STEP_NAMES)
        self.pages = QStackedWidget()
        for page in (self.detect_panel, self.subtitle_panel, self.voice_panel, self.export_panel):
            self.pages.addWidget(page)
        sv.addWidget(self.step_nav)
        sv.addWidget(self.pages, 1)

        main_split = QSplitter(Qt.Horizontal)
        main_split.addWidget(self.queue_panel)
        main_split.addWidget(self.preview_panel)
        main_split.addWidget(steps)
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)
        main_split.setStretchFactor(2, 0)
        main_split.setSizes([290, 720, 540])

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)

        v_split = QSplitter(Qt.Vertical)
        v_split.addWidget(main_split)
        v_split.addWidget(self.log_view)
        v_split.setStretchFactor(0, 1)
        v_split.setSizes([840, 80])
        root.addWidget(v_split, 1)

        self.statusBar().showMessage("Sẵn sàng")

    def _connect(self) -> None:
        q = self.queue_panel
        q.btn_add.clicked.connect(self._on_add_links)
        q.btn_local.clicked.connect(self._on_open_local)
        q.btn_download.clicked.connect(self._on_download)
        q.btn_remove.clicked.connect(self._on_remove)
        q.act_cookie_file.triggered.connect(self._on_pick_cookie_file)
        q.act_cookie_paste.triggered.connect(self._on_paste_cookie)
        q.act_cookie_clear.triggered.connect(self._on_clear_cookie)
        q.list.currentItemChanged.connect(lambda *_: self._set_current(q.current_id()))

        p = self.preview_panel
        p.position_changed.connect(self._on_position)
        p.canvas.regions_changed.connect(self._on_regions_changed)

        self.step_nav.step_clicked.connect(self.go_step)
        d = self.detect_panel
        d.detect_requested.connect(self._on_detect)
        d.quick_export_requested.connect(self._on_blur_export)
        d.add_region_requested.connect(p.canvas.add_region)
        d.remove_region_requested.connect(p.canvas.remove_selected)
        d.next_requested.connect(lambda: self.go_step(STEP_SUBS))

        s = self.subtitle_panel
        s.generate_requested.connect(self._on_generate_subs)
        s.import_requested.connect(self._on_import_srt)
        s.export_requested.connect(self._on_export_srt)
        s.seek_requested.connect(p.seek)
        s.subtitles_changed.connect(self._refresh_steps)
        s.style_changed.connect(lambda: p.canvas.set_sub_style(s.sub_style()))
        s.back_requested.connect(lambda: self.go_step(STEP_DETECT))
        s.next_requested.connect(lambda: self.go_step(STEP_VOICE))

        v = self.voice_panel
        v.generate_dub_requested.connect(self._on_generate_dub)
        v.back_requested.connect(lambda: self.go_step(STEP_SUBS))
        v.next_requested.connect(lambda: self.go_step(STEP_EXPORT))

        e = self.export_panel
        e.render_requested.connect(self._on_render_current)
        e.back_requested.connect(lambda: self.go_step(STEP_VOICE))
        e.render_all_requested.connect(self._on_render_all)
        e.connect_requested.connect(self._on_connect_uploader)

    # ------------------------------------------------------------- helpers
    def log(self, msg: str, level: str = "info") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        color = _LOG_COLORS.get(level, _LOG_COLORS["info"])
        safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log_view.appendHtml(f'<span style="color:#5d626b">{ts}</span>&nbsp;&nbsp;'
                                 f'<span style="color:{color}">{safe}</span>')
        if level == "error":
            self.statusBar().showMessage(msg, 8000)

    def _update(self, project: VideoProject, status: Status | None = None, progress: int | None = None,
                error: str = "") -> None:
        if status is not None:
            project.status = status
        if progress is not None:
            project.progress = progress
        project.error = error
        self.queue_panel.upsert(project)
        if project is self.current:
            self._refresh_steps()

    def go_step(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.step_nav.set_current(index)

    def _refresh_steps(self) -> None:
        """Cập nhật trạng thái 4 bước + nút bật/tắt theo dữ liệu của video đang chọn."""
        project = self.current
        has_video = bool(project and project.local_path)
        lines = project.subtitles if project else []
        n_regions = len(project.regions) if project else 0
        n_text = sum(1 for l in lines if l.text.strip())
        n_voices = sum(1 for l in lines if l.audio_path)
        self.step_nav.set_done([n_regions > 0, n_text > 0, n_voices > 0,
                                bool(project and project.output_path)])
        self.detect_panel.set_state(has_video, n_regions, len(lines),
                                    busy=self._scanning is not None)
        self.voice_panel.set_line_count(n_text if has_video else 0, n_voices)
        self.export_panel.set_availability(n_regions, n_text, n_voices)
        self.video_label.setText(f"·  {project.display_name}" if project else "")

    def _require_video(self) -> VideoProject | None:
        if self.current and self.current.local_path:
            return self.current
        self.log("Chọn một video đã tải trong hàng chờ trước.", "warn")
        return None

    def _fail(self, project: VideoProject, what: str, msg: str) -> None:
        self._update(project, Status.ERROR, error=msg)
        self.log(f"[{project.display_name}] {what} lỗi: {msg}", "error")

    # ---------------------------------------------------------- 1. nguồn video
    def _on_add_links(self) -> None:
        urls = extract_urls(self.queue_panel.take_links_text())
        if not urls:
            self.log("Không tìm thấy link nào.", "warn")
            return
        known = {p.url for p in self.projects.values()}
        added = []
        for url in urls:
            if url in known:
                continue
            if not self.services.scraper_for(url):
                self.log(f"Bỏ qua link không phải XHS: {url}", "warn")
                continue
            project = VideoProject(url=url)
            self.projects[project.id] = project
            self.queue_panel.upsert(project)
            added.append(project)
        if added:
            self.log(f"Đã thêm {len(added)} link.", "ok")
            if not self.current:
                self.queue_panel.select(added[0].id)
            self._download(added)

    def _on_open_local(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Mở video", "", VIDEO_FILTER)
        for f in files:
            path = Path(f)
            project = VideoProject(title=path.stem, local_path=path, status=Status.READY)
            self.projects[project.id] = project
            self.queue_panel.upsert(project)
            self.queue_panel.select(project.id)
        if files:
            self.log(f"Đã mở {len(files)} video từ máy.", "ok")

    # ---------------------------------------------------------------- cookie
    def _load_saved_cookie(self) -> None:
        saved = self._settings.value("xhs/cookie_path", "")
        if saved == "-":  # người dùng đã gỡ cookie
            self._apply_cookie(CookieInfo(), None)
            return
        path = Path(saved) if saved else DEFAULT_COOKIE_FILE
        if path.exists():
            self._use_cookie_file(path)
        else:
            self._apply_cookie(CookieInfo(), None)

    def _use_cookie_file(self, path: Path) -> None:
        try:
            info = load_cookie_file(path)
        except (OSError, ValueError, KeyError) as e:
            self.log(f"Không đọc được cookie {path.name}: {e}", "error")
            return
        self._apply_cookie(info, path)

    def _apply_cookie(self, info: CookieInfo, path: Path | None) -> None:
        for scraper in self.services.scrapers:
            scraper.set_cookies(info.cookies)
        self._settings.setValue("xhs/cookie_path", str(path) if path else "-")
        self.queue_panel.set_cookie_status(info.summary(), info.logged_in)
        self.queue_panel.cookie_label.setToolTip(str(path) if path else "")
        if not path:
            return
        level = "ok" if info.logged_in else "warn"
        self.log(f"Đã gắn cookie từ {path.name}: {info.summary()}", level)
        if info.expired:
            self.log(f"Bỏ qua {len(info.expired)} cookie đã hết hạn: {', '.join(info.expired)}", "warn")

    def _on_pick_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file cookie XHS", str(DEFAULT_COOKIE_FILE.parent),
                                              "Cookie (*.txt *.json);;Tất cả (*)")
        if path:
            self._use_cookie_file(Path(path))

    def _on_paste_cookie(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self, "Dán cookie XHS",
            "Dán chuỗi cookie (a1=…; web_session=…) hoặc nội dung file cookie.txt:")
        if not ok or not text.strip():
            return
        if not parse_cookies(text).cookies:
            self.log("Chuỗi cookie không hợp lệ.", "error")
            return
        PASTED_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PASTED_COOKIE_FILE.write_text(text.strip(), encoding="utf-8")
        self._use_cookie_file(PASTED_COOKIE_FILE)

    def _on_clear_cookie(self) -> None:
        self._apply_cookie(CookieInfo(), None)
        self.log("Đã gỡ cookie XHS.")

    def _on_remove(self) -> None:
        for pid in self.queue_panel.selected_ids():
            project = self.projects[pid]
            if project.status.busy:
                self.log(f"[{project.display_name}] đang xử lý, không xoá được.", "warn")
                continue
            self.queue_panel.remove(pid)
            del self.projects[pid]
        if self.current and self.current.id not in self.projects:
            self._set_current(self.queue_panel.current_id())

    def _on_download(self) -> None:
        ids = self.queue_panel.selected_ids()
        targets = [self.projects[i] for i in ids] if ids else list(self.projects.values())
        self._download(targets)

    def _download(self, projects: list[VideoProject]) -> None:
        targets = [p for p in projects if p.url and p.status in (Status.PENDING, Status.ERROR)]
        if not targets:
            self.log("Không có video nào cần tải.", "warn")
            return
        for project in targets:
            scraper = self.services.scraper_for(project.url)
            self._update(project, Status.DOWNLOADING, 0)
            self.runner.submit(
                scraper.download, project.url, DOWNLOAD_DIR,
                on_result=partial(self._on_downloaded, project),
                on_error=partial(self._fail, project, "Tải video"),
                on_progress=lambda pct, _msg, p=project: self._update(p, progress=pct),
            )
        self.log(f"Bắt đầu tải {len(targets)} video…")

    def _on_downloaded(self, project: VideoProject, video: ScrapedVideo) -> None:
        project.local_path = video.video_path
        project.title = video.title or project.title
        self._update(project, Status.READY, 100)
        self.log(f"Đã tải: {project.display_name}", "ok")
        if project is self.current:
            self.preview_panel.load(project.local_path)
            self.subtitle_panel.set_enabled(True)
            self._refresh_steps()

    def _set_current(self, project_id: str | None) -> None:
        project = self.projects.get(project_id) if project_id else None
        if project is self.current and project is not None:
            return
        self.current = project
        self.preview_panel.load(project.local_path if project else None)
        self.preview_panel.canvas.set_regions(project.regions if project else [], notify=False)
        self.subtitle_panel.set_lines(project.subtitles if project else [])
        self.subtitle_panel.set_enabled(bool(project and project.local_path))
        self.export_panel.set_result(project.output_path if project else None, project.drive_link if project else "")
        if not self._batch_running:
            self.export_panel.progress.finish()
        self.preview_panel.canvas.set_sub_style(self.subtitle_panel.sub_style())
        self._refresh_steps()

    # --------------------------------------------------------- 2. vùng làm mờ
    def _on_detect(self) -> None:
        """Quét video: vùng mờ theo từng câu sub + tự điền sub gốc sang bước 2 (một lần quét cho cả hai)."""
        project = self._require_video()
        if not project or self._scanning:
            return
        detector = next(iter(self.services.detectors.values()))
        source = next(iter(self.services.subtitle_sources.values()))
        bar = self.detect_panel.progress
        self.log(f"[{project.display_name}] Đang tìm sub…")

        def job(progress):
            regions = detector.detect(project.local_path, progress)
            lines = source.generate(project.local_path, regions, 0)  # dùng lại kết quả quét, không quét lại
            return regions, lines

        def done(result):
            regions, lines = result
            self._scanning = None
            project.regions = regions
            if not any(l.text.strip() for l in project.subtitles):  # không ghi đè sub mới người dùng đã gõ
                project.subtitles[:] = lines
            if project is self.current:
                self.preview_panel.canvas.set_regions(regions)
                self.subtitle_panel.set_lines(project.subtitles)
            bar.finish()
            self._refresh_steps()
            self.log(f"[{project.display_name}] Tìm thấy {len(lines)} câu sub, {len(regions)} vùng mờ.", "ok")

        def failed(msg):
            self._scanning = None
            bar.finish(f"Lỗi: {msg}")
            self._refresh_steps()
            self.log(f"Tìm sub lỗi: {msg}", "error")

        self._scanning = project
        self._refresh_steps()
        bar.update(0, "Đang chuẩn bị…")
        self.runner.submit(job, on_result=done, on_error=failed,
                           on_progress=lambda pct, msg: bar.update(pct, msg))

    def _on_regions_changed(self) -> None:
        if self.current:
            self.current.regions = self.preview_panel.canvas.regions()
            self._refresh_steps()

    def _on_position(self, ms: int) -> None:
        self.subtitle_panel.highlight_at(ms)
        self.preview_panel.canvas.set_position(ms)
        self.preview_panel.canvas.set_overlay_text(self.subtitle_panel.text_at(ms))

    # -------------------------------------------------------------- 3. phụ đề
    def _on_generate_subs(self, source_id: str) -> None:
        project = self._require_video()
        if not project:
            return
        if self._scanning:
            return
        source = self.services.subtitle_sources[source_id]
        self.log(f"[{project.display_name}] Đang đọc lại sub gốc…")

        def done(lines):
            project.subtitles[:] = lines  # giữ nguyên list đang gắn với bảng
            if project is self.current:
                self.subtitle_panel.set_lines(project.subtitles)
                self._refresh_steps()
            self.log(f"[{project.display_name}] Đã đọc {len(lines)} dòng sub gốc.", "ok")

        self.runner.submit(source.generate, project.local_path, list(project.regions),
                           self.preview_panel.duration_ms, on_result=done,
                           on_error=lambda m: self.log(f"Đọc sub lỗi: {m}", "error"),
                           on_progress=lambda pct, msg: self.statusBar().showMessage(f"{msg} {pct}%", 3000))

    def _on_import_srt(self) -> None:
        project = self._require_video()
        if not project:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Nhập phụ đề", "", "Phụ đề (*.srt)")
        if path:
            project.subtitles[:] = parse_srt(Path(path).read_text(encoding="utf-8-sig"))
            self.subtitle_panel.set_lines(project.subtitles)
            self._refresh_steps()
            self.log(f"Đã nhập {len(project.subtitles)} dòng từ {Path(path).name}", "ok")

    def _on_export_srt(self) -> None:
        project = self._require_video()
        if not project or not project.subtitles:
            return
        default = str((project.local_path.with_suffix(".srt")))
        path, _ = QFileDialog.getSaveFileName(self, "Xuất phụ đề", default, "Phụ đề (*.srt)")
        if path:
            # chưa có sub mới thì xuất sub gốc
            lines = [replace(l, text=l.text if l.text.strip() else l.original) for l in project.subtitles]
            Path(path).write_text(to_srt(lines), encoding="utf-8")
            self.log(f"Đã xuất sub ra {path}", "ok")

    # ------------------------------------------------------------ 4. giọng đọc
    def _on_generate_dub(self) -> None:
        project = self._require_video()
        if not project:
            return
        lines = [(i, l.text) for i, l in enumerate(project.subtitles) if l.text.strip()]
        if not lines:
            self.log("Chưa có sub mới để lồng tiếng.", "warn")
            return
        settings = self.voice_panel.settings()
        provider = self.services.tts[settings.provider]
        out_dir = TTS_CACHE_DIR / project.id

        def job(progress):
            paths = {}
            for n, (i, text) in enumerate(lines):
                progress(int(n / len(lines) * 100), f"Đang đọc dòng {n + 1}/{len(lines)}")
                paths[i] = provider.synthesize(text, settings, out_dir / f"line_{i:03d}.mp3")
            return paths

        panel = self.voice_panel

        def done(paths):
            for i, path in paths.items():
                if i < len(project.subtitles):
                    project.subtitles[i].audio_path = path
            panel.btn_dub.setEnabled(True)
            panel.progress.finish()
            self._update(project, Status.READY)
            self.log(f"[{project.display_name}] Đã tạo {len(paths)} đoạn lồng tiếng ({settings.voice_id}).", "ok")

        def failed(msg):
            panel.btn_dub.setEnabled(True)
            panel.progress.finish(f"Lỗi: {msg}")
            self._fail(project, "Lồng tiếng", msg)

        self._update(project, Status.PROCESSING, 0)
        panel.btn_dub.setEnabled(False)
        panel.progress.update(0, "Đang tạo giọng đọc…")
        self.runner.submit(
            job, on_result=done, on_error=failed,
            on_progress=lambda pct, msg: (self._update(project, progress=pct), panel.progress.update(pct, msg)),
        )

    # ------------------------------------------------------ 5-6. render + upload
    def _on_render_current(self) -> None:
        project = self._require_video()
        if project:
            self._start_batch([project], self.export_panel.export_settings())

    def _on_blur_export(self) -> None:
        """Chỉ che sub gốc rồi xuất: giữ nguyên tiếng gốc, không chèn sub / giọng."""
        project = self._require_video()
        if not project or self._batch_running:
            return
        if not project.regions:
            self.log("Chưa có vùng mờ nào: bấm 'Tự động tìm sub' hoặc '+ Thêm vùng mờ' trước.", "warn")
            return
        export = replace(self.export_panel.export_settings(), apply_blur=True, burn_subs=False,
                         add_voice=False, keep_original_audio=True)
        self.go_step(STEP_EXPORT)  # để thấy tiến trình
        self._start_batch([project], export, suffix="_che-sub")

    def _on_render_all(self) -> None:
        projects = [p for p in self.projects.values() if p.local_path and not p.status.busy]
        if not projects:
            self.log("Chưa có video nào đã tải để render.", "warn")
            return
        self.log(f"Chạy hàng loạt {len(projects)} video…")
        self._start_batch(projects, self.export_panel.export_settings())

    def _start_batch(self, projects: list[VideoProject], export, suffix: str = "") -> None:
        self._batch = list(projects)
        self._batch_export = export
        self._batch_suffix = suffix
        self._next_in_batch()

    def _next_in_batch(self) -> None:
        if not self._batch:
            self._batch_running = False
            self.export_panel.set_busy(False)
            self._refresh_steps()
            return
        self._batch_running = True
        self.export_panel.set_busy(True)
        self._render(self._batch.pop(0))

    def _render(self, project: VideoProject) -> None:
        # mỗi video tự bỏ qua phần nó chưa có (vd. xuất tất cả mà có video chưa tạo giọng)
        base = self._batch_export
        export = replace(base,
                         apply_blur=base.apply_blur and bool(project.regions),
                         burn_subs=base.burn_subs and any(l.text.strip() for l in project.subtitles),
                         add_voice=base.add_voice and any(l.audio_path for l in project.subtitles))
        ctx = RenderContext(style=self.subtitle_panel.sub_style(), voice=self.voice_panel.settings(), export=export)
        renderer = self.services.renderers[export.renderer_id]
        safe = re.sub(r'[\\/:*?"<>|]+', "_", project.display_name)[:60]
        out_path = export.output_dir / f"{safe}_{project.id}{self._batch_suffix}.mp4"

        def progress(pct, msg):
            self._update(project, progress=pct)
            self.export_panel.set_progress(pct, f"[{project.display_name}] {msg}")

        def done(path: Path):
            project.output_path = path
            self.log(f"[{project.display_name}] Render xong: {path}", "ok")
            if export.auto_upload:
                self._upload(project, export)
            else:
                self._finish(project)

        def failed(msg):
            self._fail(project, "Render", msg)
            self.export_panel.progress.finish(f"Lỗi: {msg}")
            self._next_in_batch()

        self._update(project, Status.RENDERING, 0)
        self.log(f"[{project.display_name}] Bắt đầu render ({renderer.name})…")
        self.runner.submit(renderer.render, project, ctx, out_path,
                           on_result=done, on_error=failed, on_progress=progress)

    def _upload(self, project: VideoProject, export) -> None:
        uploader = self.services.uploaders[export.uploader_id]

        def progress(pct, msg):
            self._update(project, progress=pct)
            self.export_panel.set_progress(pct, f"[{project.display_name}] {msg}")

        def done(link: str):
            project.drive_link = link
            self.log(f"[{project.display_name}] Upload xong: {link}", "ok")
            self._finish(project)

        def failed(msg):
            self._fail(project, "Upload", msg)
            self._next_in_batch()

        self._update(project, Status.UPLOADING, 0)
        self.runner.submit(uploader.upload, project.output_path, export.drive_folder,
                           on_result=done, on_error=failed, on_progress=progress)

    def _finish(self, project: VideoProject) -> None:
        self._update(project, Status.DONE, 100)
        self.export_panel.progress.finish()
        if project is self.current:
            self.export_panel.set_result(project.output_path, project.drive_link)
        self._next_in_batch()

    def _on_connect_uploader(self, uploader_id: str) -> None:
        uploader = self.services.uploaders[uploader_id]

        def failed(msg):
            self.log(f"Kết nối {uploader.name} lỗi: {msg}", "error")
            QMessageBox.information(self, uploader.name, msg)

        self.runner.submit(uploader.connect, on_result=self.export_panel.set_account, on_error=failed)

    # ---------------------------------------------------------------- đóng app
    def closeEvent(self, event) -> None:
        self.voice_panel.save_settings(self._settings)
        self.export_panel.save_settings(self._settings)
        self.preview_panel.player.stop()
        self.runner.shutdown()
        super().closeEvent(event)

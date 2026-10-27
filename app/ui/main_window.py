from __future__ import annotations

import hashlib
import re
from datetime import datetime
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QStackedWidget, QStyle, QVBoxLayout, QWidget,
)

from app.config import (
    APP_NAME, DEFAULT_COOKIE_FILE, DOWNLOAD_DIR, PASTED_COOKIE_FILE, TTS_CACHE_DIR, VIDEO_FILTER,
)
from app.models import ExportSettings, Status, TranslateSettings, VideoProject
from app.services import build_services
from app.services.render.base import RenderContext
from app.services.scraper.base import ScrapedVideo, extract_urls
from app.services.scraper.cookies import CookieInfo, load_cookie_file, parse_cookies
from app.services.translate.subtrans import overlong_seconds
from app.ui.panels.preview_panel import PreviewPanel
from app.ui.panels.queue_panel import QueuePanel
from app.ui.panels.settings_dialog import SettingsDialog
from app.ui.panels.sub_editor import SubEditor
from app.ui.panels.workflow_panel import WorkflowPanel
from app.ui.tasks import TaskRunner
from app.ui.widgets.common import ElidedLabel, dot_icon, ghost, muted_label, set_prop
from app.ui.workflow import (
    DETECT, EXPORT, ORDER, OUTPUT_SUFFIX, SHORT, TRANSLATE, VOICE, pending_steps, progress_text, stale_voice_count,
    step_info,
)
from app.utils.timefmt import ms_to_clock

_LOG_COLORS = {"info": "#c9ccd1", "ok": "#3ecf8e", "warn": "#f5a524", "error": "#ff5c5c"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1560, 940)

        self.services = build_services()
        self.runner = TaskRunner(self, on_unhandled_error=lambda m: self.log(m, "error"))
        self.projects: dict[str, VideoProject] = {}
        self.current: VideoProject | None = None
        self._auto_queue: list[tuple[VideoProject, str]] = []
        self._waiting: list[tuple] = []  # (video, bước, then, failed, kwargs) chờ video khác chạy xong bước đó  # (video, bước) còn chờ chạy tự động
        self._auto_running = False
        self._auto_stopped = False
        self._stop_at: int | None = None  # "Phát câu này": dừng khi tới mốc này
        self._dub_key = None  # dữ liệu của tiếng nghe thử đang gắn trên khung xem trước -> đổi thì bỏ tiếng cũ
        self._cookie = ("chưa gắn", False, "")  # (tóm tắt, đã đăng nhập, đường dẫn)
        self._settings = QSettings()

        self._build_ui()
        self._connect()
        self.settings_dialog.load_settings(self._settings)
        self.workflow.translate.load_settings(self._settings)
        self.workflow.voice.load_settings(self._settings)
        self.workflow.export.load_settings(self._settings)
        self._set_current(None)
        self.log("Sẵn sàng. Dán link XHS hoặc mở file video để bắt đầu.")
        self._load_saved_cookie()
        self._load_drive_account()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        main = QWidget()
        root = QVBoxLayout(main)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("TopBar")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.setSpacing(8)
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        self.video_label = muted_label()
        self.chip_cookie = self._header_chip()
        self.chip_key = self._header_chip()
        self.chip_drive = self._header_chip()
        self.btn_settings = QPushButton("Cài đặt")
        self.btn_settings.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        hl.addWidget(title)
        hl.addSpacing(8)
        hl.addWidget(self.video_label, 1)
        for w in (self.chip_cookie, self.chip_key, self.chip_drive, self.btn_settings):
            hl.addWidget(w)
        root.addWidget(header)

        self.queue_panel = QueuePanel()
        self.preview_panel = PreviewPanel()
        self.workflow = WorkflowPanel(self.services.tts, self.runner, self.log)

        self.main_split = QSplitter(Qt.Horizontal)
        self.main_split.addWidget(self.queue_panel)
        self.main_split.addWidget(self.preview_panel)
        self.main_split.addWidget(self.workflow)
        self.main_split.setStretchFactor(0, 0)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setStretchFactor(2, 0)
        self.main_split.setSizes([280, 760, 480])

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        self.log_view.setVisible(False)

        v_split = QSplitter(Qt.Vertical)
        v_split.addWidget(self.main_split)
        v_split.addWidget(self.log_view)
        v_split.setStretchFactor(0, 1)
        v_split.setSizes([800, 140])
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 12, 16, 0)
        bl.addWidget(v_split)
        root.addWidget(body, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(16, 6, 16, 8)
        self.log_dot = QLabel()
        self.log_label = ElidedLabel()
        self.log_label.setObjectName("Muted")
        self.btn_log = ghost(QPushButton("Nhật ký"))
        self.btn_log.setCheckable(True)
        footer.addWidget(self.log_dot)
        footer.addWidget(self.log_label, 1)
        footer.addWidget(self.btn_log)
        root.addLayout(footer)

        self.editor = SubEditor()
        self.stack.addWidget(main)
        self.stack.addWidget(self.editor)
        self.main_page = main

        self.settings_dialog = SettingsDialog(self.services.uploaders, self)

    def _header_chip(self) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("HeaderChip")
        btn.clicked.connect(lambda: self._open_settings())
        return btn

    def _connect(self) -> None:
        q = self.queue_panel
        q.btn_add.clicked.connect(self._on_add_links)
        q.btn_local.clicked.connect(self._on_open_local)
        q.btn_download.clicked.connect(self._on_download)
        q.btn_remove.clicked.connect(self._on_remove)
        q.list.currentItemChanged.connect(lambda *_: self._set_current(q.current_id()))

        p = self.preview_panel
        p.position_changed.connect(self._on_position)
        p.canvas.regions_changed.connect(self._on_regions_changed)
        p.player.durationChanged.connect(lambda _: self._refresh_header())

        w = self.workflow
        w.goal_changed.connect(self._on_goal)
        w.auto_requested.connect(self._on_auto)
        w.auto_all_requested.connect(self._on_auto_all)
        w.detect.run_requested.connect(lambda: self._run_manual(DETECT))
        w.detect.add_region_requested.connect(p.canvas.add_region)
        w.detect.remove_region_requested.connect(p.canvas.remove_selected)
        w.translate.run_requested.connect(lambda: self._run_manual(TRANSLATE))
        w.translate.edit_requested.connect(self._open_editor)
        w.translate.settings_requested.connect(lambda: self._open_settings(keys=True))
        w.translate.style_changed.connect(self._on_style)
        w.translate.target_changed.connect(self._refresh)
        w.voice.run_requested.connect(lambda only_missing: self._run_manual(VOICE, only_missing=only_missing))
        w.voice.listen_requested.connect(self._on_listen)
        w.voice.bg_check.toggled.connect(lambda _: self._refresh())  # chip "nhạc nền …%" ở bước Xuất
        w.voice.orig_volume.value_changed.connect(lambda _: self._refresh())
        w.export.run_requested.connect(self._on_export_clicked)
        w.export.settings_requested.connect(lambda: self._open_settings())

        s = self.settings_dialog
        s.cookie_file_requested.connect(self._on_pick_cookie_file)
        s.cookie_paste_requested.connect(self._on_paste_cookie)
        s.cookie_clear_requested.connect(self._on_clear_cookie)
        s.connect_requested.connect(self._on_connect_uploader)
        s.disconnect_requested.connect(self._on_disconnect_uploader)
        s.cancel_login_requested.connect(lambda uid: self.services.uploaders[uid].cancel_login())
        s.reopen_login_requested.connect(lambda uid: self.services.uploaders[uid].reopen_login())
        s.changed.connect(self._refresh)

        e = self.editor
        e.back_requested.connect(self._close_editor)
        e.seek_requested.connect(p.seek)
        e.play_line_requested.connect(self._play_line)
        e.voice_requested.connect(self.workflow.voice.play)
        e.translate_requested.connect(self._translate_lines)
        e.shorten_requested.connect(self._shorten_line)
        e.lines_changed.connect(self._on_lines_edited)

        self.btn_settings.clicked.connect(lambda: self._open_settings())
        self.btn_log.toggled.connect(self.log_view.setVisible)

    # ------------------------------------------------------------- helpers
    def log(self, msg: str, level: str = "info") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        color = _LOG_COLORS.get(level, _LOG_COLORS["info"])
        safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log_view.appendHtml(f'<span style="color:#5d626b">{ts}</span>&nbsp;&nbsp;'
                                 f'<span style="color:{color}">{safe}</span>')
        self.log_label.set_full_text(msg)
        self.log_dot.setPixmap(dot_icon(color).pixmap(12, 12))

    @property
    def has_key(self) -> bool:
        return bool(self.settings_dialog.api_keys())

    def _default_goal(self) -> str:
        goal = self._settings.value("workflow/goal", "dub")
        return goal if goal in ORDER else "dub"

    def _touch(self, project: VideoProject) -> None:
        """Dữ liệu / trạng thái của video đổi: cập nhật danh sách và (nếu đang chọn) cột quy trình."""
        self.queue_panel.upsert(project, *progress_text(project, self.has_key))
        if project is self.current:
            self._refresh()

    def _update(self, project: VideoProject, status: Status | None = None, progress: int | None = None,
                error: str = "") -> None:
        if status is not None:
            project.status = status
        if progress is not None:
            project.progress = progress
        project.error = error
        self._touch(project)

    def _refresh_header(self) -> None:
        cookie_text, cookie_ok, cookie_path = self._cookie
        self.chip_cookie.setText("Cookie XHS")
        self.chip_cookie.setIcon(dot_icon("#3ecf8e" if cookie_ok else "#f5a524" if cookie_path else "#9aa0a9",
                                          filled=bool(cookie_path)))
        self.chip_cookie.setToolTip(f"Cookie: {cookie_text}")
        set_prop(self.chip_cookie, "tone", "" if cookie_ok or not cookie_path else "warn")
        self.chip_key.setText("Gemini" if self.has_key else "Gemini: chưa có key")
        self.chip_key.setIcon(dot_icon("#3ecf8e" if self.has_key else "#f5a524"))
        set_prop(self.chip_key, "tone", "" if self.has_key else "warn")
        account = self.settings_dialog.drive_account
        self.chip_drive.setText("Drive" if account else "Drive (tuỳ chọn)")
        self.chip_drive.setIcon(dot_icon("#3ecf8e" if account else "#9aa0a9", filled=bool(account)))
        self.chip_drive.setToolTip(account)
        p = self.current
        duration = self.preview_panel.duration_ms
        self.video_label.setText(f"{p.display_name}" + (f" · {ms_to_clock(duration)}" if duration else "")
                                 if p else "")

    def _refresh(self) -> None:
        """Cập nhật cột quy trình theo dữ liệu của video đang chọn."""
        self._refresh_header()
        w = self.workflow
        p = self.current
        # sub mới trên khung xem trước theo dữ liệu hiện tại (dịch xong / rút gọn / đổi video khi video đang dừng)
        self.preview_panel.canvas.set_overlay_text(self.editor.text_at(self.preview_panel.position_ms))
        if self._dub_key is not None and self._dub_key != self._listen_key(p):
            self._dub_key = None  # giọng / nhạc nền / video đã đổi -> tiếng nghe thử cũ không còn đúng
            self.preview_panel.set_dub_audio(None)
        n_ready = sum(1 for x in self.projects.values() if x.local_path)
        all_text = f"Làm cho cả {n_ready} video"
        if not p:
            w.set_goal(None)
            w.set_empty(True)
            w.set_auto("Làm tự động từ đầu đến cuối", False, all_text, False)
            return
        has_key = self.has_key
        w.set_empty(False)
        w.set_goal(p.goal)
        order = ORDER[p.goal]
        infos = {k: step_info(p, k, has_key) for k in order}
        has_video = bool(p.local_path)
        queued = any(q is p for q, _ in self._auto_queue)
        can = has_video and not p.busy_step and not p.waiting_step and not queued

        lines = p.subtitles
        n_orig = sum(1 for l in lines if l.original.strip())
        n_text = sum(1 for l in lines if l.text.strip())
        n_voices = sum(1 for l in lines if l.audio_path)
        n_missing = sum(1 for l in lines if l.text.strip() and not l.audio_path)
        timed = sum(1 for r in p.regions if r.end_ms is not None)
        tgt = w.translate.target_label()

        w.cards[TRANSLATE].title.setText(f"Dịch sub sang {tgt}")
        w.detect.set_state(can, has_video, timed, len(p.regions) - timed)
        summary = f"Đã có sub mới cho {n_text}/{max(n_orig, n_text)} câu."
        n_long = len(overlong_seconds(lines))
        if n_long:
            summary += f" Có {n_long} câu hơi dài so với thời lượng, nên xem lại."
        w.translate.set_state(can, bool(lines), has_key, summary)
        w.voice.set_state(can, n_text, n_voices, n_missing)
        chips, missing = self._export_chips(p, infos, tgt)
        w.export.set_state(can, chips, missing, p.output_path, p.drive_link)
        w.export.set_drive_connected(self.settings_dialog.uploader_id() != "gdrive"
                                     or bool(self.settings_dialog.drive_account))
        w.set_steps(order, infos, p.busy_step or p.waiting_step, p.step_progress, waiting=bool(p.waiting_step))
        if w.open_step is not None and w.open_step not in order:
            self._open_first_pending(p)

        pending = [k for k in order if not infos[k].done]
        if self._auto_running:
            auto, auto_on = "Dừng sau bước đang chạy", not self._auto_stopped
        elif not pending:
            auto, auto_on = "Đã xong tất cả bước", False
        elif len(pending) < len(order):
            auto, auto_on = f"Làm tự động {len(pending)} bước còn lại", can
        else:
            auto, auto_on = "Làm tự động từ đầu đến cuối", can
        w.set_auto(auto, auto_on, all_text, not self._auto_running and n_ready > 1)
        if self.stack.currentWidget() is self.editor:
            self.editor.set_busy(p.busy_step == TRANSLATE)

    def _export_chips(self, p: VideoProject, infos, tgt: str) -> tuple[list[tuple[str, bool]], str]:
        done = {k: i.done for k, i in infos.items()}
        chips = [("✓ Che sub gốc" if done[DETECT] else "Che sub gốc (chưa làm)", done[DETECT])]
        if p.goal != "blur":
            chips.append((f"✓ Sub {tgt}" if done[TRANSLATE] else f"Sub {tgt} (chưa làm)", done[TRANSLATE]))
        if p.goal == "dub":
            voice = self.workflow.voice
            ok_text = (f"✓ Giọng AI + nhạc nền {voice.original_volume()}%" if voice.keep_background()
                       else "✓ Giọng AI (tắt nhạc nền)")
            chips.append((ok_text if done[VOICE] else "Giọng AI (chưa xong)", done[VOICE]))
        else:
            chips.append(("✓ Giữ tiếng gốc", True))
        missing = [SHORT[k] for k in ORDER[p.goal] if k != EXPORT and not done[k]]
        text = (f"Còn {len(missing)} bước chưa xong ({', '.join(missing)}) — xuất bây giờ sẽ bỏ qua phần đó."
                if missing else "")
        return chips, text

    def _open_first_pending(self, project: VideoProject) -> None:
        pending = pending_steps(project, self.has_key)
        self.workflow.set_open(pending[0] if pending else ORDER[project.goal][-1])

    def _open_settings(self, keys: bool = False) -> None:
        if keys:
            self.settings_dialog.open_keys()
        self.settings_dialog.exec()
        self._refresh()

    # ---------------------------------------------------------- nguồn video
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
            project = VideoProject(url=url, goal=self._default_goal())
            self.projects[project.id] = project
            self._touch(project)
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
            project = VideoProject(title=path.stem, local_path=path, status=Status.READY, goal=self._default_goal())
            self.projects[project.id] = project
            self._touch(project)
            self.queue_panel.select(project.id)
        if files:
            self.log(f"Đã mở {len(files)} video từ máy.", "ok")

    def _on_remove(self) -> None:
        for pid in self.queue_panel.selected_ids():
            project = self.projects[pid]
            if project.status.busy or project.busy_step:
                self.log(f"[{project.display_name}] đang xử lý, không xoá được.", "warn")
                continue
            self._auto_queue = [(q, k) for q, k in self._auto_queue if q is not project]
            self._waiting = [w for w in self._waiting if w[0] is not project]
            self.queue_panel.remove(pid)
            del self.projects[pid]
        if self.current and self.current.id not in self.projects:
            self._set_current(self.queue_panel.current_id())
        self._refresh()

    def _on_download(self) -> None:
        ids = self.queue_panel.selected_ids()
        targets = [self.projects[i] for i in ids] if ids else list(self.projects.values())
        self._download(targets)

    def _download(self, projects: list[VideoProject]) -> None:
        targets = [p for p in projects if p.url and not p.local_path and p.status in (Status.PENDING, Status.ERROR)]
        if not targets:
            self.log("Không có video nào cần tải.", "warn")
            return
        for project in targets:
            scraper = self.services.scraper_for(project.url)
            self._update(project, Status.DOWNLOADING, 0)
            self.runner.submit(
                scraper.download, project.url, DOWNLOAD_DIR,
                on_result=partial(self._on_downloaded, project),
                on_error=partial(self._download_failed, project),
                on_progress=lambda pct, _msg, p=project: self._update(p, progress=pct),
            )
        self.log(f"Bắt đầu tải {len(targets)} video…")

    def _download_failed(self, project: VideoProject, msg: str) -> None:
        self._update(project, Status.ERROR, error=msg)
        self.log(f"[{project.display_name}] Tải video lỗi: {msg}", "error")

    def _on_downloaded(self, project: VideoProject, video: ScrapedVideo) -> None:
        project.local_path = video.video_path
        project.title = video.title or project.title
        self._update(project, Status.READY, 100)
        self.log(f"Đã tải: {project.display_name}", "ok")
        if project is self.current:
            self.preview_panel.load(project.local_path)
            self._refresh()

    def _set_current(self, project_id: str | None) -> None:
        project = self.projects.get(project_id) if project_id else None
        if project is self.current and project is not None:
            return
        self.current = project
        self.preview_panel.load(project.local_path if project else None)
        self.preview_panel.canvas.set_regions(project.regions if project else [], notify=False)
        self.preview_panel.canvas.set_sub_style(self.workflow.translate.sub_style())
        self.editor.set_lines(project.subtitles if project else [])
        if project:
            self._open_first_pending(project)
        self._refresh()

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
        self._cookie = (info.summary() if path else "chưa gắn", info.logged_in, str(path) if path else "")
        self.settings_dialog.set_cookie_state(*self._cookie)
        self._refresh_header()
        if not path:
            return
        level = "ok" if info.logged_in else "warn"
        self.log(f"Đã gắn cookie từ {path.name}: {info.summary()}", level)
        if info.expired:
            self.log(f"Bỏ qua {len(info.expired)} cookie đã hết hạn: {', '.join(info.expired)}", "warn")

    def _on_pick_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.settings_dialog, "Chọn file cookie XHS",
                                              str(DEFAULT_COOKIE_FILE.parent), "Cookie (*.txt *.json);;Tất cả (*)")
        if path:
            self._use_cookie_file(Path(path))

    def _on_paste_cookie(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self.settings_dialog, "Dán cookie XHS",
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

    def _on_connect_uploader(self, uploader_id: str, switch_account: bool) -> None:
        uploader = self.services.uploaders[uploader_id]
        previous = self.settings_dialog.drive_account

        def done(name: str) -> None:
            self.settings_dialog.set_drive_account(name)
            self.log(f"Đã kết nối {uploader.name}: {name}", "ok")

        def failed(msg):
            self.settings_dialog.set_drive_account(previous)  # đổi tài khoản lỗi / huỷ -> vẫn giữ tài khoản cũ
            if "đã huỷ" in msg:
                self.log(f"Đã huỷ đăng nhập {uploader.name}.")
                return
            self.log(f"Kết nối {uploader.name} lỗi: {msg}", "error")
            QMessageBox.information(self.settings_dialog, uploader.name, msg)

        self.settings_dialog.set_drive_connecting()
        self.runner.submit(uploader.connect, switch_account=switch_account, on_result=done, on_error=failed)

    def _on_disconnect_uploader(self, uploader_id: str) -> None:
        uploader = self.services.uploaders[uploader_id]
        uploader.disconnect()
        self.settings_dialog.set_drive_account("")
        self.log(f"Đã ngắt kết nối {uploader.name}.")

    def _load_drive_account(self) -> None:
        """Mở app: hiện tài khoản Drive đã đăng nhập lần trước (không mở trình duyệt)."""
        uploader = self.services.uploaders[self.settings_dialog.uploader_id()]
        def done(name: str) -> None:
            if name and not self.settings_dialog.drive_account:  # người dùng chưa kết nối tay trong lúc chờ
                self.settings_dialog.set_drive_account(name)

        self.runner.submit(uploader.current_account, on_result=done,
                           on_error=lambda msg: self.log(f"Không kiểm tra được tài khoản {uploader.name}: {msg}", "warn"))

    # ------------------------------------------------------- mục tiêu, xem trước
    def _on_goal(self, goal: str) -> None:
        p = self.current
        if not p or p.goal == goal:
            return
        p.goal = goal
        self._settings.setValue("workflow/goal", goal)
        self._open_first_pending(p)
        self._touch(p)

    def _on_regions_changed(self) -> None:
        p = self.current
        if not p:
            return
        regions = self.preview_panel.canvas.regions()
        removed = [r for r in p.regions if not any(r is n for n in regions)]
        p.regions = regions
        dropped = self._drop_lines_of(p, removed)
        p.rev += 1
        if dropped:
            self.editor.set_lines(p.subtitles)
            self.log(f"[{p.display_name}] Xoá vùng che nhận nhầm -> bỏ khỏi bảng sub, không dịch / lồng tiếng: "
                     + " · ".join(dropped))
        self._touch(p)

    @staticmethod
    def _drop_lines_of(project: VideoProject, removed: list) -> list[str]:
        """Vùng che theo câu bị xoá (nhận nhầm) -> bỏ đúng dòng chữ của vùng đó khỏi sub gốc của câu cùng thời gian;
        câu không còn chữ nào thì xoá khỏi bảng sub. Trả về các dòng đã bỏ."""
        dropped = []
        for reg in removed:
            if reg.end_ms is None:  # vùng cố định (logo, watermark) / vùng tự thêm: không gắn với câu nào
                continue
            line = next((l for l in project.subtitles if l.start_ms == reg.start_ms and l.end_ms == reg.end_ms), None)
            if line is None:
                continue
            if reg.text:
                parts = line.original.split("\n")
                if reg.text not in parts:
                    continue
                parts.remove(reg.text)
                line.original = "\n".join(parts)
                dropped.append(reg.text)
            elif any(r.end_ms is not None and r.start_ms < line.end_ms and r.end_ms > line.start_ms
                     for r in project.regions):
                continue  # vùng cũ chưa có chữ: còn vùng khác che câu này -> giữ câu
            else:
                line.original = ""
                dropped.append(line.text or "(câu không còn vùng che)")
            if not line.original.strip():
                project.subtitles.remove(line)
                line.audio_path = None
        return dropped

    def _on_style(self) -> None:
        self.preview_panel.canvas.set_sub_style(self.workflow.translate.sub_style())
        if self.current and self.current.output_path:
            self.current.rev += 1  # kiểu chữ đổi -> video đã xuất của video đang chọn đã cũ
            self._touch(self.current)

    def _on_position(self, ms: int) -> None:
        if self._stop_at is not None and ms >= self._stop_at:
            self._stop_at = None
            self.preview_panel.player.pause()
        self.editor.highlight_at(ms)
        self.preview_panel.canvas.set_position(ms)
        self.preview_panel.canvas.set_overlay_text(self.editor.text_at(ms))

    # ------------------------------------------------------------ chạy các bước
    def _blocked(self, project: VideoProject, key: str) -> str:
        if not project.local_path:
            return f"[{project.display_name}] video chưa tải xong."
        if project.busy_step:
            return f"[{project.display_name}] đang {SHORT[project.busy_step].lower()}, đợi xong đã."
        if project.waiting_step:
            return f"[{project.display_name}] đang chờ {SHORT[project.waiting_step].lower()}."
        if key == TRANSLATE and not self.has_key:
            return "Chưa có Gemini API key: thêm trong Cài đặt."
        return ""

    def _run_manual(self, key: str, **kwargs) -> None:
        p = self.current
        if not p:
            return
        if key == TRANSLATE and not self.has_key:
            self._open_settings(keys=True)
            return
        if not self._confirm_redo(p, key, kwargs):
            return
        self._run_step(p, key, **kwargs)

    def _confirm_redo(self, project: VideoProject, key: str, kwargs: dict) -> bool:
        """Làm lại bước đã có kết quả: hỏi trước vì kết quả cũ sẽ bị thay. Đồng ý ở bước tìm sub = quét lại thật."""
        lines = project.subtitles
        n_text = sum(1 for l in lines if l.text.strip())
        n_voice = sum(1 for l in lines if l.audio_path)
        if key == DETECT and project.regions:
            msg = (f"Tìm lại sẽ quét lại video và thay toàn bộ {len(project.regions)} vùng che, "
                   f"{len(lines)} câu sub gốc hiện có")
            msg += f", kể cả {n_text} câu sub mới đã dịch / sửa." if n_text else "."
        elif key == TRANSLATE and n_text:
            msg = f"Dịch lại sẽ thay {n_text} câu sub mới hiện có, kể cả những câu bạn đã sửa tay."
            if n_voice:
                msg += " Câu nào đổi chữ sẽ mất giọng đọc và cần tạo lại giọng."
        elif key == VOICE and not kwargs.get("only_missing", True) and n_voice:
            msg = f"Tạo lại sẽ đọc lại toàn bộ {n_text} câu và thay {n_voice} đoạn giọng đọc hiện có."
        else:
            return True
        title = {DETECT: "Tìm lại sub?", TRANSLATE: "Dịch lại?", VOICE: "Tạo lại giọng đọc?"}[key]
        box = QMessageBox(QMessageBox.Question, title, msg + "\n\nBản trước đó sẽ bị mất. Bạn có muốn tiếp tục?",
                          parent=self)
        btn_yes = box.addButton({DETECT: "Tìm lại", TRANSLATE: "Dịch lại", VOICE: "Tạo lại"}[key],
                                QMessageBox.DestructiveRole)
        btn_no = box.addButton("Huỷ", QMessageBox.RejectRole)
        box.setDefaultButton(btn_no)
        box.exec()
        if box.clickedButton() is not btn_yes:
            return False
        if key == DETECT:
            kwargs["fresh"] = True
        return True

    def _run_step(self, project: VideoProject, key: str, then=None, failed=None, **kwargs) -> None:
        then = then or (lambda: None)
        failed = failed or (lambda: None)
        reason = self._blocked(project, key)
        if reason:
            self.log(reason, "warn")
            failed()
            return
        running = self._exclusive_running(key)
        if running:  # mỗi lúc chỉ 1 video tìm sub / lồng tiếng -> xếp hàng, video trước xong thì tự chạy
            project.waiting_step = key
            project.step_progress = (0, f"Đang chờ \"{running.display_name}\" {SHORT[key].lower()} xong…")
            self._waiting.append((project, key, then, failed, kwargs))
            self.log(f"[{project.display_name}] xếp hàng {SHORT[key].lower()}, chạy sau \"{running.display_name}\".")
            self._touch(project)
            return
        runner = {DETECT: self._detect, TRANSLATE: self._translate, VOICE: self._voice, EXPORT: self._export}[key]
        runner(project, then, failed, **kwargs)

    def _exclusive_running(self, key: str) -> VideoProject | None:
        """Tìm sub / lồng tiếng nặng máy: video khác đang chạy bước này thì trả về video đó."""
        if key not in (DETECT, VOICE):
            return None
        return next((p for p in self.projects.values() if p.busy_step == key), None)

    def _start_waiting(self, key: str) -> None:
        """Bước `key` vừa rảnh: chạy video đầu tiên đang xếp hàng chờ bước đó."""
        waiter = next((w for w in self._waiting if w[1] == key), None)
        if waiter is None or self._exclusive_running(key):
            return
        self._waiting.remove(waiter)
        project, _, then, failed, kwargs = waiter
        project.waiting_step = None
        self._run_step(project, key, then, failed, **kwargs)

    def _begin(self, project: VideoProject, key: str, msg: str, status: Status = Status.PROCESSING) -> None:
        project.busy_step = key
        project.step_errors.pop(key, None)
        project.step_progress = (0, msg)
        project.status = status
        self._touch(project)  # không tự mở bước khác: người dùng đang xem bước nào thì giữ nguyên

    def _progress(self, project: VideoProject):
        def report(pct: int, msg: str) -> None:
            project.step_progress = (pct, msg)
            self._touch(project)
        return report

    def _end(self, project: VideoProject, key: str, error: str = "") -> None:
        project.busy_step = None
        if error:
            project.step_errors[key] = error
            project.status, project.error = Status.ERROR, error
            self.log(f"[{project.display_name}] {SHORT[key]} lỗi: {error}", "error")
        else:
            project.status, project.error = (Status.DONE if key == EXPORT else Status.READY), ""
        self._touch(project)
        self._start_waiting(key)

    # ----- 1. tìm & che sub
    def _detect(self, project: VideoProject, then, failed, fresh: bool = False) -> None:
        """Quét video: vùng mờ theo từng câu sub + sub gốc (một lần quét cho cả hai).
        fresh: "Tìm lại" -> quét lại thật, thay toàn bộ vùng che và bảng sub cũ."""
        detector = next(iter(self.services.detectors.values()))
        source = next(iter(self.services.subtitle_sources.values()))
        if fresh:
            detector.forget(project.local_path)

        def job(progress):
            regions = detector.detect(project.local_path, progress)
            lines = source.generate(project.local_path, regions, 0)  # dùng lại kết quả quét, không quét lại
            return regions, lines

        def done(result):
            regions, lines = result
            project.regions = regions
            if fresh or not any(l.text.strip() for l in project.subtitles):  # lần đầu: không đè sub đã gõ
                project.subtitles[:] = lines
            project.rev += 1
            if project is self.current:
                self.preview_panel.canvas.set_regions(regions, notify=False)
                self.editor.set_lines(project.subtitles)
            self._end(project, DETECT)
            self.log(f"[{project.display_name}] Tìm thấy {len(lines)} câu sub, {len(regions)} vùng mờ.", "ok")
            then()

        def error(msg):
            self._end(project, DETECT, msg)
            failed()

        self._begin(project, DETECT, "Đang chuẩn bị…")
        self.log(f"[{project.display_name}] Đang tìm sub…")
        self.runner.submit(job, on_result=done, on_error=error, on_progress=self._progress(project))

    # ----- 2. dịch
    def _translate_settings(self) -> TranslateSettings:
        s = TranslateSettings()
        self.settings_dialog.apply_to(s)
        self.workflow.translate.apply_to(s)
        return s

    def _translate(self, project: VideoProject, then, failed, indices: list[int] | None = None) -> None:
        lines = [l for i, l in enumerate(project.subtitles)
                 if l.original.strip() and (indices is None or i in indices)]
        if not lines:
            self.log("Chưa có sub gốc để dịch.", "warn")
            failed()
            return
        settings = self._translate_settings()
        translator = self.services.translators[settings.provider]

        def done(texts):
            for line, text in zip(lines, texts):
                if line.text != text:
                    line.audio_path = None  # giọng cũ đọc nội dung cũ -> bỏ, tạo lại theo bản dịch
                line.text = text
            project.rev += 1
            if project is self.current:
                self.editor.set_lines(project.subtitles)
            self._end(project, TRANSLATE)
            self.log(f"[{project.display_name}] Đã dịch {len(texts)} câu sub.", "ok")
            then()

        def error(msg):
            self._end(project, TRANSLATE, msg)
            failed()

        self._begin(project, TRANSLATE, "Đang dịch…")
        self.log(f"[{project.display_name}] Đang dịch {len(lines)} câu bằng {translator.name} "
                 f"({settings.source_lang} → {settings.target_lang}, {settings.model})…")
        self.runner.submit(translator.translate, lines, project.display_name, settings,
                           on_result=done, on_error=error, on_progress=self._progress(project))

    def _translate_lines(self, indices: list[int]) -> None:
        if self.current:
            self._run_step(self.current, TRANSLATE, indices=indices)

    def _shorten_line(self, index: int) -> None:
        project = self.current
        if not project or index >= len(project.subtitles):
            return
        reason = self._blocked(project, TRANSLATE)
        if reason:
            self.log(reason, "warn")
            return
        line = project.subtitles[index]
        translator = self.services.translators[self._translate_settings().provider]

        def done(result: dict[int, str]):
            text = result.get(index)
            if text and line in project.subtitles:
                line.text, line.audio_path = text, None
                project.rev += 1
                self.log(f"[{project.display_name}] Đã rút gọn câu {index + 1}: {text}", "ok")
            else:
                self.log(f"Câu {index + 1} không rút gọn thêm được.", "warn")
            self._end(project, TRANSLATE)
            if project is self.current:
                self.editor.set_lines(project.subtitles)

        self._begin(project, TRANSLATE, f"Đang rút gọn câu {index + 1}…")
        self.runner.submit(translator.shorten, list(project.subtitles), [index], self._translate_settings(),
                           on_result=done, on_error=lambda msg: self._end(project, TRANSLATE, msg),
                           on_progress=self._progress(project))

    # ----- 3. giọng đọc
    def _voice(self, project: VideoProject, then, failed, only_missing: bool = True) -> None:
        targets = [(l, l.text) for l in project.subtitles
                   if l.text.strip() and not (only_missing and l.audio_path)]
        if not targets:
            if any(l.audio_path for l in project.subtitles):
                then()  # mọi câu đã có giọng
            else:
                self.log("Chưa có sub mới để lồng tiếng.", "warn")
                failed()
            return
        settings = self.workflow.voice.settings()
        provider = self.services.tts[settings.provider]
        out_dir = TTS_CACHE_DIR / project.id

        def job(progress):
            paths = []
            for n, (_, text) in enumerate(targets):
                progress(int(n / len(targets) * 100), f"Đang đọc câu {n + 1}/{len(targets)}")
                # tên file theo nội dung + giọng: không đè audio của câu khác khi câu bị thêm / tách / gộp
                key = hashlib.sha1(f"{settings}|{text}".encode("utf-8")).hexdigest()[:12]
                paths.append(provider.synthesize(text, settings, out_dir / f"line_{key}.wav"))
            return paths

        def done(paths):
            for (line, text), path in zip(targets, paths):
                if line.text == text:  # bỏ qua câu bị sửa trong lúc đang tạo giọng
                    line.audio_path = path
            project.rev += 1
            if project is self.current:
                self.editor.set_lines(project.subtitles)
            self._end(project, VOICE)
            self.log(f"[{project.display_name}] Đã tạo {len(paths)} đoạn lồng tiếng ({settings.voice_id}).", "ok")
            then()

        def error(msg):
            self._end(project, VOICE, msg)
            failed()

        self._begin(project, VOICE, "Đang tạo giọng đọc…")
        self.runner.submit(job, on_result=done, on_error=error, on_progress=self._progress(project))

    # ----- 4. xuất + upload
    def _export_settings(self, project: VideoProject) -> ExportSettings:
        e = self.workflow.export
        s = self.settings_dialog
        add_voice = project.goal == "dub" and any(l.audio_path for l in project.subtitles)
        return ExportSettings(
            output_dir=e.output_dir(),
            renderer_id=next(iter(self.services.renderers)),
            resolution=e.resolution(),
            apply_blur=bool(project.regions),
            burn_subs=project.goal != "blur" and any(l.text.strip() for l in project.subtitles),
            add_voice=add_voice,
            # chỉ bỏ tiếng gốc khi có giọng AI thay vào (không thì video mất tiếng)
            keep_original_audio=not (add_voice and not self.workflow.voice.keep_background()),
            original_volume=self.workflow.voice.original_volume(),
            uploader_id=s.uploader_id(),
            drive_folder=s.drive_folder(),
            auto_upload=e.auto_upload(),
        )

    def _on_export_clicked(self) -> None:
        p = self.current
        if not p:
            return
        n_stale = stale_voice_count(p)
        if p.goal == "dub" and n_stale:
            box = QMessageBox(QMessageBox.Warning, "Giọng đọc chưa cập nhật",
                              f"{n_stale} câu sub đã sửa nhưng chưa có giọng đọc — "
                              "những câu này sẽ bị câm trong video.", parent=self)
            btn_voice = box.addButton("Tạo giọng rồi xuất", QMessageBox.AcceptRole)
            box.addButton("Vẫn xuất", QMessageBox.DestructiveRole)
            box.addButton("Huỷ", QMessageBox.RejectRole)
            box.setDefaultButton(btn_voice)
            box.exec()
            role = box.buttonRole(box.clickedButton())
            if role == QMessageBox.AcceptRole:
                self._run_step(p, VOICE, then=lambda: self._run_step(p, EXPORT))
                return
            if role != QMessageBox.DestructiveRole:
                return
        self._run_step(p, EXPORT)

    def _export(self, project: VideoProject, then, failed) -> None:
        export = self._export_settings(project)
        ctx = RenderContext(style=self.workflow.translate.sub_style(), voice=self.workflow.voice.settings(),
                            export=export)
        renderer = self.services.renderers[export.renderer_id]
        safe = re.sub(r'[\\/:*?"<>|]+', "_", project.display_name)[:60]
        out_path = export.output_dir / f"{safe}_{project.id}{OUTPUT_SUFFIX[project.goal]}.mp4"
        rev = project.rev

        def done(path: Path):
            project.output_path = path
            project.exported_rev = rev
            project.drive_link = ""
            self.log(f"[{project.display_name}] Render xong: {path}", "ok")
            if export.auto_upload:
                self._upload(project, export, then, failed)
            else:
                self._end(project, EXPORT)
                then()

        def error(msg):
            self._end(project, EXPORT, msg)
            failed()

        n_stale = stale_voice_count(project)
        if export.add_voice and n_stale:
            self.log(f"[{project.display_name}] {n_stale} câu sub đã sửa chưa có giọng đọc — sẽ bị câm.", "warn")
        self._begin(project, EXPORT, "Đang render…", Status.RENDERING)
        self.log(f"[{project.display_name}] Bắt đầu render ({renderer.name})…")
        self.runner.submit(renderer.render, project, ctx, out_path,
                           on_result=done, on_error=error, on_progress=self._progress(project))

    def _upload(self, project: VideoProject, export: ExportSettings, then, failed) -> None:
        uploader = self.services.uploaders[export.uploader_id]

        def done(link: str):
            project.drive_link = link
            self.log(f"[{project.display_name}] Upload xong: {link}", "ok")
            self._end(project, EXPORT)
            then()

        def error(msg):
            self._end(project, EXPORT, f"upload lỗi: {msg}")
            failed()

        project.status = Status.UPLOADING
        project.step_progress = (0, "Đang tải lên…")
        self._touch(project)
        self.runner.submit(uploader.upload, project.output_path, export.drive_folder,
                           on_result=done, on_error=error, on_progress=self._progress(project))

    # ----- nghe thử giọng AI trên khung xem trước
    def _listen_key(self, project: VideoProject | None):
        v = self.workflow.voice
        return (project.id, project.rev, v.keep_background(), v.original_volume()) if project else None

    def _on_listen(self) -> None:
        p = self.current
        if not p or not p.local_path:
            return
        key = self._listen_key(p)
        if key == self._dub_key and self.preview_panel.dub_path:  # chưa đổi gì -> phát lại tiếng đã ghép
            self._play_dub()
            return
        export = self._export_settings(p)
        export.add_voice = True
        ctx = RenderContext(style=self.workflow.translate.sub_style(), voice=self.workflow.voice.settings(),
                            export=export)
        renderer = self.services.renderers[export.renderer_id]
        out = TTS_CACHE_DIR / p.id / f"nghe_thu_{p.rev}.m4a"

        def done(path: Path):
            self.workflow.voice.set_listen_busy(False)
            if p is not self.current:
                return
            self._dub_key = key
            self.preview_panel.set_dub_audio(path)
            self._play_dub()

        def failed(msg: str):
            self.workflow.voice.set_listen_busy(False)
            self.log(f"[{p.display_name}] Nghe thử lỗi: {msg}", "error")

        self.workflow.voice.set_listen_busy(True)
        self.runner.submit(renderer.render_audio, p, ctx, out, on_result=done, on_error=failed)

    def _play_dub(self) -> None:
        """Phát từ câu có giọng đầu tiên, ở chế độ Kết quả (vùng che + sub mới + giọng AI)."""
        p = self.current
        first = min((l.start_ms for l in p.subtitles if l.audio_path), default=0)
        self.preview_panel.show_result()
        self.preview_panel.seek(max(0, first - 500))
        self.preview_panel.player.play()
        self.log(f"[{p.display_name}] Đang phát thử với giọng AI. Chuyển sang Bản gốc để nghe tiếng gốc.")

    # ------------------------------------------------------------ làm tự động
    def _on_auto(self) -> None:
        if self._auto_running:  # nút đang là "Dừng sau bước đang chạy"
            self._auto_queue.clear()
            self._auto_stopped = True
            self.log("Sẽ dừng sau bước đang chạy.", "warn")
            self._refresh()
            return
        if self.current:
            self._auto_start([self.current])

    def _on_auto_all(self) -> None:
        if not self.current:
            return
        goal = self.current.goal
        projects = [p for p in self.projects.values() if p.local_path and not p.busy_step and not p.waiting_step]
        for p in projects:
            p.goal = goal
        self._auto_start(projects)

    def _auto_start(self, projects: list[VideoProject]) -> None:
        has_key = self.has_key
        queue = []
        for p in projects:
            steps = pending_steps(p, has_key)
            if TRANSLATE in steps and not has_key:
                self.log("Cần Gemini API key để dịch: thêm trong Cài đặt rồi bấm lại.", "warn")
                self._open_settings(keys=True)
                return
            queue += [(p, k) for k in steps]
        if not queue:
            self.log("Không còn bước nào cần làm.", "warn")
            return
        self._auto_queue = queue
        self._auto_running = True
        self._auto_stopped = False
        self.log(f"Làm tự động {len(queue)} bước cho {len(projects)} video…")
        self._auto_next()

    def _auto_next(self) -> None:
        if not self._auto_queue:
            if self._auto_running:
                self._auto_running = False
                self.log("Đã dừng làm tự động." if self._auto_stopped else "Làm tự động xong.",
                         "warn" if self._auto_stopped else "ok")
            for p in self.projects.values():
                self._touch(p)
            return
        project, key = self._auto_queue.pop(0)
        if step_info(project, key, self.has_key).done:
            self._auto_next()
            return
        self._run_step(project, key, then=self._auto_next, failed=partial(self._auto_skip, project))

    def _auto_skip(self, project: VideoProject) -> None:
        """Một bước lỗi: bỏ các bước còn lại của video đó, làm tiếp video khác."""
        self._auto_queue = [(q, k) for q, k in self._auto_queue if q is not project]
        self._auto_next()

    # ------------------------------------------------------------- sửa sub
    def _open_editor(self) -> None:
        p = self.current
        if not p:
            return
        self._split_sizes = self.main_split.sizes()
        self.editor.set_title(p.display_name)
        self.editor.set_lines(p.subtitles)
        self.editor.set_busy(p.busy_step == TRANSLATE)
        self.editor.attach_preview(self.preview_panel)
        self.stack.setCurrentWidget(self.editor)

    def _close_editor(self) -> None:
        self._stop_at = None
        self.main_split.insertWidget(1, self.preview_panel)
        self.main_split.setSizes(self._split_sizes)
        self.stack.setCurrentWidget(self.main_page)
        self._refresh()

    def _play_line(self, index: int) -> None:
        p = self.current
        if p and 0 <= index < len(p.subtitles):
            line = p.subtitles[index]
            self.preview_panel.seek(line.start_ms)
            self._stop_at = line.end_ms
            self.preview_panel.player.play()

    def _on_lines_edited(self) -> None:
        p = self.current
        if p:
            p.rev += 1
            self.preview_panel.canvas.set_overlay_text(self.editor.text_at(self.preview_panel.position_ms))
            self._touch(p)

    # ---------------------------------------------------------------- đóng app
    def closeEvent(self, event) -> None:
        self.settings_dialog.save_settings(self._settings)
        self.workflow.translate.save_settings(self._settings)
        self.workflow.voice.save_settings(self._settings)
        self.workflow.export.save_settings(self._settings)
        self.preview_panel.player.stop()
        self.runner.shutdown()
        super().closeEvent(event)

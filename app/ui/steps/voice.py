from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from app.models import VoiceInfo, VoiceSettings
from app.services.tts.base import SAMPLE_TEXT, TTSProvider
from app.ui.steps.base import StepBody
from app.ui.tasks import TaskRunner
from app.ui.widgets.common import LabeledSlider, TaskProgress, ghost, muted_label


class VoiceBody(StepBody):
    """Bước lồng tiếng: chọn giọng, nghe thử, tạo giọng đọc cho từng câu sub mới."""
    run_requested = Signal(bool)  # True = chỉ tạo cho câu chưa có giọng
    listen_requested = Signal()   # nghe cả video với giọng AI trên khung xem trước

    def __init__(self, providers: dict[str, TTSProvider], runner: TaskRunner, log, parent=None):
        super().__init__("Tạo giọng đọc", parent)
        self._providers = providers
        self._runner = runner
        self._log = log
        self._voices: list[VoiceInfo] = []
        self._selected_id = VoiceSettings().voice_id
        self._warmed: set[str] = set()  # provider đã nạp sẵn mô hình
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)

        # giọng đang chọn
        current = QFrame()
        current.setObjectName("SubBox")
        row = QHBoxLayout(current)
        row.setContentsMargins(14, 12, 14, 12)
        self.avatar = QLabel()
        self.avatar.setObjectName("Avatar")
        self.avatar.setFixedSize(36, 36)
        self.avatar.setAlignment(Qt.AlignCenter)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.voice_name = QLabel()
        self.voice_name.setObjectName("StepTitle")
        self.voice_meta = muted_label()
        names.addWidget(self.voice_name)
        names.addWidget(self.voice_meta)
        self.btn_preview = QPushButton("▶")
        self.btn_preview.setObjectName("IconButton")
        self.btn_preview.setToolTip("Nghe thử giọng")
        self.btn_pick = QPushButton("Đổi giọng")
        self.btn_pick.setCheckable(True)
        row.addWidget(self.avatar)
        row.addLayout(names, 1)
        row.addWidget(self.btn_preview)
        row.addWidget(self.btn_pick)
        self.top.addWidget(current)

        # danh sách giọng (mở bằng "Đổi giọng")
        self.picker = QFrame()
        self.picker.setObjectName("SubBox")
        pv = QVBoxLayout(self.picker)
        pv.setContentsMargins(14, 14, 14, 14)
        self.provider_combo = QComboBox()
        for p in providers.values():
            self.provider_combo.addItem(p.name, p.id)
        self.provider_combo.setVisible(len(providers) > 1)  # chỉ hiện khi có nhiều nguồn giọng
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Tìm giọng…")
        self.btn_reload = ghost(QPushButton("Tải lại"))
        search_row = QHBoxLayout()
        search_row.addWidget(self.provider_combo)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.btn_reload)
        self.voice_list = QListWidget()
        self.voice_list.setFixedHeight(200)
        self.voice_list.setToolTip("Double-click để nghe thử")
        self.btn_clone = ghost(QPushButton("+ Tạo giọng riêng từ file ghi âm (3–8 giây)…"))
        self.btn_remove_voice = ghost(QPushButton("Xoá giọng này"))
        self.btn_remove_voice.setVisible(False)
        clone_row = QVBoxLayout()  # 2 dòng: cột phải hẹp
        clone_row.setSpacing(2)
        clone_row.addWidget(self.btn_clone, 0, Qt.AlignLeft)
        clone_row.addWidget(self.btn_remove_voice, 0, Qt.AlignLeft)
        pv.addLayout(search_row)
        pv.addWidget(self.voice_list)
        pv.addLayout(clone_row)
        self.clone_progress = TaskProgress()
        pv.addWidget(self.clone_progress)
        self.picker.setVisible(False)
        self.top.addWidget(self.picker)

        # nghe thử: có ở cả lúc xong lẫn lúc còn vài câu đã sửa chưa tạo lại giọng
        self.btn_listen = QPushButton("▶  Nghe thử")
        self.btn_listen_idle = QPushButton("▶  Nghe thử")
        for b in (self.btn_listen, self.btn_listen_idle):
            b.setToolTip("Phát video trên khung xem trước với giọng AI và nhạc nền, như lúc xuất")
            b.clicked.connect(self.listen_requested)
        self.btn_redo = QPushButton("Tạo lại")
        self.btn_redo.setToolTip("Tạo lại giọng cho mọi câu (vd. sau khi đổi giọng / tốc độ)")
        self.done_row.addWidget(self.btn_listen)
        self.done_row.addWidget(self.btn_redo)
        self.idle_row.addWidget(self.btn_listen_idle)

        tune = QWidget()
        form = QFormLayout(tune)
        form.setContentsMargins(0, 0, 0, 0)
        self.rate = LabeledSlider(-50, 100, 0, "%")
        self.pitch = LabeledSlider(-12, 12, 0, "")
        self.volume = LabeledSlider(-50, 50, 0, "%")
        self.orig_volume = LabeledSlider(0, 100, 20, "%")
        self.orig_volume.setToolTip("Âm lượng tiếng gốc (nhạc nền) khi ghép giọng AI; lúc giọng AI đọc thì tiếng gốc tắt hẳn")
        self.bg_check = QCheckBox("Giữ nhạc nền gốc")
        self.bg_check.setToolTip("Tắt: video xuất ra chỉ còn giọng AI, bỏ hẳn tiếng gốc")
        self.bg_check.setChecked(True)
        bg_row = QHBoxLayout()
        bg_row.addWidget(self.bg_check)
        bg_row.addWidget(self.orig_volume, 1)  # chỉ hiện khi bật
        self.bg_check.toggled.connect(self.orig_volume.setVisible)
        form.addRow("Tốc độ", self.rate)
        form.addRow("Cao độ", self.pitch)
        form.addRow("Âm lượng giọng", self.volume)
        form.addRow("Nhạc nền", bg_row)
        self.add_advanced("Tốc độ, cao độ, âm lượng", tune)

        self.btn_run.clicked.connect(lambda: self.run_requested.emit(True))
        self.btn_redo.clicked.connect(lambda: self.run_requested.emit(False))
        self.btn_pick.toggled.connect(self.picker.setVisible)
        self.btn_preview.clicked.connect(self.preview)
        self.btn_reload.clicked.connect(lambda: self.reload(force=True))
        self.provider_combo.currentIndexChanged.connect(lambda _: self.reload())
        self.search_edit.textChanged.connect(lambda _: self._apply_filter())
        self.voice_list.itemClicked.connect(self._on_pick)
        self.voice_list.itemDoubleClicked.connect(lambda item: (self._on_pick(item), self.preview()))
        self.btn_clone.clicked.connect(self.clone_voice)
        self.btn_remove_voice.clicked.connect(self.remove_voice)

        self._update_current()
        QTimer.singleShot(200, self.reload)

    @property
    def provider(self) -> TTSProvider:
        return self._providers[self.provider_combo.currentData()]

    def settings(self) -> VoiceSettings:
        return VoiceSettings(
            provider=self.provider.id,
            voice_id=self._selected_id,
            rate=self.rate.value(),
            pitch=self.pitch.value(),
            volume=self.volume.value(),
        )

    def set_listen_busy(self, busy: bool) -> None:
        for b in (self.btn_listen, self.btn_listen_idle):
            b.setEnabled(not busy)
            b.setText("Đang ghép giọng…" if busy else "▶  Nghe thử")

    def original_volume(self) -> int:
        return self.orig_volume.value()

    def keep_background(self) -> bool:
        return self.bg_check.isChecked()

    def set_state(self, can_run: bool, n_lines: int, n_done: int, n_missing: int) -> None:
        """n_missing: câu có sub mới nhưng chưa có giọng (lúc đã có giọng cho câu khác = câu vừa sửa)."""
        self.btn_run.setEnabled(can_run and n_lines > 0)
        self.btn_redo.setEnabled(can_run and n_lines > 0)
        self.btn_listen_idle.setVisible(n_done > 0)
        if n_done and n_missing:
            self.btn_run.setText(f"Tạo giọng cho {n_missing} câu đã sửa")
        else:
            self.btn_run.setText(f"Tạo giọng đọc ({n_lines} câu)" if n_lines else "Tạo giọng đọc")
        self.summary.setText(f"Đã có giọng đọc cho {n_done} câu.")

    # ----- danh sách giọng -----
    def reload(self, force: bool = False) -> None:
        self.btn_clone.setVisible(self.provider.supports_clone)
        self.btn_reload.setEnabled(False)
        self._runner.submit(self.provider.list_voices, force, on_result=self._on_voices, on_error=self._on_voices_error)

    def _on_voices(self, voices: list[VoiceInfo]) -> None:
        self.btn_reload.setEnabled(True)
        self._voices = voices
        if voices and self._selected_id not in {v.id for v in voices}:  # giọng đã lưu không còn
            default = VoiceSettings().voice_id
            self._selected_id = default if any(v.id == default for v in voices) else voices[0].id
        self._apply_filter()
        self._update_current()
        self._log(f"Đã tải {len(voices)} giọng từ {self.provider.name}")
        provider = self.provider
        if provider.id not in self._warmed:  # nạp mô hình ở nền: nghe thử / lồng tiếng không phải chờ
            self._warmed.add(provider.id)
            self._runner.submit(provider.warm_up,
                                on_result=lambda _: self._log(f"Đã nạp sẵn mô hình {provider.name}"),
                                on_error=lambda m: self._log(f"Nạp mô hình giọng lỗi: {m}", "warn"))

    def _on_voices_error(self, msg: str) -> None:
        self.btn_reload.setEnabled(True)
        self._log(f"Lỗi tải giọng: {msg}", "error")

    def _apply_filter(self) -> None:
        query = self.search_edit.text().strip().lower()
        self.voice_list.clear()
        for v in self._voices:
            meta = " · ".join(x for x in (v.gender, v.locale) if x)
            if query and query not in f"{v.name} {meta}".lower():
                continue
            item = QListWidgetItem(f"{v.name}   ·  {meta}" if meta else v.name)
            item.setData(Qt.UserRole, v.id)
            self.voice_list.addItem(item)
            if v.id == self._selected_id:
                self.voice_list.setCurrentItem(item)

    def _on_pick(self, item: QListWidgetItem) -> None:
        self._selected_id = item.data(Qt.UserRole)
        self._update_current()

    def _update_current(self) -> None:
        voice = next((v for v in self._voices if v.id == self._selected_id), None)
        name = voice.name if voice else self._selected_id
        self.voice_name.setText(name)
        self.voice_meta.setText(" · ".join(x for x in (voice.gender, voice.locale) if x) if voice else "")
        self.avatar.setText(name[:1].upper())
        self.btn_remove_voice.setVisible(bool(voice and voice.custom))

    # ----- nghe thử -----
    def preview(self) -> None:
        text = SAMPLE_TEXT  # câu mẫu cố định: có sẵn audio cho các giọng dựng sẵn -> nghe ngay
        settings = self.settings()
        ready = self.provider.cached_preview(text, settings)
        if ready:  # câu mẫu đã tạo sẵn -> phát ngay
            self.play(ready)
            return
        self.btn_preview.setEnabled(False)
        self.btn_preview.setText("…")
        self._runner.submit(self.provider.preview, text, settings,
                            on_result=self.play, on_error=self._on_preview_error)

    def play(self, path) -> None:
        self._reset_preview_button()
        self._player.stop()
        self._player.setSource(QUrl())
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def _on_preview_error(self, msg: str) -> None:
        self._reset_preview_button()
        self._log(f"Lỗi nghe thử: {msg}", "error")

    def _reset_preview_button(self) -> None:
        self.btn_preview.setEnabled(True)
        self.btn_preview.setText("▶")

    # ----- clone giọng -----
    def clone_voice(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn giọng mẫu", "",
            "Audio / video (*.wav *.mp3 *.m4a *.flac *.ogg *.aac *.mp4 *.mov *.mkv *.webm);;Tất cả (*.*)")
        if not path:
            return
        name, ok = QInputDialog.getText(self, "Tạo giọng riêng", "Tên giọng mới:", text=Path(path).stem)
        if not ok or not name.strip():
            return
        self.btn_clone.setEnabled(False)
        self.clone_progress.update(0, "Đang tạo giọng riêng…")

        def done(voice: VoiceInfo) -> None:
            self.btn_clone.setEnabled(True)
            self.clone_progress.finish()
            self._selected_id = voice.id
            self._log(f"Đã tạo giọng \"{voice.id}\" từ {Path(path).name}", "ok")
            self.reload()
            self.preview()

        def failed(msg: str) -> None:
            self.btn_clone.setEnabled(True)
            self.clone_progress.finish(f"Lỗi: {msg}")
            self._log(f"Tạo giọng riêng lỗi: {msg}", "error")

        self._runner.submit(self.provider.clone_voice, name.strip(), Path(path), on_result=done, on_error=failed,
                            on_progress=self.clone_progress.update)

    def remove_voice(self) -> None:
        voice_id = self._selected_id
        self.provider.remove_voice(voice_id)
        self._log(f"Đã xoá giọng \"{voice_id}\"")
        self._selected_id = VoiceSettings().voice_id
        self.reload()

    # ----- lưu cài đặt -----
    def save_settings(self, qs: QSettings) -> None:
        s = self.settings()
        qs.setValue("voice/provider", s.provider)
        qs.setValue("voice/id", s.voice_id)
        qs.setValue("voice/rate", s.rate)
        qs.setValue("voice/pitch", s.pitch)
        qs.setValue("voice/volume", s.volume)
        qs.setValue("export/original_volume", self.orig_volume.value())
        qs.setValue("export/keep_background", self.bg_check.isChecked())

    def load_settings(self, qs: QSettings) -> None:
        idx = self.provider_combo.findData(qs.value("voice/provider", "vieneu"))
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self._selected_id = qs.value("voice/id", self._selected_id)
        self.rate.set_value(int(qs.value("voice/rate", 0)))
        self.pitch.set_value(int(qs.value("voice/pitch", 0)))
        self.volume.set_value(int(qs.value("voice/volume", 0)))
        self.orig_volume.set_value(int(qs.value("export/original_volume", 20)))
        self.bg_check.setChecked(qs.value("export/keep_background", True, type=bool))
        self._update_current()

import hashlib

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.config import TTS_CACHE_DIR
from app.models import VoiceInfo, VoiceSettings
from app.services.tts.base import TTSProvider
from app.ui.tasks import TaskRunner
from app.ui.theme import accent
from app.ui.widgets.common import LabeledSlider, muted_label

LOCALE_NAMES = {
    "vi-VN": "Tiếng Việt",
    "zh-CN": "Tiếng Trung (Phổ thông)",
    "zh-TW": "Tiếng Trung (Đài Loan)",
    "zh-HK": "Tiếng Quảng Đông",
    "en-US": "Tiếng Anh (Mỹ)",
    "en-GB": "Tiếng Anh (Anh)",
    "ja-JP": "Tiếng Nhật",
    "ko-KR": "Tiếng Hàn",
    "th-TH": "Tiếng Thái",
}
ALL = "__all__"


class VoicePanel(QWidget):
    """Tab Giọng đọc: danh sách voice AI, nghe thử, tạo lồng tiếng."""
    generate_dub_requested = Signal()

    def __init__(self, providers: dict[str, TTSProvider], runner: TaskRunner, log, parent=None):
        super().__init__(parent)
        self._providers = providers
        self._runner = runner
        self._log = log
        self._voices: list[VoiceInfo] = []
        self._selected_id = VoiceSettings().voice_id

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        row = QHBoxLayout()
        self.provider_combo = QComboBox()
        for p in providers.values():
            self.provider_combo.addItem(p.name, p.id)
        self.btn_reload = QPushButton("Tải lại")
        row.addWidget(self.provider_combo, 1)
        row.addWidget(self.btn_reload)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.lang_combo = QComboBox()
        self.gender_combo = QComboBox()
        self.gender_combo.addItem("Tất cả", ALL)
        self.gender_combo.addItem("Nữ", "Nữ")
        self.gender_combo.addItem("Nam", "Nam")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Tìm giọng…")
        row.addWidget(self.lang_combo, 2)
        row.addWidget(self.gender_combo, 1)
        row.addWidget(self.search_edit, 2)
        layout.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Giọng", "Ngôn ngữ", "Giới tính"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.status_label = muted_label("Đang tải danh sách giọng…")
        layout.addWidget(self.status_label)

        tune = QGroupBox("Tuỳ chỉnh giọng")
        form = QFormLayout(tune)
        self.rate = LabeledSlider(-50, 100, 0, "%")
        self.pitch = LabeledSlider(-50, 50, 0, "Hz")
        self.volume = LabeledSlider(-50, 50, 0, "%")
        form.addRow("Tốc độ", self.rate)
        form.addRow("Cao độ", self.pitch)
        form.addRow("Âm lượng", self.volume)
        layout.addWidget(tune)

        listen = QGroupBox("Nghe thử")
        lv = QVBoxLayout(listen)
        self.sample_edit = QLineEdit("Xin chào, đây là giọng đọc thử cho video của bạn.")
        row = QHBoxLayout()
        self.selected_label = muted_label()
        self.btn_preview = accent(QPushButton("▶  Nghe thử"))
        row.addWidget(self.selected_label, 1)
        row.addWidget(self.btn_preview)
        lv.addWidget(self.sample_edit)
        lv.addLayout(row)
        layout.addWidget(listen)

        self.btn_dub = QPushButton("Tạo audio lồng tiếng cho toàn bộ sub")
        layout.addWidget(self.btn_dub)

        self.btn_reload.clicked.connect(lambda: self.reload(force=True))
        self.provider_combo.currentIndexChanged.connect(lambda _: self.reload())
        self.lang_combo.currentIndexChanged.connect(lambda _: self._apply_filter())
        self.gender_combo.currentIndexChanged.connect(lambda _: self._apply_filter())
        self.search_edit.textChanged.connect(lambda _: self._apply_filter())
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellDoubleClicked.connect(lambda *_: self.preview())
        self.btn_preview.clicked.connect(self.preview)
        self.btn_dub.clicked.connect(self.generate_dub_requested)

        self._update_selected_label()
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

    # ----- danh sách giọng -----
    def reload(self, force: bool = False) -> None:
        self.status_label.setText("Đang tải danh sách giọng…")
        self.btn_reload.setEnabled(False)
        self._runner.submit(self.provider.list_voices, force, on_result=self._on_voices, on_error=self._on_voices_error)

    def _on_voices(self, voices: list[VoiceInfo]) -> None:
        self.btn_reload.setEnabled(True)
        self._voices = voices
        locales = sorted({v.locale for v in voices})
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        self.lang_combo.addItem("Tất cả ngôn ngữ", ALL)
        for loc in locales:
            self.lang_combo.addItem(f"{LOCALE_NAMES.get(loc, loc)} ({loc})", loc)
        current = self._selected_id[:5]
        idx = self.lang_combo.findData(current if current in locales else "vi-VN")
        self.lang_combo.setCurrentIndex(max(idx, 0))
        self.lang_combo.blockSignals(False)
        self._apply_filter()
        self._log(f"Đã tải {len(voices)} giọng từ {self.provider.name}")

    def _on_voices_error(self, msg: str) -> None:
        self.btn_reload.setEnabled(True)
        self.status_label.setText("Không tải được danh sách giọng (cần Internet)")
        self._log(f"Lỗi tải giọng: {msg}", "error")

    def _apply_filter(self) -> None:
        lang = self.lang_combo.currentData()
        gender = self.gender_combo.currentData()
        query = self.search_edit.text().strip().lower()
        shown = [
            v for v in self._voices
            if (lang in (None, ALL) or v.locale == lang)
            and (gender == ALL or v.gender == gender)
            and (not query or query in v.id.lower())
        ]
        self.table.blockSignals(True)
        self.table.setRowCount(len(shown))
        select_row = -1
        for r, v in enumerate(shown):
            name = QTableWidgetItem(v.name)
            name.setData(Qt.UserRole, v.id)
            name.setToolTip(v.id)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(v.locale))
            self.table.setItem(r, 2, QTableWidgetItem(v.gender))
            if v.id == self._selected_id:
                select_row = r
        self.table.blockSignals(False)
        if select_row >= 0:
            self.table.selectRow(select_row)
        self.status_label.setText(f"{len(shown)} / {len(self._voices)} giọng · double-click để nghe thử")

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if items:
            self._selected_id = self.table.item(items[0].row(), 0).data(Qt.UserRole)
            self._update_selected_label()

    def _update_selected_label(self) -> None:
        self.selected_label.setText(f"Đang chọn: {self._selected_id}")

    # ----- nghe thử -----
    def preview(self) -> None:
        text = self.sample_edit.text().strip()
        if not text:
            return
        settings = self.settings()
        key = hashlib.sha1(f"{settings}|{text}".encode()).hexdigest()[:16]
        out = TTS_CACHE_DIR / "preview" / f"{key}.mp3"
        if out.exists():
            self._play(out)
            return
        self.btn_preview.setEnabled(False)
        self.btn_preview.setText("Đang tạo…")
        self._runner.submit(self.provider.synthesize, text, settings, out,
                            on_result=self._play, on_error=self._on_preview_error)

    def _play(self, path) -> None:
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
        self.btn_preview.setText("▶  Nghe thử")

    # ----- lưu cài đặt -----
    def save_settings(self, qs: QSettings) -> None:
        s = self.settings()
        qs.setValue("voice/provider", s.provider)
        qs.setValue("voice/id", s.voice_id)
        qs.setValue("voice/rate", s.rate)
        qs.setValue("voice/pitch", s.pitch)
        qs.setValue("voice/volume", s.volume)
        qs.setValue("voice/sample", self.sample_edit.text())

    def load_settings(self, qs: QSettings) -> None:
        idx = self.provider_combo.findData(qs.value("voice/provider", "edge"))
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self._selected_id = qs.value("voice/id", self._selected_id)
        self.rate.set_value(int(qs.value("voice/rate", 0)))
        self.pitch.set_value(int(qs.value("voice/pitch", 0)))
        self.volume.set_value(int(qs.value("voice/volume", 0)))
        self.sample_edit.setText(qs.value("voice/sample", self.sample_edit.text()))
        self._update_selected_label()

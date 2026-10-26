from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.config import OUTPUT_DIR
from app.models import ExportSettings
from app.services.render.base import Renderer
from app.services.upload.base import Uploader
from app.ui.theme import accent
from app.ui.widgets.common import LabeledSlider, muted_label

RESOLUTIONS = [("Giữ nguyên", "original"), ("1080p", "1080"), ("720p", "720")]


class ExportPanel(QWidget):
    """Tab Xuất & Upload."""
    render_requested = Signal()
    render_all_requested = Signal()
    connect_requested = Signal(str)  # uploader id

    def __init__(self, renderers: dict[str, Renderer], uploaders: dict[str, Uploader], parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        out_box = QGroupBox("Xuất video")
        form = QFormLayout(out_box)
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(str(OUTPUT_DIR))
        self.btn_browse = QPushButton("…")
        self.btn_browse.setObjectName("IconButton")
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(self.btn_browse)
        self.renderer_combo = QComboBox()
        for r in renderers.values():
            self.renderer_combo.addItem(r.name, r.id)
        self.res_combo = QComboBox()
        for label, value in RESOLUTIONS:
            self.res_combo.addItem(label, value)
        self.chk_blur = QCheckBox("Làm mờ vùng sub gốc")
        self.chk_subs = QCheckBox("Chèn sub mới vào vùng mờ")
        self.chk_voice = QCheckBox("Ghép giọng đọc AI")
        self.chk_orig = QCheckBox("Giữ tiếng gốc")
        for c in (self.chk_blur, self.chk_subs, self.chk_voice, self.chk_orig):
            c.setChecked(True)
        self.orig_volume = LabeledSlider(0, 100, 20, "%")
        form.addRow("Thư mục", dir_row)
        form.addRow("Bộ render", self.renderer_combo)
        form.addRow("Độ phân giải", self.res_combo)
        form.addRow(self.chk_blur)
        form.addRow(self.chk_subs)
        form.addRow(self.chk_voice)
        form.addRow(self.chk_orig)
        form.addRow("Âm lượng gốc", self.orig_volume)
        layout.addWidget(out_box)

        up_box = QGroupBox("Upload")
        form = QFormLayout(up_box)
        self.uploader_combo = QComboBox()
        for u in uploaders.values():
            self.uploader_combo.addItem(u.name, u.id)
        acc_row = QHBoxLayout()
        self.account_label = muted_label("Chưa kết nối")
        self.btn_connect = QPushButton("Kết nối")
        acc_row.addWidget(self.account_label, 1)
        acc_row.addWidget(self.btn_connect)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("ID hoặc link thư mục Google Drive")
        self.chk_auto = QCheckBox("Tự động upload sau khi render xong")
        self.chk_auto.setChecked(True)
        form.addRow("Đích", self.uploader_combo)
        form.addRow("Tài khoản", acc_row)
        form.addRow("Thư mục", self.folder_edit)
        form.addRow(self.chk_auto)
        layout.addWidget(up_box)

        prog_box = QGroupBox("Tiến trình")
        pv = QVBoxLayout(prog_box)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_label = muted_label("Chưa render")
        self.result_label = QLabel()
        self.result_label.setOpenExternalLinks(True)
        self.result_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.result_label.setWordWrap(True)
        pv.addWidget(self.progress)
        pv.addWidget(self.progress_label)
        pv.addWidget(self.result_label)
        layout.addWidget(prog_box)
        layout.addStretch()

        row = QHBoxLayout()
        row.setContentsMargins(10, 6, 10, 10)
        self.btn_render = accent(QPushButton("Render && Upload video này"))
        self.btn_render_all = QPushButton("Chạy tất cả")
        self.btn_render_all.setToolTip("Render + upload lần lượt mọi video đã tải trong hàng chờ")
        row.addWidget(self.btn_render, 1)
        row.addWidget(self.btn_render_all)
        outer.addLayout(row)

        self.btn_browse.clicked.connect(self._browse)
        self.btn_render.clicked.connect(self.render_requested)
        self.btn_render_all.clicked.connect(self.render_all_requested)
        self.btn_connect.clicked.connect(lambda: self.connect_requested.emit(self.uploader_combo.currentData()))
        self.uploader_combo.currentIndexChanged.connect(lambda _: self.account_label.setText("Chưa kết nối"))
        self.chk_orig.toggled.connect(self.orig_volume.setEnabled)
        self.chk_auto.toggled.connect(lambda on: self.btn_render.setText(
            "Render && Upload video này" if on else "Render video này"))

    def export_settings(self) -> ExportSettings:
        return ExportSettings(
            output_dir=Path(self.dir_edit.text().strip() or OUTPUT_DIR),
            renderer_id=self.renderer_combo.currentData(),
            resolution=self.res_combo.currentData(),
            apply_blur=self.chk_blur.isChecked(),
            burn_subs=self.chk_subs.isChecked(),
            add_voice=self.chk_voice.isChecked(),
            keep_original_audio=self.chk_orig.isChecked(),
            original_volume=self.orig_volume.value(),
            uploader_id=self.uploader_combo.currentData(),
            drive_folder=self.folder_edit.text().strip(),
            auto_upload=self.chk_auto.isChecked(),
        )

    def set_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.progress_label.setText(msg)

    def set_result(self, output: Path | None, link: str) -> None:
        parts = []
        if output:
            parts.append(f'File: <a href="{output.parent.as_uri()}">{output.name}</a>')
        if link:
            parts.append(f'Drive: <a href="{link}">{link}</a>')
        self.result_label.setText("<br>".join(parts))

    def set_busy(self, busy: bool) -> None:
        self.btn_render.setEnabled(not busy)
        self.btn_render_all.setEnabled(not busy)

    def set_account(self, name: str) -> None:
        self.account_label.setText(f"Đã kết nối: {name}")

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    def save_settings(self, qs: QSettings) -> None:
        s = self.export_settings()
        qs.setValue("export/output_dir", str(s.output_dir))
        qs.setValue("export/resolution", s.resolution)
        qs.setValue("export/uploader", s.uploader_id)
        qs.setValue("export/drive_folder", s.drive_folder)
        qs.setValue("export/auto_upload", s.auto_upload)
        qs.setValue("export/original_volume", s.original_volume)

    def load_settings(self, qs: QSettings) -> None:
        self.dir_edit.setText(qs.value("export/output_dir", str(OUTPUT_DIR)))
        for combo, key in ((self.res_combo, "export/resolution"), (self.uploader_combo, "export/uploader")):
            idx = combo.findData(qs.value(key))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self.folder_edit.setText(qs.value("export/drive_folder", ""))
        self.chk_auto.setChecked(qs.value("export/auto_upload", True, type=bool))
        self.orig_volume.set_value(int(qs.value("export/original_volume", 20)))

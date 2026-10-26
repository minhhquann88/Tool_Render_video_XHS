import os
from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton,
)

from app.config import OUTPUT_DIR
from app.models import ExportSettings
from app.services.render.base import Renderer
from app.services.upload.base import Uploader
from app.ui.theme import accent
from app.ui.widgets.common import LabeledSlider, StepPage, TaskProgress, muted_label, repolish

RESOLUTIONS = [("Giữ nguyên", "original"), ("1080p", "1080"), ("720p", "720")]


class ExportPanel(StepPage):
    """Bước 4: chọn phần nào đưa vào video (che sub / sub mới / giọng đọc), xuất và upload."""
    render_requested = Signal()
    render_all_requested = Signal()
    connect_requested = Signal(str)  # uploader id
    back_requested = Signal()

    def __init__(self, renderers: dict[str, Renderer], uploaders: dict[str, Uploader], parent=None):
        super().__init__("Xuất video",
                         "Chọn những phần muốn đưa vào video. Phần nào chưa làm sẽ mờ đi và được bỏ qua.",
                         parent)
        self._renderer_id = next(iter(renderers))
        self._output: Path | None = None

        content = QGroupBox("Nội dung")
        form = QFormLayout(content)
        self.chk_blur = QCheckBox("Che sub gốc")
        self.chk_subs = QCheckBox("Chèn sub mới")
        self.chk_voice = QCheckBox("Ghép giọng đọc AI")
        self.chk_orig = QCheckBox("Giữ tiếng gốc")
        for c in (self.chk_blur, self.chk_subs, self.chk_voice, self.chk_orig):
            c.setChecked(True)
        self.blur_state = muted_label()
        self.subs_state = muted_label()
        self.voice_state = muted_label()
        self.orig_volume = LabeledSlider(0, 100, 20, "%")
        self.orig_volume.setToolTip("Âm lượng tiếng gốc khi có giọng đọc AI (không ghép giọng thì giữ nguyên 100%)")
        form.addRow(self.chk_blur, self.blur_state)
        form.addRow(self.chk_subs, self.subs_state)
        form.addRow(self.chk_voice, self.voice_state)
        form.addRow(self.chk_orig, self.orig_volume)
        self.body.addWidget(content)

        out_box = QGroupBox("File xuất")
        form = QFormLayout(out_box)
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(str(OUTPUT_DIR))
        self.btn_browse = QPushButton("…")
        self.btn_browse.setObjectName("IconButton")
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(self.btn_browse)
        self.res_combo = QComboBox()
        for label, value in RESOLUTIONS:
            self.res_combo.addItem(label, value)
        form.addRow("Thư mục", dir_row)
        form.addRow("Độ phân giải", self.res_combo)
        self.body.addWidget(out_box)

        # bật nhóm này = tự upload sau khi xuất
        self.up_box = QGroupBox("Upload lên Google Drive sau khi xuất")
        self.up_box.setCheckable(True)
        self.up_box.setChecked(False)
        form = QFormLayout(self.up_box)
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
        form.addRow("Đích", self.uploader_combo)
        form.addRow("Tài khoản", acc_row)
        form.addRow("Thư mục", self.folder_edit)
        self.body.addWidget(self.up_box)

        self.progress = TaskProgress()
        self.body.addWidget(self.progress)
        result_row = QHBoxLayout()
        self.result_label = QLabel()
        self.result_label.setObjectName("Summary")
        self.result_label.setWordWrap(True)
        self.result_label.setOpenExternalLinks(True)
        self.btn_open = QPushButton("Mở thư mục")
        result_row.addWidget(self.result_label, 1)
        result_row.addWidget(self.btn_open)
        self.body.addLayout(result_row)
        self.body.addStretch()

        self.btn_back = QPushButton("←  Quay lại")
        self.btn_render_all = QPushButton("Xuất tất cả video")
        self.btn_render_all.setToolTip("Xuất lần lượt mọi video đã tải trong danh sách, mỗi video tự bỏ qua phần chưa làm")
        self.btn_render = accent(QPushButton("Xuất video"))
        self.btn_render.setObjectName("Big")
        self.footer.addWidget(self.btn_back)
        self.footer.addStretch()
        self.footer.addWidget(self.btn_render_all)
        self.footer.addWidget(self.btn_render)

        self.btn_browse.clicked.connect(self._browse)
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_back.clicked.connect(self.back_requested)
        self.btn_render.clicked.connect(self.render_requested)
        self.btn_render_all.clicked.connect(self.render_all_requested)
        self.btn_connect.clicked.connect(lambda: self.connect_requested.emit(self.uploader_combo.currentData()))
        self.uploader_combo.currentIndexChanged.connect(lambda _: self.account_label.setText("Chưa kết nối"))
        self.chk_orig.toggled.connect(self.orig_volume.setEnabled)
        self.up_box.toggled.connect(lambda on: self.btn_render.setText("Xuất && Upload" if on else "Xuất video"))
        self.set_result(None, "")

    def export_settings(self) -> ExportSettings:
        return ExportSettings(
            output_dir=Path(self.dir_edit.text().strip() or OUTPUT_DIR),
            renderer_id=self._renderer_id,
            resolution=self.res_combo.currentData(),
            apply_blur=self.chk_blur.isChecked() and self.chk_blur.isEnabled(),
            burn_subs=self.chk_subs.isChecked() and self.chk_subs.isEnabled(),
            add_voice=self.chk_voice.isChecked() and self.chk_voice.isEnabled(),
            keep_original_audio=self.chk_orig.isChecked(),
            original_volume=self.orig_volume.value(),
            uploader_id=self.uploader_combo.currentData(),
            drive_folder=self.folder_edit.text().strip(),
            auto_upload=self.up_box.isChecked(),
        )

    def set_availability(self, n_regions: int, n_subs: int, n_voices: int) -> None:
        """Bật/tắt từng mục theo những gì video đang có; mục chưa có dữ liệu thì mờ đi kèm gợi ý."""
        for chk, label, n, ok_text, missing in (
            (self.chk_blur, self.blur_state, n_regions, "{} vùng mờ", "chưa tìm sub (bước 1)"),
            (self.chk_subs, self.subs_state, n_subs, "{} dòng", "chưa có sub mới (bước 2)"),
            (self.chk_voice, self.voice_state, n_voices, "{} đoạn", "chưa tạo giọng (bước 3)"),
        ):
            chk.setEnabled(n > 0)
            label.setText(ok_text.format(n) if n else missing)

    def set_progress(self, pct: int, msg: str) -> None:
        self.progress.update(pct, msg)

    def set_result(self, output: Path | None, link: str) -> None:
        self._output = output
        parts = []
        if output:
            parts.append(f"✓ Đã xuất: {output.name}")
        if link:
            parts.append(f'Drive: <a href="{link}">{link}</a>')
        self.result_label.setText("<br>".join(parts))
        self.result_label.setProperty("ok", bool(parts))
        repolish(self.result_label)
        self.result_label.setVisible(bool(parts))
        self.btn_open.setVisible(output is not None)
        if output:
            self.progress.finish()

    def set_busy(self, busy: bool) -> None:
        self.btn_render.setEnabled(not busy)
        self.btn_render_all.setEnabled(not busy)

    def set_account(self, name: str) -> None:
        self.account_label.setText(f"Đã kết nối: {name}")

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    def _open_folder(self) -> None:
        folder = self._output.parent if self._output else Path(self.dir_edit.text())
        if folder.exists():
            os.startfile(folder)  # Windows: mở Explorer

    def _content_checks(self):
        return (("blur", self.chk_blur), ("subs", self.chk_subs), ("voice", self.chk_voice),
                ("keep_orig", self.chk_orig))

    def save_settings(self, qs: QSettings) -> None:
        s = self.export_settings()
        qs.setValue("export/output_dir", str(s.output_dir))
        qs.setValue("export/resolution", s.resolution)
        qs.setValue("export/uploader", s.uploader_id)
        qs.setValue("export/drive_folder", s.drive_folder)
        qs.setValue("export/auto_upload", s.auto_upload)
        qs.setValue("export/original_volume", s.original_volume)
        for key, chk in self._content_checks():
            qs.setValue(f"export/{key}", chk.isChecked())

    def load_settings(self, qs: QSettings) -> None:
        self.dir_edit.setText(qs.value("export/output_dir", str(OUTPUT_DIR)))
        for combo, key in ((self.res_combo, "export/resolution"), (self.uploader_combo, "export/uploader")):
            idx = combo.findData(qs.value(key))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self.folder_edit.setText(qs.value("export/drive_folder", ""))
        self.up_box.setChecked(qs.value("export/auto_upload", False, type=bool))
        self.orig_volume.set_value(int(qs.value("export/original_volume", 20)))
        for key, chk in self._content_checks():
            chk.setChecked(qs.value(f"export/{key}", True, type=bool))

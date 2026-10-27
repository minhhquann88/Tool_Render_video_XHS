import os
from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle

from app.config import OUTPUT_DIR
from app.ui.steps.base import StepBody
from app.ui.widgets.common import ElidedLabel, FlowLayout, Segmented, ghost, muted_label, set_prop

RESOLUTIONS = [("Giữ nguyên", "original"), ("1080p", "1080"), ("720p", "720")]


class ExportBody(StepBody):
    """Bước xuất video (+ tải lên Drive)."""
    run_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Xuất video", parent)
        self._output: Path | None = None

        self.top.addWidget(muted_label("Video xuất ra sẽ có:"))
        self.chip_row = FlowLayout()  # hết chỗ thì xuống hàng
        self._chips: list[QLabel] = []
        self.top.addLayout(self.chip_row)
        self.missing_label = QLabel()
        self.missing_label.setObjectName("WarnText")
        self.missing_label.setWordWrap(True)
        self.top.addWidget(self.missing_label)

        folder = QFrame()
        folder.setObjectName("SubBox")
        fr = QHBoxLayout(folder)
        fr.setContentsMargins(14, 6, 6, 6)
        icon = QLabel()
        icon.setPixmap(self.style().standardIcon(QStyle.SP_DirIcon).pixmap(16, 16))
        self.dir_label = ElidedLabel(str(OUTPUT_DIR))
        self.btn_browse = ghost(QPushButton("Đổi"))
        fr.addWidget(icon)
        fr.addWidget(self.dir_label, 1)
        fr.addWidget(self.btn_browse)
        self.top.addWidget(folder)

        self.upload_check = QCheckBox("Tải lên Google Drive sau khi xuất")
        self.top.addWidget(self.upload_check)
        self.drive_warning = QFrame()
        dw = QHBoxLayout(self.drive_warning)
        dw.setContentsMargins(28, 0, 0, 0)
        warn = QLabel("Chưa kết nối Drive —")
        warn.setObjectName("WarnText")
        self.btn_drive = ghost(QPushButton("kết nối trong Cài đặt"))
        self.btn_drive.setObjectName("Link")
        dw.addWidget(warn)
        dw.addWidget(self.btn_drive)
        dw.addStretch()
        self.top.addWidget(self.drive_warning)

        self.btn_open = QPushButton("Mở thư mục")
        self.btn_play = QPushButton("Xem video")
        self.btn_again = ghost(QPushButton("Xuất lại"))
        for b in (self.btn_open, self.btn_play, self.btn_again):
            self.done_row.addWidget(b)

        self.res = Segmented(RESOLUTIONS)
        self.add_advanced("Độ phân giải", self.res)

        self.btn_run.clicked.connect(self.run_requested)
        self.btn_again.clicked.connect(self.run_requested)
        self.btn_browse.clicked.connect(self._browse)
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_play.clicked.connect(lambda: self._output and self._output.exists() and os.startfile(self._output))
        self.btn_drive.clicked.connect(self.settings_requested)
        self.upload_check.toggled.connect(lambda _: self._update_run_text())
        self._drive_connected = False
        self._update_run_text()

    def output_dir(self) -> Path:
        return Path(self.dir_label.toolTip() or OUTPUT_DIR)

    def resolution(self) -> str:
        return self.res.value()

    def auto_upload(self) -> bool:
        return self.upload_check.isChecked()

    def set_drive_connected(self, connected: bool) -> None:
        self._drive_connected = connected
        self._update_run_text()

    def _update_run_text(self) -> None:
        up = self.upload_check.isChecked()
        self.btn_run.setText("Xuất && tải lên Drive" if up else "Xuất video")
        self.drive_warning.setVisible(up and not self._drive_connected)

    def set_state(self, can_run: bool, chips: list[tuple[str, bool]], missing: str,
                  output: Path | None, link: str) -> None:
        self.btn_run.setEnabled(can_run)
        self.btn_again.setEnabled(can_run)
        while len(self._chips) < len(chips):
            chip = QLabel()
            chip.setObjectName("Chip")
            chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self.chip_row.addWidget(chip)
            self._chips.append(chip)
        for i, chip in enumerate(self._chips):
            chip.setVisible(i < len(chips))
            if i < len(chips):
                chip.setText(chips[i][0])
                set_prop(chip, "ok", chips[i][1])
        self.missing_label.setText(missing)
        self.missing_label.setVisible(bool(missing))

        self._output = output
        parts = []
        if output:
            size = f" · {output.stat().st_size / 1_048_576:.0f} MB" if output.exists() else ""
            parts.append(f"Đã xuất {output.name}{size}")
        if link:
            parts.append(f'Drive: <a href="{link}" style="color:#7cb7ff">{link}</a>')
        self.summary.setText("<br>".join(parts))
        self.summary.setOpenExternalLinks(True)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất", str(self.output_dir()))
        if path:
            self.dir_label.set_full_text(path)

    def _open_folder(self) -> None:
        folder = self._output.parent if self._output else self.output_dir()
        if folder.exists():
            os.startfile(folder)  # Windows: mở Explorer

    def save_settings(self, qs: QSettings) -> None:
        qs.setValue("export/output_dir", str(self.output_dir()))
        qs.setValue("export/resolution", self.resolution())
        qs.setValue("export/auto_upload", self.auto_upload())

    def load_settings(self, qs: QSettings) -> None:
        self.dir_label.set_full_text(qs.value("export/output_dir", str(OUTPUT_DIR)))
        self.res.set_value(qs.value("export/resolution", "original"))
        self.upload_check.setChecked(qs.value("export/auto_upload", False, type=bool))

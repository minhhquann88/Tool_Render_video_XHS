from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app.ui.steps.base import StepBody


class DetectBody(StepBody):
    """Bước tìm & che sub gốc."""
    run_requested = Signal()
    add_region_requested = Signal()
    remove_region_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Tự động tìm sub", parent)
        self.btn_rerun = QPushButton("Tìm lại")
        self.done_row.addWidget(self.btn_rerun)

        manual = QWidget()
        row = QHBoxLayout(manual)
        row.setContentsMargins(0, 0, 0, 0)
        self.btn_add = QPushButton("+ Thêm vùng che")
        self.btn_add.setToolTip("Thêm vùng che cho cả video. Kéo khung trên video để di chuyển, kéo góc để co giãn")
        self.btn_remove = QPushButton("Xoá vùng đang chọn")
        self.btn_remove.setToolTip("Hoặc chọn khung trên video rồi bấm phím Delete")
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_remove)
        row.addStretch()
        self.add_advanced("Thêm thủ công", manual)

        self.btn_run.clicked.connect(self.run_requested)
        self.btn_rerun.clicked.connect(self.run_requested)
        self.btn_add.clicked.connect(self.add_region_requested)
        self.btn_remove.clicked.connect(self.remove_region_requested)

    def set_state(self, can_run: bool, has_video: bool, n_timed: int, n_fixed: int) -> None:
        self.btn_run.setEnabled(can_run)
        self.btn_rerun.setEnabled(can_run)
        self.btn_add.setEnabled(has_video)
        self.btn_remove.setEnabled(has_video)
        text = f"Đã che {n_timed} câu sub" if n_timed else "Đã che"
        if n_fixed:
            text += f" và {n_fixed} vùng cố định (logo, watermark)"
        self.summary.setText(text + ".")

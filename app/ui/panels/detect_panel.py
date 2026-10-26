from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.ui.theme import accent
from app.ui.widgets.common import StepPage, TaskProgress, muted_label, repolish


class DetectPanel(StepPage):
    """Bước 1: tìm sub gốc (vị trí + thời gian) và chỉnh vùng mờ."""
    detect_requested = Signal()
    quick_export_requested = Signal()
    add_region_requested = Signal()
    remove_region_requested = Signal()
    next_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Tìm & che sub gốc",
                         "Tự động tìm vị trí và thời gian của từng câu sub gốc. Mỗi câu được che bằng "
                         "một vùng mờ, chỉ hiện đúng lúc câu đó xuất hiện. Sub gốc đọc được sẽ tự điền "
                         "sang bước Sub mới.", parent)

        self.btn_detect = accent(QPushButton("Tự động tìm sub"))
        self.btn_detect.setObjectName("Big")
        self.body.addWidget(self.btn_detect)
        self.progress = TaskProgress()
        self.body.addWidget(self.progress)
        self.summary = QLabel()
        self.summary.setObjectName("Summary")
        self.summary.setWordWrap(True)
        self.body.addWidget(self.summary)

        manual = QGroupBox("Chỉnh tay")
        mv = QVBoxLayout(manual)
        hint = muted_label("Kéo vùng mờ trên khung xem trước để di chuyển, kéo góc dưới-phải để co giãn. "
                           "Tua video tới câu sub cần chỉnh.")
        hint.setWordWrap(True)
        row = QHBoxLayout()
        self.btn_add = QPushButton("+ Thêm vùng mờ")
        self.btn_add.setToolTip("Thêm vùng mờ áp dụng cho cả video (vd. che logo, watermark)")
        self.btn_remove = QPushButton("Xoá vùng đang chọn")
        self.btn_remove.setToolTip("Hoặc chọn vùng rồi bấm phím Delete")
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_remove)
        row.addStretch()
        mv.addWidget(hint)
        mv.addLayout(row)
        self.body.addWidget(manual)

        quick = QGroupBox("Chỉ cần che sub?")
        qv = QVBoxLayout(quick)
        q_hint = muted_label("Xuất luôn video đã che sub, giữ nguyên tiếng gốc — bỏ qua các bước sau.")
        q_hint.setWordWrap(True)
        self.btn_quick = QPushButton("Xuất video chỉ che sub")
        qv.addWidget(q_hint)
        qv.addWidget(self.btn_quick)
        self.body.addWidget(quick)
        self.body.addStretch()

        self.btn_next = QPushButton("Tiếp: Sub mới  →")
        self.footer.addStretch()
        self.footer.addWidget(self.btn_next)

        self.btn_detect.clicked.connect(self.detect_requested)
        self.btn_quick.clicked.connect(self.quick_export_requested)
        self.btn_add.clicked.connect(self.add_region_requested)
        self.btn_remove.clicked.connect(self.remove_region_requested)
        self.btn_next.clicked.connect(self.next_requested)
        self.set_state(has_video=False, n_regions=0, n_subs=0, busy=False)

    def set_state(self, has_video: bool, n_regions: int, n_subs: int, busy: bool) -> None:
        self.btn_detect.setEnabled(has_video and not busy)
        self.btn_detect.setText("Đang tìm sub…" if busy else "Tìm lại sub" if n_regions else "Tự động tìm sub")
        self.btn_add.setEnabled(has_video)
        self.btn_remove.setEnabled(has_video)
        self.btn_quick.setEnabled(n_regions > 0 and not busy)
        if not has_video:
            text, ok = "Chọn hoặc tải một video ở cột trái để bắt đầu.", False
        elif n_regions:
            subs = f"{n_subs} câu sub · " if n_subs else ""
            text, ok = f"✓ Đã có {subs}{n_regions} vùng mờ. Bấm ▶ ở khung xem trước để kiểm tra.", True
        else:
            text, ok = "Chưa tìm sub. Video ~3 phút mất khoảng 4–6 phút.", False
        self.summary.setText(text)
        self.summary.setProperty("ok", ok)
        repolish(self.summary)

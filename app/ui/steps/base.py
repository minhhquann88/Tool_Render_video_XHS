from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from app.ui.theme import accent
from app.ui.widgets.common import TaskProgress, ghost, summary_label

IDLE, RUNNING, DONE = "idle", "running", "done"


class StepBody(QWidget):
    """Thân một bước: phần riêng của bước (top) · nút chạy / tiến độ / kết quả · phần nâng cao gập được."""

    def __init__(self, run_text: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 0, 16, 16)  # thẳng hàng với tên bước (sau huy hiệu số)
        layout.setSpacing(10)

        self.top = QVBoxLayout()
        self.top.setSpacing(10)
        layout.addLayout(self.top)

        self.btn_run = accent(QPushButton(run_text))
        self.btn_run.setObjectName("Big")
        self.idle = QWidget()
        self.idle_row = QHBoxLayout(self.idle)
        self.idle_row.setContentsMargins(0, 0, 0, 0)
        self.idle_row.addWidget(self.btn_run)
        layout.addWidget(self.idle)

        self.progress = TaskProgress()
        layout.addWidget(self.progress)

        self.done = QWidget()
        dv = QVBoxLayout(self.done)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(10)
        self.summary = summary_label("ok")
        self.done_row = QHBoxLayout()
        dv.addWidget(self.summary)
        dv.addLayout(self.done_row)
        layout.addWidget(self.done)

        self.bottom = QVBoxLayout()
        self.bottom.setSpacing(10)
        layout.addLayout(self.bottom)
        self._rows_closed = False
        self.done.setVisible(False)

    def set_phase(self, phase: str, progress: tuple[int, str] = (0, ""), waiting: bool = False) -> None:
        if not self._rows_closed:  # lần đầu (lớp con đã thêm nút xong): dồn các nút sang trái
            self.idle_row.addStretch()
            self.done_row.addStretch()
            self._rows_closed = True
        self.idle.setVisible(phase == IDLE)
        self.done.setVisible(phase == DONE)
        if phase == RUNNING and waiting:
            self.progress.wait(progress[1])
        elif phase == RUNNING:
            self.progress.update(*progress)
        else:
            self.progress.finish()

    def add_advanced(self, title: str, content: QWidget) -> QFrame:
        """Nút "▸ title" mở / gập một khung tuỳ chọn thêm."""
        btn = ghost(QPushButton(f"▸  {title}"))
        btn.setCheckable(True)
        box = QFrame()
        box.setObjectName("SubBox")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(16, 16, 16, 16)
        bv.addWidget(content)
        box.setVisible(False)

        def toggle(on: bool) -> None:
            box.setVisible(on)
            btn.setText(f"{'▾' if on else '▸'}  {title}")

        btn.toggled.connect(toggle)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch()
        self.bottom.addLayout(row)
        self.bottom.addWidget(box)
        return box

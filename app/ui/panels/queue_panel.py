from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from app.models import VideoProject
from app.ui.theme import accent
from app.ui.widgets.common import dot_icon, ghost, muted_label, title_label


class QueuePanel(QFrame):
    """Cột trái: dán link + danh sách video."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(title_label("Video"))
        label = muted_label("Dán link Xiaohongshu (mỗi dòng một link)")
        self.links_edit = QPlainTextEdit()
        self.links_edit.setPlaceholderText("https://www.xiaohongshu.com/…")
        self.links_edit.setFixedHeight(76)
        label.setBuddy(self.links_edit)
        layout.addWidget(label)
        layout.addWidget(self.links_edit)

        row = QHBoxLayout()
        self.btn_add = accent(QPushButton("Thêm && tải về"))
        self.btn_local = QPushButton("Mở file…")
        self.btn_local.setToolTip("Mở video có sẵn trên máy")
        row.addWidget(self.btn_add, 1)
        row.addWidget(self.btn_local)
        layout.addLayout(row)

        line = QFrame()
        line.setObjectName("Separator")
        line.setFixedHeight(1)
        layout.addWidget(line)

        head = QHBoxLayout()
        self.count_label = muted_label("0 video")
        self.btn_download = ghost(QPushButton("Tải lại"))
        self.btn_download.setToolTip("Tải lại video bị lỗi / chưa tải (đang chọn, hoặc tất cả)")
        self.btn_remove = ghost(QPushButton("Xoá"))
        self.btn_remove.setToolTip("Xoá video đang chọn khỏi danh sách (Ctrl / Shift để chọn nhiều)")
        head.addWidget(self.count_label, 1)
        head.addWidget(self.btn_download)
        head.addWidget(self.btn_remove)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setObjectName("VideoList")
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setWordWrap(True)
        layout.addWidget(self.list, 1)

        self._items: dict[str, QListWidgetItem] = {}
        self._labels: dict[str, QLabel] = {}

    def take_links_text(self) -> str:
        text = self.links_edit.toPlainText()
        self.links_edit.clear()
        return text

    def selected_ids(self) -> list[str]:
        return [item.data(Qt.UserRole) for item in self.list.selectedItems()]

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def upsert(self, project: VideoProject, status: str, color: str) -> None:
        item = self._items.get(project.id)
        if item is None:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, project.id)
            self.list.addItem(item)
            self._items[project.id] = item
        name = project.display_name
        if len(name) > 42:
            name = name[:40] + "…"
        item.setText(f"{name}\n{status}")
        item.setIcon(dot_icon(color))
        item.setToolTip(project.error or project.url or str(project.local_path or ""))
        self.count_label.setText(f"{len(self._items)} video")

    def remove(self, project_id: str) -> None:
        item = self._items.pop(project_id, None)
        if item:
            self.list.takeItem(self.list.row(item))
        self.count_label.setText(f"{len(self._items)} video")

    def select(self, project_id: str) -> None:
        item = self._items.get(project_id)
        if item:
            self.list.setCurrentItem(item)

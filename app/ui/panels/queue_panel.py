from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QPlainTextEdit,
    QMenu, QPushButton, QVBoxLayout,
)

from app.models import VideoProject
from app.ui.theme import accent
from app.ui.widgets.common import muted_label, title_label

_icon_cache: dict[str, QIcon] = {}


def _dot(color: str) -> QIcon:
    if color not in _icon_cache:
        pix = QPixmap(12, 12)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()
        _icon_cache[color] = QIcon(pix)
    return _icon_cache[color]


class QueuePanel(QFrame):
    """Cột trái: dán link + hàng chờ video."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(270)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(title_label("Nguồn video"))
        self.links_edit = QPlainTextEdit()
        self.links_edit.setPlaceholderText("Dán link Xiaohongshu, mỗi dòng 1 link\n"
                                           "(dán cả đoạn share cũng được)")
        self.links_edit.setFixedHeight(96)
        layout.addWidget(self.links_edit)

        row = QHBoxLayout()
        self.btn_add = accent(QPushButton("Thêm && tải về"))
        self.btn_local = QPushButton("Mở file…")
        self.btn_local.setToolTip("Mở video có sẵn trên máy")
        row.addWidget(self.btn_add, 1)
        row.addWidget(self.btn_local)
        layout.addLayout(row)

        cookie_row = QHBoxLayout()
        self.cookie_label = muted_label("Cookie: chưa gắn")
        self.cookie_label.setWordWrap(True)
        self.btn_cookie = QPushButton("Cookie…")
        self.btn_cookie.setToolTip("Gắn cookie XHS / RedNote để tải video")
        menu = QMenu(self.btn_cookie)
        self.act_cookie_file = menu.addAction("Chọn file cookie (.txt / .json)…")
        self.act_cookie_paste = menu.addAction("Dán chuỗi cookie…")
        menu.addSeparator()
        self.act_cookie_clear = menu.addAction("Gỡ cookie")
        self.btn_cookie.setMenu(menu)
        cookie_row.addWidget(self.cookie_label, 1)
        cookie_row.addWidget(self.btn_cookie)
        layout.addLayout(cookie_row)

        head = QHBoxLayout()
        head.addWidget(title_label("Danh sách video"))
        head.addStretch()
        self.count_label = muted_label("0 video")
        head.addWidget(self.count_label)
        layout.addSpacing(6)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setWordWrap(True)
        layout.addWidget(self.list, 1)

        row2 = QHBoxLayout()
        self.btn_download = QPushButton("Tải lại")
        self.btn_download.setToolTip("Tải lại video bị lỗi / chưa tải (đang chọn, hoặc tất cả)")
        self.btn_remove = QPushButton("Xoá")
        row2.addWidget(self.btn_download, 1)
        row2.addWidget(self.btn_remove)
        layout.addLayout(row2)

        self._items: dict[str, QListWidgetItem] = {}

    def take_links_text(self) -> str:
        text = self.links_edit.toPlainText()
        self.links_edit.clear()
        return text

    def selected_ids(self) -> list[str]:
        return [item.data(Qt.UserRole) for item in self.list.selectedItems()]

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def upsert(self, project: VideoProject) -> None:
        item = self._items.get(project.id)
        if item is None:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, project.id)
            self.list.addItem(item)
            self._items[project.id] = item
        name = project.display_name
        if len(name) > 42:
            name = name[:40] + "…"
        status = project.status.label
        if project.status.busy:
            status += f" · {project.progress}%"
        item.setText(f"{name}\n{status}")
        item.setIcon(_dot(project.status.color))
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

    def set_cookie_status(self, text: str, ok: bool) -> None:
        self.cookie_label.setText(f"Cookie: {text}")
        self.cookie_label.setStyleSheet(f"color: {'#3ecf8e' if ok else '#f5a524'};")

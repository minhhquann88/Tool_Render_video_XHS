"""Trang sửa sub mở toàn cửa sổ: bảng câu sub + khung xem trước và chỉnh thời gian câu đang chọn."""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemDelegate, QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.models import SubtitleLine
from app.services.translate.subtrans import overlong_seconds
from app.ui.theme import accent
from app.ui.widgets.common import Segmented, ghost, muted_label, title_label
from app.utils.timefmt import ms_to_str, str_to_ms

COL_NUM, COL_TIME, COL_ORIGINAL, COL_TEXT, COL_VOICE = range(5)
_ACTIVE_BG = QColor("#2b1d22")
_EDITOR_MIN_HEIGHT = 76
_REVIEW_FG = QColor("#f8d58e")


class _SubTextDelegate(QStyledItemDelegate):
    """Ô sửa nhiều dòng: Enter lưu và sang câu sau, Shift+Enter xuống dòng, Esc huỷ."""
    advance = Signal(int, int)  # hàng, cột vừa sửa xong bằng Enter

    def createEditor(self, parent, option, index):
        editor = QPlainTextEdit(parent)
        editor.setProperty("row", index.row())
        editor.setProperty("col", index.column())
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data() or "")
        editor.moveCursor(QTextCursor.End)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText().strip())

    def updateEditorGeometry(self, editor, option, index):
        rect = option.rect
        rect.setHeight(max(rect.height(), _EDITOR_MIN_HEIGHT))
        editor.setGeometry(rect)

    def eventFilter(self, editor, event):
        if (event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and not event.modifiers() & Qt.ShiftModifier):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)
            self.advance.emit(editor.property("row"), editor.property("col"))
            return True
        return super().eventFilter(editor, event)


def _time_text(line: SubtitleLine) -> str:
    return f"{ms_to_str(line.start_ms)} → {ms_to_str(line.end_ms)}"


class SubEditor(QWidget):
    back_requested = Signal()
    seek_requested = Signal(int)
    play_line_requested = Signal(int)
    voice_requested = Signal(object)  # đường dẫn audio giọng đọc của một câu
    translate_requested = Signal(list)  # chỉ số các câu cần dịch lại
    shorten_requested = Signal(int)
    lines_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines: list[SubtitleLine] = []
        self._loading = False
        self._active_row = -1
        self._review: dict[int, float] = {}
        self.position_ms = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("TopBar")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.setSpacing(12)
        self.btn_back = ghost(QPushButton("←  Quay lại"))
        self.title = title_label("Sửa sub")
        self.count_label = muted_label()
        self.btn_done = accent(QPushButton("Xong"))
        hl.addWidget(self.btn_back)
        hl.addWidget(self.title)
        hl.addWidget(self.count_label, 1)
        hl.addWidget(self.btn_done)
        root.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(16, 12, 16, 12)
        body.setSpacing(12)
        root.addLayout(body, 1)

        # ----- bảng sub -----
        table_card = QFrame()
        table_card.setObjectName("Card")
        tv = QVBoxLayout(table_card)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        tools = QHBoxLayout()
        tools.setContentsMargins(16, 14, 16, 14)
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm trong sub…")
        self.search.setClearButtonEnabled(True)
        self.filter = Segmented([("Tất cả", "all"), ("Cần xem lại", "review")])
        self.btn_translate = QPushButton("Dịch lại câu đã chọn")
        self.btn_add = ghost(QPushButton("+ Thêm câu"))
        self.btn_add.setToolTip("Thêm câu tại vị trí đang phát")
        tools.addWidget(self.search, 1)
        tools.addWidget(self.filter)
        tools.addWidget(self.btn_translate)
        tools.addWidget(self.btn_add)
        tv.addLayout(tools)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("SubTable")
        self.table.setHorizontalHeaderLabels(["#", "Thời gian", "Sub gốc", "Sub mới", "Giọng"])
        self.table.setToolTip("Bấm một câu để tua video tới đó · double-click ô để sửa · "
                              "Enter: lưu và sang câu sau · Shift+Enter: xuống dòng · Esc: huỷ")
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setMinimumSectionSize(44)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
                                   | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)
        delegate = _SubTextDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_ORIGINAL, delegate)
        self.table.setItemDelegateForColumn(COL_TEXT, delegate)
        delegate.advance.connect(self._edit_next)
        header_view = self.table.horizontalHeader()
        for col in (COL_NUM, COL_TIME, COL_VOICE):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(COL_ORIGINAL, QHeaderView.Stretch)
        header_view.setSectionResizeMode(COL_TEXT, QHeaderView.Stretch)
        tv.addWidget(self.table, 1)
        body.addWidget(table_card, 1)

        # ----- cột phải: xem trước + chỉnh câu đang chọn -----
        aside = QVBoxLayout()
        aside.setSpacing(12)
        preview_card = QFrame()
        preview_card.setObjectName("Card")
        preview_card.setFixedWidth(380)
        pv = QVBoxLayout(preview_card)
        pv.setContentsMargins(16, 16, 16, 16)
        pv.setSpacing(10)
        self.preview_title = title_label("Câu đang chọn trên video")
        pv.addWidget(self.preview_title)
        self.preview_slot = QVBoxLayout()
        pv.addLayout(self.preview_slot, 1)
        self.btn_play_line = QPushButton("▶  Phát câu này")
        pv.addWidget(self.btn_play_line)
        aside.addWidget(preview_card, 1)

        timing = QFrame()
        timing.setObjectName("Card")
        timing.setFixedWidth(380)
        tl = QVBoxLayout(timing)
        tl.setContentsMargins(16, 16, 16, 16)
        tl.setSpacing(10)
        self.timing_title = title_label("Chỉnh câu đang chọn")
        tl.addWidget(self.timing_title)
        self.time_label = muted_label()
        tl.addWidget(self.time_label)
        self.review_box = QFrame()
        self.review_box.setObjectName("WarnBox")
        rl = QHBoxLayout(self.review_box)
        rl.setContentsMargins(14, 10, 10, 10)
        self.review_label = QLabel()
        self.review_label.setObjectName("WarnText")
        self.review_label.setWordWrap(True)
        self.btn_shorten = QPushButton("Rút gọn")
        self.btn_shorten.setToolTip("Nhờ Gemini viết lại câu này ngắn hơn cho vừa thời lượng")
        rl.addWidget(self.review_label, 1)
        rl.addWidget(self.btn_shorten)
        tl.addWidget(self.review_box)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.btn_set_start = QPushButton("Bắt đầu = vị trí phát")
        self.btn_set_end = QPushButton("Kết thúc = vị trí phát")
        self.btn_delete = QPushButton("Xoá câu")
        self.btn_delete.setObjectName("Danger")
        self.btn_delete.setToolTip("Xoá câu đang chọn (chọn nhiều dòng để xoá nhiều câu)")
        grid.addWidget(self.btn_set_start, 0, 0)
        grid.addWidget(self.btn_set_end, 0, 1)
        grid.addWidget(self.btn_delete, 1, 0, 1, 2)
        tl.addLayout(grid)
        aside.addWidget(timing)
        body.addLayout(aside)

        self.btn_back.clicked.connect(self.back_requested)
        self.btn_done.clicked.connect(self.back_requested)
        self.search.textChanged.connect(lambda _: self._apply_filter())
        self.filter.changed.connect(lambda _: self._apply_filter())
        self.btn_translate.clicked.connect(self._translate_selected)
        self.btn_add.clicked.connect(self._add_line)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(lambda row, *_: self._on_current(row))
        self.table.cellClicked.connect(lambda row, _col: self._seek_row(row))
        self.btn_play_line.clicked.connect(lambda: self._current_row() >= 0
                                           and self.play_line_requested.emit(self._current_row()))
        self.btn_set_start.clicked.connect(lambda: self._set_time("start_ms"))
        self.btn_set_end.clicked.connect(lambda: self._set_time("end_ms"))
        self.btn_delete.clicked.connect(self._delete)
        self.btn_shorten.clicked.connect(lambda: self._current_row() >= 0
                                         and self.shorten_requested.emit(self._current_row()))
        self._on_current(-1)

    # ----- dữ liệu -----
    def attach_preview(self, widget: QWidget) -> None:
        self.preview_slot.addWidget(widget)

    def set_title(self, name: str) -> None:
        self.title.setText(f"Sửa sub · {name}")

    def set_lines(self, lines: list[SubtitleLine]) -> None:
        """Giữ tham chiếu tới list của project: sửa bảng = sửa project."""
        row = self._current_row()
        self._lines = lines
        self._active_row = -1
        self._loading = True
        self.table.setRowCount(0)
        for line in lines:
            self._append_row(line)
        self._loading = False
        self._refresh_review()
        self.table.resizeRowsToContents()
        if 0 <= row < len(lines):
            self.table.selectRow(row)
        self._apply_filter()
        self._on_current(self._current_row())

    def set_busy(self, busy: bool) -> None:
        self.btn_translate.setEnabled(not busy)
        self.btn_shorten.setEnabled(not busy)
        self.btn_translate.setText("Đang dịch…" if busy else "Dịch lại câu đã chọn")

    def _append_row(self, line: SubtitleLine) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        num = QTableWidgetItem(str(r + 1))
        num.setFlags(num.flags() & ~Qt.ItemIsEditable)
        num.setForeground(QColor("#9aa0a9"))
        time = QTableWidgetItem(_time_text(line))
        time.setForeground(QColor("#9aa0a9"))
        time.setToolTip("Sửa dạng 00:01.200 → 00:03.500")
        original = QTableWidgetItem(line.original)
        original.setForeground(QColor("#9aa0a9"))
        self.table.setItem(r, COL_NUM, num)
        self.table.setItem(r, COL_TIME, time)
        self.table.setItem(r, COL_ORIGINAL, original)
        self.table.setItem(r, COL_TEXT, QTableWidgetItem(line.text))
        self._set_voice_cell(r)

    def _set_voice_cell(self, r: int) -> None:
        line = self._lines[r]
        if line.audio_path:
            btn = QPushButton("▶")
            btn.setObjectName("IconButton")
            btn.setToolTip(f"Nghe câu {r + 1}")
            btn.clicked.connect(lambda _=False, path=line.audio_path: self.voice_requested.emit(path))
            self.table.setCellWidget(r, COL_VOICE, btn)
        else:
            self.table.removeCellWidget(r, COL_VOICE)
            item = QTableWidgetItem("—")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setForeground(QColor("#5d626b"))
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, COL_VOICE, item)

    def _refresh_review(self) -> None:
        """Câu sub mới dài hơn thời lượng -> tô vàng, lọc được ở "Cần xem lại"."""
        self._review = overlong_seconds(self._lines)
        self._loading = True
        for r in range(self.table.rowCount()):
            item = self.table.item(r, COL_TEXT)
            if not item:
                continue
            extra = self._review.get(r)
            item.setForeground(QBrush(_REVIEW_FG) if extra else QBrush())
            item.setToolTip(f"Dài hơn thời lượng khoảng {extra:.1f} giây".replace(".", ",") if extra else "")
        self._loading = False
        n, k = len(self._lines), len(self._review)
        self.count_label.setText(f"{n} câu · {k} câu cần xem lại" if k else f"{n} câu")
        self.filter.set_label("all", f"Tất cả {n}")
        self.filter.set_label("review", f"Cần xem lại {k}")

    def _apply_filter(self) -> None:
        query = self.search.text().strip().lower()
        only_review = self.filter.value() == "review"
        for r, line in enumerate(self._lines):
            hide = (only_review and r not in self._review) or \
                (query and query not in line.text.lower() and query not in line.original.lower())
            self.table.setRowHidden(r, bool(hide))

    # ----- vị trí phát -----
    def text_at(self, ms: int) -> str:
        line = next((l for l in self._lines if l.start_ms <= ms < l.end_ms), None)
        return line.text if line else ""

    def highlight_at(self, ms: int) -> None:
        self.position_ms = ms
        row = next((i for i, l in enumerate(self._lines) if l.start_ms <= ms < l.end_ms), -1)
        if row == self._active_row:
            return
        self._loading = True
        for r, bg in ((self._active_row, None), (row, _ACTIVE_BG)):
            if 0 <= r < self.table.rowCount():
                for c in range(self.table.columnCount()):
                    item = self.table.item(r, c)
                    if item:
                        item.setBackground(QBrush(bg) if bg else QBrush())
        self._loading = False
        self._active_row = row

    # ----- câu đang chọn -----
    def _current_row(self) -> int:
        row = self.table.currentRow()
        return row if 0 <= row < len(self._lines) else -1

    def _seek_row(self, row: int) -> None:
        if 0 <= row < len(self._lines):
            self.seek_requested.emit(self._lines[row].start_ms)

    def _on_current(self, row: int) -> None:
        has = 0 <= row < len(self._lines)
        for b in (self.btn_play_line, self.btn_set_start, self.btn_set_end, self.btn_delete):
            b.setEnabled(has)
        if has:
            line = self._lines[row]
            seconds = f"{(line.end_ms - line.start_ms) / 1000:.1f}".replace(".", ",")
            self.time_label.setText(f"{_time_text(line)}   ·   dài {seconds} giây")
        self.time_label.setVisible(has)
        self.preview_title.setText(f"Câu {row + 1} trên video" if has else "Câu đang chọn trên video")
        self.timing_title.setText(f"Chỉnh câu {row + 1}" if has else "Chỉnh câu đang chọn")
        extra = self._review.get(row) if has else None
        self.review_box.setVisible(bool(extra))
        if extra:
            self.review_label.setText(f"Dài hơn thời lượng {extra:.1f} giây".replace(".", ","))

    def _edit_next(self, row: int, col: int) -> None:
        nxt = next((r for r in range(row + 1, len(self._lines)) if not self.table.isRowHidden(r)), -1)
        if nxt < 0:
            return

        def go():
            self.table.setCurrentCell(nxt, col)
            self._seek_row(nxt)
            self.table.editItem(self.table.item(nxt, col))

        QTimer.singleShot(0, go)

    # ----- chỉnh sửa -----
    def _changed(self, rebuild: bool = False) -> None:
        if rebuild:
            self.set_lines(self._lines)
        else:
            self._refresh_review()
            self._on_current(self._current_row())
        self.lines_changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        r, col = item.row(), item.column()
        line = self._lines[r]
        if col == COL_TIME:
            parts = re.split(r"\s*(?:→|->)\s*", item.text().strip())
            try:
                start, end = (str_to_ms(p) for p in parts) if len(parts) == 2 else (None, None)
            except ValueError:
                start = end = None
            if start is not None and end > start:
                line.start_ms, line.end_ms = start, end
            self._loading = True
            item.setText(_time_text(line))
            self._loading = False
        elif col == COL_TEXT:
            if line.text != item.text():
                line.audio_path = None  # sửa câu thì giọng cũ không còn khớp
                self._set_voice_cell(r)
            line.text = item.text()
        elif col == COL_ORIGINAL:
            line.original = item.text()
        self.table.resizeRowToContents(r)
        self._changed()

    def _translate_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        rows = [r for r in rows if self._lines[r].original.strip()]
        if rows:
            self.translate_requested.emit(rows)

    def _add_line(self) -> None:
        start = self.position_ms
        line = SubtitleLine(start, start + 2000)
        index = next((i for i, l in enumerate(self._lines) if l.start_ms > start), len(self._lines))
        self._lines.insert(index, line)
        self._changed(rebuild=True)
        self.table.setCurrentCell(index, COL_TEXT)
        self.table.editItem(self.table.item(index, COL_TEXT))

    def _set_time(self, attr: str) -> None:
        row = self._current_row()
        if row < 0:
            return
        line = self._lines[row]
        setattr(line, attr, self.position_ms)
        if line.end_ms <= line.start_ms:  # giữ câu dài ít nhất 0,5 giây
            if attr == "start_ms":
                line.end_ms = line.start_ms + 500
            else:
                line.start_ms = max(0, line.end_ms - 500)
        self._loading = True
        self.table.item(row, COL_TIME).setText(_time_text(line))
        self._loading = False
        self._changed()

    def _delete(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()} or {self._current_row()}, reverse=True)
        rows = [r for r in rows if r >= 0]
        for r in rows:
            del self._lines[r]
        if rows:
            self._changed(rebuild=True)


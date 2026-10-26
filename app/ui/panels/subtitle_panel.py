from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFontComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QMenu, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
)

from app.models import SubStyle, SubtitleLine
from app.services.subtitle.base import SubtitleSource
from app.ui.widgets.common import ColorButton, StepPage, muted_label
from app.utils.timefmt import ms_to_str, str_to_ms

COL_START, COL_END, COL_ORIGINAL, COL_TEXT = range(4)
_ACTIVE_BG = QColor("#2b1d22")


class SubtitlePanel(StepPage):
    """Bước 2: sửa sub mới (chèn vào vùng mờ) + kiểu chữ."""
    generate_requested = Signal(str)  # source id
    import_requested = Signal()
    export_requested = Signal()
    seek_requested = Signal(int)
    subtitles_changed = Signal()
    style_changed = Signal()
    back_requested = Signal()
    next_requested = Signal()

    def __init__(self, sources: dict[str, SubtitleSource], parent=None):
        super().__init__("Sub mới (tuỳ chọn)",
                         "Sub gốc đã được đọc tự động ở bước 1. Gõ nội dung mới vào cột \"Sub mới\" "
                         "(double-click ô để sửa) — chữ sẽ được chèn vào đúng vùng mờ của câu đó. "
                         "Dòng để trống thì chỉ che, không chèn gì. Không cần sub mới thì bỏ qua bước này.",
                         parent)
        self._source_id = next(iter(sources))
        self._lines: list[SubtitleLine] = []
        self._loading = False
        self._active_row = -1
        self.position_ms = 0
        layout = self.body

        row = QHBoxLayout()
        self.count_label = muted_label()
        self.btn_file = QPushButton("Tệp sub  ▾")
        menu = QMenu(self.btn_file)
        self.act_generate = menu.addAction("Đọc lại sub gốc từ video")
        menu.addSeparator()
        self.act_import = menu.addAction("Nhập file .srt…")
        self.act_export = menu.addAction("Xuất file .srt…")
        self.btn_file.setMenu(menu)
        row.addWidget(self.count_label, 1)
        row.addWidget(self.btn_file)
        layout.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Bắt đầu", "Kết thúc", "Sub gốc", "Sub mới"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_START, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_END, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_ORIGINAL, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btn_add = QPushButton("+ Dòng")
        self.btn_delete = QPushButton("− Dòng")
        self.btn_set_start = QPushButton("⇤ Bắt đầu")
        self.btn_set_start.setToolTip("Đặt mốc bắt đầu = vị trí đang phát")
        self.btn_set_end = QPushButton("Kết thúc ⇥")
        self.btn_set_end.setToolTip("Đặt mốc kết thúc = vị trí đang phát")
        for b in (self.btn_add, self.btn_delete, self.btn_set_start, self.btn_set_end):
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(muted_label("Double-click mốc thời gian để tua tới dòng đó · dòng đang phát được tô đỏ"))

        style_box = QGroupBox("Kiểu chữ sub mới")
        form = QFormLayout(style_box)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont("Arial"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(12, 200)
        self.size_spin.setValue(56)
        self.size_spin.setSuffix(" px")
        self.bold_check = QCheckBox("In đậm")
        self.bold_check.setChecked(True)
        size_row = QHBoxLayout()
        size_row.addWidget(self.size_spin)
        size_row.addWidget(self.bold_check)
        size_row.addStretch()
        self.color_btn = ColorButton("#FFFFFF")
        self.outline_btn = ColorButton("#000000")
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_btn)
        color_row.addWidget(muted_label("Viền"))
        color_row.addWidget(self.outline_btn)
        color_row.addStretch()
        form.addRow("Font", self.font_combo)
        form.addRow("Cỡ chữ", size_row)
        form.addRow("Màu chữ", color_row)
        layout.addWidget(style_box)

        self.btn_back = QPushButton("←  Quay lại")
        self.btn_next = QPushButton("Tiếp: Giọng đọc  →")
        self.footer.addWidget(self.btn_back)
        self.footer.addStretch()
        self.footer.addWidget(self.btn_next)

        self.act_generate.triggered.connect(lambda: self.generate_requested.emit(self._source_id))
        self.act_import.triggered.connect(self.import_requested)
        self.act_export.triggered.connect(self.export_requested)
        self.btn_back.clicked.connect(self.back_requested)
        self.btn_next.clicked.connect(self.next_requested)
        self.btn_add.clicked.connect(self._add_line)
        self.btn_delete.clicked.connect(self._delete_lines)
        self.btn_set_start.clicked.connect(lambda: self._set_time(COL_START))
        self.btn_set_end.clicked.connect(lambda: self._set_time(COL_END))
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.font_combo.currentFontChanged.connect(self.style_changed)
        self.size_spin.valueChanged.connect(self.style_changed)
        self.bold_check.toggled.connect(self.style_changed)
        self.color_btn.color_changed.connect(self.style_changed)
        self.outline_btn.color_changed.connect(self.style_changed)

        self.set_lines([])

    # ----- dữ liệu -----
    def set_lines(self, lines: list[SubtitleLine]) -> None:
        """Giữ tham chiếu tới list của project: sửa bảng = sửa project."""
        self._lines = lines
        self._active_row = -1
        self._loading = True
        self.table.setRowCount(0)
        for line in lines:
            self._append_row(line)
        self._loading = False
        self.table.resizeRowsToContents()
        self._update_count()

    def set_enabled(self, enabled: bool) -> None:
        for w in (self.btn_file, self.btn_add, self.btn_delete, self.btn_set_start, self.btn_set_end, self.table):
            w.setEnabled(enabled)

    def _update_count(self) -> None:
        n = len(self._lines)
        new = sum(1 for l in self._lines if l.text.strip())
        self.count_label.setText(f"{n} dòng sub gốc · {new} dòng có sub mới" if n else
                                 "Chưa có sub — tìm sub ở bước 1 hoặc nhập file .srt")
        self.act_export.setEnabled(n > 0)

    def _append_row(self, line: SubtitleLine) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, COL_START, QTableWidgetItem(ms_to_str(line.start_ms)))
        self.table.setItem(r, COL_END, QTableWidgetItem(ms_to_str(line.end_ms)))
        original = QTableWidgetItem(line.original)
        original.setForeground(QColor("#8a8f98"))
        self.table.setItem(r, COL_ORIGINAL, original)
        self.table.setItem(r, COL_TEXT, QTableWidgetItem(line.text))

    def sub_style(self) -> SubStyle:
        return SubStyle(
            font_family=self.font_combo.currentFont().family(),
            font_size=self.size_spin.value(),
            color=self.color_btn.color(),
            outline_color=self.outline_btn.color(),
            bold=self.bold_check.isChecked(),
        )

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

    # ----- chỉnh sửa -----
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        line = self._lines[item.row()]
        col = item.column()
        if col in (COL_START, COL_END):
            attr = "start_ms" if col == COL_START else "end_ms"
            try:
                setattr(line, attr, str_to_ms(item.text()))
            except ValueError:
                pass
            self._loading = True
            item.setText(ms_to_str(getattr(line, attr)))
            self._loading = False
        elif col == COL_TEXT:
            line.text = item.text()
        elif col == COL_ORIGINAL:
            line.original = item.text()
        self._update_count()
        self.subtitles_changed.emit()

    def _on_double_click(self, row: int, col: int) -> None:
        if col in (COL_START, COL_END):
            self.seek_requested.emit(self._lines[row].start_ms)

    def _add_line(self) -> None:
        start = self.position_ms
        line = SubtitleLine(start, start + 2000, text="Sub mới")
        index = next((i for i, l in enumerate(self._lines) if l.start_ms > start), len(self._lines))
        self._lines.insert(index, line)
        self.set_lines(self._lines)
        self.table.selectRow(index)
        self.subtitles_changed.emit()

    def _delete_lines(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        for r in rows:
            del self._lines[r]
        if rows:
            self.set_lines(self._lines)
            self.subtitles_changed.emit()

    def _set_time(self, col: int) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.item(row, col).setText(ms_to_str(self.position_ms))

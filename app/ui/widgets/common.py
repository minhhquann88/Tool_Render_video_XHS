from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QButtonGroup, QColorDialog, QComboBox,
    QFrame, QHBoxLayout, QLabel, QLayout, QProgressBar, QPushButton, QScrollBar, QSlider, QVBoxLayout, QWidget,
)


class NoWheelFilter(QObject):
    """Con lăn chuột không đổi giá trị ô chọn / ô số / thanh trượt (dễ đổi nhầm khi đang cuộn trang);
    thay vào đó cuộn khung chứa nó như bình thường."""

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QAbstractSpinBox, QAbstractSlider))
                and not isinstance(obj, QScrollBar)):
            parent = obj.parentWidget()
            while parent and not isinstance(parent, QAbstractScrollArea):
                parent = parent.parentWidget()
            if parent:
                QApplication.sendEvent(parent.verticalScrollBar(), event)
            return True
        return False


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    return frame


def title_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    return lbl


def muted_label(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    return lbl


def summary_label(tone: str = "ok") -> QLabel:
    """Ô kết quả có nền: tone "ok" (xanh) hoặc "warn" (vàng)."""
    lbl = QLabel()
    lbl.setObjectName("Summary")
    lbl.setProperty(tone, True)
    lbl.setWordWrap(True)
    return lbl


def ghost(button: QPushButton) -> QPushButton:
    """Nút phụ không viền / nền."""
    button.setObjectName("Ghost")
    return button


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_prop(widget: QWidget, name: str, value) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


_icon_cache: dict[tuple[str, bool], QIcon] = {}


def dot_icon(color: str, filled: bool = True) -> QIcon:
    key = (color, filled)
    if key not in _icon_cache:
        pix = QPixmap(12, 12)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        if filled:
            painter.setBrush(QColor(color))
            painter.setPen(Qt.NoPen)
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor(color))
        painter.drawEllipse(2, 2, 8, 8)
        painter.end()
        _icon_cache[key] = QIcon(pix)
    return _icon_cache[key]


class FlowLayout(QLayout):
    """Xếp các widget theo hàng, hết chỗ thì xuống hàng (chip, nhãn ngắn)."""

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect: QRect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


class ClickableFrame(QFrame):
    """Khung bấm được như nút (chuột hoặc Space / Enter khi đang focus)."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class ElidedLabel(QLabel):
    """Nhãn một dòng, chữ dài thì cắt "…" ở giữa (đường dẫn file)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setMinimumWidth(40)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(10, self.width())))


class Segmented(QFrame):
    """Nhóm nút chọn một (Bản gốc | Kết quả, Tất cả | Cần xem lại, ...)."""
    changed = Signal(object)  # data của nút được chọn

    def __init__(self, options: list[tuple[str, object]], parent=None):
        super().__init__(parent)
        self.setObjectName("SegGroup")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        self._group = QButtonGroup(self)
        self._buttons: list[tuple[QPushButton, object]] = []
        for label, data in options:
            btn = QPushButton(label)
            btn.setObjectName("Seg")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._group.addButton(btn)
            layout.addWidget(btn)
            self._buttons.append((btn, data))
            btn.clicked.connect(lambda _=False, d=data: self.changed.emit(d))
        self._buttons[0][0].setChecked(True)

    def value(self):
        return next(d for b, d in self._buttons if b.isChecked())

    def set_value(self, data) -> None:
        for btn, d in self._buttons:
            if d == data:
                btn.setChecked(True)

    def set_label(self, data, text: str) -> None:
        for btn, d in self._buttons:
            if d == data:
                btn.setText(text)


class TaskProgress(QWidget):
    """Thanh tiến độ + dòng trạng thái của một việc chạy nền (ẩn khi không chạy)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.label = muted_label()
        self.label.setWordWrap(True)
        layout.addWidget(self.bar)
        layout.addWidget(self.label)
        self.setVisible(False)

    @property
    def running(self) -> bool:
        return not self.isHidden() and not self.bar.isHidden()  # đúng cả khi trang đang bị ẩn

    def update(self, pct: int, msg: str) -> None:
        self.setVisible(True)
        self.bar.setVisible(True)
        self.bar.setValue(pct)
        self.label.setText(f"{msg}  {pct}%")

    def wait(self, msg: str) -> None:
        """Đang xếp hàng chờ: chỉ hiện dòng chữ, chưa có thanh tiến độ."""
        self.setVisible(True)
        self.bar.setVisible(False)
        self.label.setText(msg)

    def finish(self, msg: str = "") -> None:
        self.bar.setVisible(False)
        self.label.setText(msg)
        self.setVisible(bool(msg))


class ColorButton(QPushButton):
    color_changed = Signal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 28)
        self.set_color(color)
        self.clicked.connect(self._pick)

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        self.setStyleSheet(f"background: {color}; border: 1px solid #343842; border-radius: 6px;")

    def _pick(self) -> None:
        picked = QColorDialog.getColor(QColor(self._color), self, "Chọn màu")
        if picked.isValid():
            self.set_color(picked.name().upper())
            self.color_changed.emit(self._color)


class LabeledSlider(QWidget):
    """Slider kèm nhãn giá trị, vd '+10%'."""
    value_changed = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, unit: str, parent=None):
        super().__init__(parent)
        self._unit = unit
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.label = muted_label()
        self.label.setFixedWidth(52)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.label)
        self.slider.valueChanged.connect(self._update)
        self.slider.setValue(value)
        self._update(value)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.setValue(value)

    def _update(self, value: int) -> None:
        self.label.setText(f"{value:+d}{self._unit}" if self.slider.minimum() < 0 else f"{value}{self._unit}")
        self.value_changed.emit(value)

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget,
)

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


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class StepNav(QWidget):
    """Thanh bước bấm được: số thứ tự, ✓ khi xong, gạch chân bước đang mở."""
    step_clicked = Signal(int)

    def __init__(self, names: list[str], parent=None):
        super().__init__(parent)
        self._names = names
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._buttons: list[QPushButton] = []
        for i in range(len(names)):
            btn = QPushButton()
            btn.setObjectName("StepTab")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=i: self.step_clicked.emit(i))
            layout.addWidget(btn, 1)
            self._buttons.append(btn)
        self.set_done([False] * len(names))
        self.set_current(0)

    def set_current(self, index: int) -> None:
        self._buttons[index].setChecked(True)

    def set_done(self, done: list[bool]) -> None:
        for i, (btn, d) in enumerate(zip(self._buttons, done)):
            name = self._names[i].replace("&", "&&")  # "&" trên nút là phím tắt
            btn.setText(f"✓  {name}" if d else f"{i + 1}  {name}")
            btn.setProperty("done", d)
            repolish(btn)


class StepPage(QWidget):
    """Khung chung của một bước: tiêu đề + mô tả, phần thân, chân trang (nút điều hướng / hành động)."""

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(10)
        outer.addWidget(title_label(title))
        desc = muted_label(description)
        desc.setWordWrap(True)
        outer.addWidget(desc)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)
        self.footer = QHBoxLayout()
        self.footer.setSpacing(8)
        outer.addLayout(self.footer)


class TaskProgress(QWidget):
    """Thanh tiến độ + dòng trạng thái của một việc chạy nền (ẩn khi không chạy)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
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

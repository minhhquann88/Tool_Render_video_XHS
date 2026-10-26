from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget,
)

STEPS = ["Cào video", "Làm mờ sub", "Sub mới", "Giọng đọc", "Render", "Upload"]


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


class StepBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._labels: list[QLabel] = []
        for i, name in enumerate(STEPS):
            if i:
                arrow = QLabel("›")
                arrow.setObjectName("StepArrow")
                layout.addWidget(arrow)
            lbl = QLabel(f"{i + 1}  {name}")
            lbl.setObjectName("Step")
            layout.addWidget(lbl)
            self._labels.append(lbl)
        self.set_states([False] * len(STEPS))

    def set_states(self, done: list[bool]) -> None:
        active = next((i for i, d in enumerate(done) if not d), None)
        for i, (lbl, d) in enumerate(zip(self._labels, done)):
            lbl.setProperty("state", "done" if d else "active" if i == active else "todo")
            repolish(lbl)


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

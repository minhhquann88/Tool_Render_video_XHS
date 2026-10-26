"""Khung preview video + các vùng làm mờ kéo thả / co giãn được.

Toạ độ scene = toạ độ pixel của video, nên vùng mờ quy đổi chính xác sang
toạ độ chuẩn hoá (0..1) dùng cho bước render.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QTextOption
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QGraphicsItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsTextItem, QGraphicsView, QStyle,
)

from app.models import BlurRegion, SubStyle

_ACCENT = QColor("#ff2e4d")


class BlurRegionItem(QGraphicsRectItem):
    MIN_SIZE = 24

    def __init__(self, region: BlurRegion, rect: QRectF, on_changed):
        super().__init__(0, 0, rect.width(), rect.height())
        self.region = region
        self._on_changed = on_changed
        self._resizing = False
        self.setPos(rect.topLeft())
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)

        pen = QPen(_ACCENT, 2, Qt.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(190, 195, 205, 110)))  # mô phỏng hiệu ứng mờ

        self.text_item = QGraphicsTextItem(self)
        self.text_item.setAcceptedMouseButtons(Qt.NoButton)
        self.text_item.document().setDocumentMargin(4)
        option = QTextOption(Qt.AlignCenter)
        option.setWrapMode(QTextOption.WordWrap)
        self.text_item.document().setDefaultTextOption(option)
        self._shadow = QGraphicsDropShadowEffect()
        self._shadow.setOffset(0, 0)
        self._shadow.setBlurRadius(10)
        self.text_item.setGraphicsEffect(self._shadow)

    # ----- vẽ & tương tác -----
    def _handle_rect(self) -> QRectF:
        r = self.rect()
        size = self.scene().sceneRect().width() * 0.03 if self.scene() else 20
        return QRectF(r.right() - size, r.bottom() - size, size, size)

    def paint(self, painter: QPainter, option, widget=None):
        option.state &= ~QStyle.State_Selected  # bỏ khung chọn mặc định
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.fillRect(self._handle_rect(), _ACCENT)

    def hoverMoveEvent(self, event):
        in_handle = self.isSelected() and self._handle_rect().contains(event.pos())
        self.setCursor(Qt.SizeFDiagCursor if in_handle else Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSelected() and self._handle_rect().contains(event.pos()):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            frame = self.scene().sceneRect()
            w = min(max(event.pos().x(), self.MIN_SIZE), frame.right() - self.pos().x())
            h = min(max(event.pos().y(), self.MIN_SIZE), frame.bottom() - self.pos().y())
            self.setRect(0, 0, w, h)
            self.layout_text()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resizing = False
        super().mouseReleaseEvent(event)
        self._on_changed()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            frame = self.scene().sceneRect()
            r = self.rect()
            x = min(max(value.x(), frame.left()), frame.right() - r.width())
            y = min(max(value.y(), frame.top()), frame.bottom() - r.height())
            return QPointF(x, y)
        return super().itemChange(change, value)

    # ----- sub mới hiển thị trong vùng mờ -----
    def set_text(self, text: str, style: SubStyle) -> None:
        font = QFont(style.font_family)
        font.setPixelSize(style.font_size)
        font.setBold(style.bold)
        self.text_item.setFont(font)
        self.text_item.setDefaultTextColor(QColor(style.color))
        self._shadow.setColor(QColor(style.outline_color))
        self.text_item.setPlainText(text)
        self.layout_text()

    def layout_text(self) -> None:
        r = self.rect()
        self.text_item.setTextWidth(r.width())
        h = self.text_item.boundingRect().height()
        self.text_item.setPos(0, (r.height() - h) / 2)

    def scene_rect(self) -> QRectF:
        return QRectF(self.pos(), self.rect().size())


class VideoCanvas(QGraphicsView):
    regions_changed = Signal()
    DEFAULT_SIZE = QSizeF(1080, 1920)  # video XHS thường là dọc 9:16

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor("#0b0c0e"))
        self.setMinimumSize(280, 360)

        self._frame_bg = QGraphicsRectItem()
        self._frame_bg.setBrush(QColor("#000000"))
        self._frame_bg.setPen(Qt.NoPen)
        self._frame_bg.setZValue(-1)
        self._scene.addItem(self._frame_bg)

        self.video_item = QGraphicsVideoItem()
        self._scene.addItem(self.video_item)
        self.video_item.nativeSizeChanged.connect(self._on_native_size)

        self._placeholder = QGraphicsSimpleTextItem("Chưa có video\nDán link XHS hoặc mở file từ máy")
        self._placeholder.setBrush(QColor("#5d626b"))
        self._scene.addItem(self._placeholder)

        self._items: list[BlurRegionItem] = []
        self._style = SubStyle()
        self._text = ""
        self._show_text = True
        self._set_frame_size(self.DEFAULT_SIZE)

    # ----- khung video -----
    @property
    def frame_size(self) -> QSizeF:
        return self._scene.sceneRect().size()

    def set_has_video(self, has_video: bool) -> None:
        self._placeholder.setVisible(not has_video)
        if not has_video:
            self._set_frame_size(self.DEFAULT_SIZE)

    def _on_native_size(self, size: QSizeF) -> None:
        if size.isValid() and size.width() > 0 and size != self.frame_size:
            self._set_frame_size(QSizeF(size))

    def _set_frame_size(self, size: QSizeF) -> None:
        regions = self.regions()  # tính theo kích thước cũ, dựng lại theo kích thước mới
        rect = QRectF(QPointF(0, 0), size)
        self._scene.setSceneRect(rect)
        self._frame_bg.setRect(rect)
        self.video_item.setSize(size)
        font = QFont("Segoe UI")
        font.setPixelSize(int(size.width() * 0.04))
        self._placeholder.setFont(font)
        br = self._placeholder.boundingRect()
        self._placeholder.setPos((size.width() - br.width()) / 2, (size.height() - br.height()) / 2)
        self.set_regions(regions, notify=False)
        self._fit()

    def _fit(self) -> None:
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    # ----- vùng mờ -----
    def regions(self) -> list[BlurRegion]:
        fw, fh = self.frame_size.width(), self.frame_size.height()
        out = []
        for item in self._items:
            r = item.scene_rect()
            reg = item.region
            reg.x, reg.y, reg.w, reg.h = r.x() / fw, r.y() / fh, r.width() / fw, r.height() / fh
            out.append(reg)
        return out

    def set_regions(self, regions: list[BlurRegion], notify: bool = True) -> None:
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()
        fw, fh = self.frame_size.width(), self.frame_size.height()
        for reg in regions:
            rect = QRectF(reg.x * fw, reg.y * fh, reg.w * fw, reg.h * fh)
            item = BlurRegionItem(reg, rect, self.regions_changed.emit)
            self._scene.addItem(item)
            self._items.append(item)
        self._refresh_text()
        if notify:
            self.regions_changed.emit()

    def add_region(self) -> None:
        regions = self.regions()
        offset = 0.04 * len(regions)
        regions.append(BlurRegion(x=0.06, y=max(0.05, 0.78 - offset), w=0.88, h=0.09))
        self.set_regions(regions)
        self._items[-1].setSelected(True)

    def remove_selected(self) -> None:
        keep = [item.region for item in self._items if not item.isSelected()]
        if len(keep) != len(self._items):
            self.regions()  # cập nhật toạ độ trước khi dựng lại
            self.set_regions(keep)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.remove_selected()
            return
        super().keyPressEvent(event)

    # ----- sub mới -----
    def set_sub_style(self, style: SubStyle) -> None:
        self._style = style
        self._refresh_text()

    def set_overlay_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self._refresh_text()

    def set_show_text(self, show: bool) -> None:
        self._show_text = show
        self._refresh_text()

    def _refresh_text(self) -> None:
        text = self._text if self._show_text else ""
        for item in self._items:
            item.set_text(text, self._style)

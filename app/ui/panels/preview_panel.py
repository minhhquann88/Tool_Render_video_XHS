from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QStyle,
    QVBoxLayout,
)

from app.ui.widgets.common import muted_label, title_label
from app.ui.widgets.video_canvas import VideoCanvas
from app.utils.timefmt import ms_to_clock


class PreviewPanel(QFrame):
    """Cột giữa: preview video, vùng làm mờ, điều khiển phát."""
    position_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(title_label("Xem trước"))
        self.info_label = muted_label()
        head.addWidget(self.info_label)
        head.addStretch()
        self.chk_show_sub = QCheckBox("Hiện sub mới")
        self.chk_show_sub.setChecked(True)
        head.addWidget(self.chk_show_sub)
        layout.addLayout(head)

        self.canvas = VideoCanvas()
        layout.addWidget(self.canvas, 1)

        controls = QHBoxLayout()
        self.btn_play = QPushButton()
        self.btn_play.setObjectName("IconButton")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.slider = QSlider(Qt.Horizontal)
        self.time_label = muted_label("00:00 / 00:00")
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        self.volume.setFixedWidth(80)
        controls.addWidget(self.btn_play)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        controls.addWidget(QLabel("🔊"))
        controls.addWidget(self.volume)
        layout.addLayout(controls)

        hint = muted_label("Space: phát/dừng · vùng mờ chỉ hiện đúng lúc câu sub xuất hiện")
        layout.addWidget(hint)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.7)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.canvas.video_item)

        self.btn_play.clicked.connect(self.toggle_play)
        self.chk_show_sub.toggled.connect(self.canvas.set_show_text)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.volume.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.canvas.video_item.nativeSizeChanged.connect(
            lambda s: self.info_label.setText(f"{int(s.width())}×{int(s.height())}") if s.width() > 0 else None)
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play)

        self.set_video_enabled(False)

    @property
    def duration_ms(self) -> int:
        return self.player.duration()

    @property
    def position_ms(self) -> int:
        return self.player.position()

    def load(self, path: Path | None) -> None:
        self.player.stop()
        if path:
            self.player.setSource(QUrl.fromLocalFile(str(path)))
        else:
            self.player.setSource(QUrl())
            self.info_label.setText("")
        self.canvas.set_has_video(path is not None)
        self.set_video_enabled(path is not None)

    def set_video_enabled(self, enabled: bool) -> None:
        for w in (self.btn_play, self.slider):
            w.setEnabled(enabled)

    def toggle_play(self) -> None:
        if self.player.source().isEmpty():
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, ms: int) -> None:
        self.player.setPosition(ms)

    def _on_position(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time_label.setText(f"{ms_to_clock(ms)} / {ms_to_clock(self.player.duration())}")
        self.position_changed.emit(ms)

    def _on_duration(self, ms: int) -> None:
        self.slider.setRange(0, ms)
        self.time_label.setText(f"{ms_to_clock(self.player.position())} / {ms_to_clock(ms)}")

    def _on_state(self, state) -> None:
        icon = QStyle.SP_MediaPause if state == QMediaPlayer.PlayingState else QStyle.SP_MediaPlay
        self.btn_play.setIcon(self.style().standardIcon(icon))

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QStyle, QVBoxLayout

from app.ui.widgets.common import Segmented, muted_label, title_label
from app.ui.widgets.video_canvas import VideoCanvas
from app.utils.timefmt import ms_to_clock


class PreviewPanel(QFrame):
    """Cột giữa: preview video, vùng làm mờ, điều khiển phát."""
    position_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(title_label("Xem trước"))
        self.info_label = muted_label()
        head.addWidget(self.info_label)
        head.addStretch()
        self.view = Segmented([("Bản gốc", "orig"), ("Kết quả", "result")])
        self.view.set_value("result")
        self.view.setToolTip("Kết quả: hiện vùng che và sub mới như khi xuất video")
        head.addWidget(self.view)
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


        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.7)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.canvas.video_item)
        # tiếng đã ghép giọng AI (nghe thử): phát song song, bám theo vị trí của video, thay tiếng gốc ở chế độ Kết quả
        self.dub = QMediaPlayer(self)
        self.dub_audio = QAudioOutput(self)
        self.dub_audio.setVolume(0.7)
        self.dub.setAudioOutput(self.dub_audio)
        self._dub_path: Path | None = None

        self.btn_play.clicked.connect(self.toggle_play)
        self.view.changed.connect(self._on_view)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.volume.valueChanged.connect(lambda v: (self.audio.setVolume(v / 100), self.dub_audio.setVolume(v / 100)))
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
        self.set_dub_audio(None)
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
        if self._dub_path:
            self.dub.setPosition(ms)

    # ----- nghe thử giọng AI -----
    @property
    def dub_path(self) -> Path | None:
        return self._dub_path

    def set_dub_audio(self, path: Path | None) -> None:
        """Gắn tiếng đã ghép giọng AI (None = bỏ, quay về tiếng gốc của video)."""
        self._dub_path = path
        self.dub.stop()
        self.dub.setSource(QUrl())
        if path:
            self.dub.setSource(QUrl.fromLocalFile(str(path)))
            self.dub.setPosition(self.player.position())
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                self.dub.play()
        self._apply_audio()

    def show_result(self) -> None:
        self.view.set_value("result")
        self._on_view("result")

    def _dub_active(self) -> bool:
        return self._dub_path is not None and self.view.value() == "result"

    def _apply_audio(self) -> None:
        on = self._dub_active()
        self.audio.setMuted(on)
        self.dub_audio.setMuted(not on)

    def _on_view(self, value) -> None:
        self.canvas.set_show_overlays(value == "result")
        self._apply_audio()

    def _on_position(self, ms: int) -> None:
        if self._dub_path and self.dub.playbackState() == QMediaPlayer.PlayingState                 and abs(self.dub.position() - ms) > 250:
            self.dub.setPosition(ms)  # lệch (tua / giật hình) -> kéo tiếng về khớp hình
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time_label.setText(f"{ms_to_clock(ms)} / {ms_to_clock(self.player.duration())}")
        self.position_changed.emit(ms)

    def _on_duration(self, ms: int) -> None:
        self.slider.setRange(0, ms)
        self.time_label.setText(f"{ms_to_clock(self.player.position())} / {ms_to_clock(ms)}")

    def _on_state(self, state) -> None:
        if self._dub_path:
            if state == QMediaPlayer.PlayingState:
                self.dub.setPosition(self.player.position())
                self.dub.play()
            else:
                self.dub.pause()
        icon = QStyle.SP_MediaPause if state == QMediaPlayer.PlayingState else QStyle.SP_MediaPlay
        self.btn_play.setIcon(self.style().standardIcon(icon))

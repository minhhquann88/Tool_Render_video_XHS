from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.services.tts.base import TTSProvider
from app.ui.steps.base import DONE, IDLE, RUNNING
from app.ui.steps.detect import DetectBody
from app.ui.steps.export import ExportBody
from app.ui.steps.translate import TranslateBody
from app.ui.steps.voice import VoiceBody
from app.ui.tasks import TaskRunner
from app.ui.theme import accent
from app.ui.widgets.common import ClickableFrame, set_prop, title_label
from app.ui.workflow import DETECT, EXPORT, GOALS, ORDER, STEPS, TITLES, TRANSLATE, VOICE, StepInfo


class GoalCard(ClickableFrame):
    def __init__(self, title: str, desc: str, n_steps: int, parent=None):
        super().__init__(parent)
        self.setObjectName("Goal")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        name = QLabel(title)
        name.setObjectName("GoalTitle")
        about = QLabel(desc)
        about.setObjectName("GoalDesc")
        about.setWordWrap(True)
        self.count = QLabel(f"{n_steps} bước")
        self.count.setObjectName("GoalCount")
        layout.addWidget(name)
        layout.addWidget(about)
        layout.addStretch()
        layout.addWidget(self.count)

    def set_selected(self, selected: bool) -> None:
        set_prop(self, "selected", selected)
        set_prop(self.count, "selected", selected)


class StepCard(QFrame):
    """Một bước dạng gập / mở: đầu bước (số, tên, trạng thái) + thân bước."""
    toggled = Signal()

    def __init__(self, title: str, body: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("StepCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.head = ClickableFrame()
        self.head.setObjectName("StepHead")
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(12)
        self.badge = QLabel()
        self.badge.setObjectName("Badge")
        self.badge.setFixedSize(28, 28)
        self.badge.setAlignment(Qt.AlignCenter)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("StepTitle")
        self.status = QLabel()
        self.status.setObjectName("StepStatus")
        self.status.setWordWrap(True)
        texts.addWidget(self.title)
        texts.addWidget(self.status)
        self.chevron = QLabel()
        self.chevron.setObjectName("Muted")
        hl.addWidget(self.badge, 0, Qt.AlignTop)
        hl.addLayout(texts, 1)
        hl.addWidget(self.chevron)
        layout.addWidget(self.head)
        self.body = body
        layout.addWidget(body)
        self.head.clicked.connect(self.toggled)

    def set_info(self, n: int, info: StepInfo, is_open: bool) -> None:
        running = info.tone == "run"
        self.badge.setText("✓" if info.done else str(n))
        set_prop(self.badge, "state", "done" if info.done else "run" if running else "open" if is_open else "")
        self.status.setText(info.status)
        set_prop(self.status, "tone", info.tone)
        set_prop(self, "open", is_open)
        self.chevron.setText("▴" if is_open else "▾")
        self.body.setVisible(is_open)


class WorkflowPanel(QFrame):
    """Cột phải: chọn mục tiêu -> các bước cần làm (gập / mở) -> làm tự động."""
    goal_changed = Signal(str)
    auto_requested = Signal()
    auto_all_requested = Signal()

    def __init__(self, providers: dict[str, TTSProvider], runner: TaskRunner, log, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(460)  # đủ chỗ cho phần mở rộng của các bước (đo bằng font Segoe UI)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        head = QWidget()
        hv = QVBoxLayout(head)
        hv.setContentsMargins(16, 16, 16, 12)
        hv.setSpacing(10)
        hv.addWidget(title_label("Bạn muốn làm gì với video này?"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.goals: dict[str, GoalCard] = {}
        for col, (gid, name, desc) in enumerate(GOALS):
            g = GoalCard(name, desc, len(ORDER[gid]))
            g.clicked.connect(lambda gid=gid: self.goal_changed.emit(gid))
            grid.addWidget(g, 0, col)
            self.goals[gid] = g
        hv.addLayout(grid)
        layout.addWidget(head)
        line = QFrame()
        line.setObjectName("Separator")
        line.setFixedHeight(1)
        layout.addWidget(line)

        self.detect = DetectBody()
        self.translate = TranslateBody()
        self.voice = VoiceBody(providers, runner, log)
        self.export = ExportBody()
        self.bodies = {DETECT: self.detect, TRANSLATE: self.translate, VOICE: self.voice, EXPORT: self.export}
        self.cards: dict[str, StepCard] = {}
        steps = QWidget()
        sv = QVBoxLayout(steps)
        sv.setContentsMargins(16, 14, 16, 14)
        sv.setSpacing(10)
        for key in STEPS:
            card = StepCard(TITLES[key], self.bodies[key])
            card.toggled.connect(lambda key=key: self.set_open(None if self._open == key else key))
            sv.addWidget(card)
            self.cards[key] = card
        sv.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(steps)
        layout.addWidget(scroll, 1)

        bar = QFrame()
        bar.setObjectName("AutoBar")
        bv = QVBoxLayout(bar)
        bv.setContentsMargins(16, 12, 16, 16)
        bv.setSpacing(8)
        self.btn_auto = accent(QPushButton("Làm tự động từ đầu đến cuối"))
        self.btn_auto.setObjectName("Big")
        self.btn_auto.setToolTip("Chạy lần lượt các bước còn lại, chỉ dừng khi cần bạn nhập gì đó")
        self.btn_all = QPushButton("Làm cho cả danh sách")
        self.btn_all.setToolTip("Áp dụng mục tiêu này cho mọi video đã tải rồi chạy lần lượt từng video")
        bv.addWidget(self.btn_auto)
        bv.addWidget(self.btn_all)
        layout.addWidget(bar)

        self.btn_auto.clicked.connect(self.auto_requested)
        self.btn_all.clicked.connect(self.auto_all_requested)
        self._open: str | None = DETECT
        self._order: list[str] = list(STEPS)
        self._infos: dict[str, StepInfo] = {}

    @property
    def open_step(self) -> str | None:
        return self._open

    def set_open(self, key: str | None) -> None:
        self._open = key
        self._render_cards()

    def set_goal(self, goal: str | None) -> None:
        for gid, card in self.goals.items():
            card.set_selected(gid == goal)

    def set_steps(self, order: list[str], infos: dict[str, StepInfo], busy_step: str | None,
                  progress: tuple[int, str], waiting: bool = False) -> None:
        self._order = order
        self._infos = infos
        for key, body in self.bodies.items():
            info = infos.get(key)
            if busy_step == key:
                body.set_phase(RUNNING, progress, waiting)
            else:
                body.set_phase(DONE if info and info.done else IDLE)
        self._render_cards()

    def set_progress(self, key: str, pct: int, msg: str) -> None:
        self.bodies[key].progress.update(pct, msg)

    def _render_cards(self) -> None:
        for key, card in self.cards.items():
            shown = key in self._order and key in self._infos
            card.setVisible(shown)
            if shown:
                card.set_info(self._order.index(key) + 1, self._infos[key], self._open == key)

    def set_empty(self, empty: bool) -> None:
        """Chưa chọn video: ẩn các bước."""
        for card in self.cards.values():
            card.setEnabled(not empty)
        for g in self.goals.values():
            g.setEnabled(not empty)
        if empty:
            self._infos = {}
            self._render_cards()

    def set_auto(self, text: str, enabled: bool, all_text: str, all_enabled: bool) -> None:
        self.btn_auto.setText(text)
        self.btn_auto.setEnabled(enabled)
        self.btn_all.setText(all_text)
        self.btn_all.setEnabled(all_enabled)

from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFontComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QWidget,
)

from app.models import SubStyle, TranslateSettings
from app.ui.steps.base import StepBody
from app.ui.widgets.common import ColorButton, LabeledSlider, ghost, muted_label

# tên tiếng Anh đưa thẳng vào prompt của subtrans
LANGUAGES = [("Tiếng Trung", "Chinese"), ("Tiếng Việt", "Vietnamese"), ("Tiếng Anh", "English"),
             ("Tiếng Nhật", "Japanese"), ("Tiếng Hàn", "Korean"), ("Tiếng Thái", "Thai")]
# mẫu chữ nhanh: (tên, màu chữ, viền, có khung nền)
PRESETS = [("Trắng viền đen", "#FFFFFF", "#000000", False), ("Vàng", "#FFD84A", "#000000", False),
           ("Nền đen", "#FFFFFF", "#000000", True)]


class TranslateBody(StepBody):
    """Bước dịch sub gốc -> sub mới, kèm kiểu chữ của sub mới."""
    run_requested = Signal()
    edit_requested = Signal()
    settings_requested = Signal()
    style_changed = Signal()
    target_changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Dịch tự động", parent)

        defaults = TranslateSettings()
        self.src_combo = QComboBox()
        self.tgt_combo = QComboBox()
        for combo, value in ((self.src_combo, defaults.source_lang), (self.tgt_combo, defaults.target_lang)):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            for label, lang in LANGUAGES:
                combo.addItem(label, lang)
            combo.setCurrentIndex(combo.findData(value))
        lang_row = QHBoxLayout()
        lang_row.addWidget(self.src_combo, 1)
        lang_row.addWidget(muted_label("→"))
        lang_row.addWidget(self.tgt_combo, 1)
        self.top.addLayout(lang_row)

        self.key_warning = QFrame()
        self.key_warning.setObjectName("WarnBox")
        kw = QHBoxLayout(self.key_warning)
        kw.setContentsMargins(14, 10, 10, 10)
        warn_text = QLabel("Bước này cần Gemini API key (miễn phí).")
        warn_text.setObjectName("WarnText")
        warn_text.setWordWrap(True)
        self.btn_add_key = QPushButton("Thêm key")
        kw.addWidget(warn_text, 1)
        kw.addWidget(self.btn_add_key)
        self.top.addWidget(self.key_warning)

        self.btn_edit_idle = QPushButton("Xem && sửa sub")
        self.idle_row.addWidget(self.btn_edit_idle)
        self.btn_edit = QPushButton("Xem && sửa sub")
        self.btn_retranslate = ghost(QPushButton("Dịch lại"))
        self.done_row.addWidget(self.btn_edit)
        self.done_row.addWidget(self.btn_retranslate)

        self.add_advanced("Kiểu chữ && tuỳ chọn dịch", self._build_style())

        self.btn_run.clicked.connect(self.run_requested)
        self.btn_retranslate.clicked.connect(self.run_requested)
        self.btn_edit.clicked.connect(self.edit_requested)
        self.btn_edit_idle.clicked.connect(self.edit_requested)
        self.btn_add_key.clicked.connect(self.settings_requested)
        self.tgt_combo.currentIndexChanged.connect(lambda _: self.target_changed.emit())

    def _build_style(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)

        presets = QHBoxLayout()
        self._preset_group = QButtonGroup(self)
        for i, (name, color, outline, bg) in enumerate(PRESETS):
            btn = QPushButton(name)
            btn.setObjectName("Preset")
            btn.setCheckable(True)
            self._preset_group.addButton(btn, i)
            presets.addWidget(btn)
        presets.addStretch()
        self._preset_group.idClicked.connect(self._apply_preset)

        self.font_combo = QFontComboBox()
        self.font_combo.setEditable(False)  # bấm là mở danh sách font, không phải ô gõ chữ
        self.font_combo.setCurrentFont(QFont("Arial"))
        self.font_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.font_combo.setMinimumContentsLength(10)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(12, 200)
        self.size_spin.setValue(56)
        self.size_spin.setSuffix(" px")
        self.bold_check = QCheckBox("Đậm")
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

        self.bg_combo = QComboBox()
        self.bg_combo.addItem("Trong suốt", False)
        self.bg_combo.addItem("Có màu", True)
        self.bg_color_btn = ColorButton("#000000")
        self.bg_opacity = LabeledSlider(10, 100, 60, "%")
        self.bg_opacity.setToolTip("Độ đậm của khung nền")
        bg_row = QHBoxLayout()
        bg_row.addWidget(self.bg_combo)
        bg_row.addWidget(self.bg_color_btn)
        bg_row.addWidget(self.bg_opacity, 1)

        self.fit_check = QCheckBox("Dịch ngắn gọn vừa thời lượng câu")
        self.fit_check.setToolTip("Câu dịch quá dài so với thời gian câu sub thì nhờ Gemini rút gọn, "
                                  "để giọng đọc khớp hình hơn")
        self.fit_check.setChecked(TranslateSettings().fit_duration)
        # nhãn nằm trên ô: cột phải hẹp, nhãn bên trái làm ô bị đẩy tràn ra ngoài
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setVerticalSpacing(6)

        form.addRow("Mẫu chữ", presets)
        form.addRow("Font", self.font_combo)
        form.addRow("Cỡ chữ", size_row)
        form.addRow("Màu chữ", color_row)
        form.addRow("Nền", bg_row)
        form.addRow(self.fit_check)

        for signal in (self.font_combo.currentFontChanged, self.size_spin.valueChanged, self.bold_check.toggled,
                       self.color_btn.color_changed, self.outline_btn.color_changed,
                       self.bg_color_btn.color_changed, self.bg_opacity.value_changed):
            signal.connect(self._on_style)
        self.bg_combo.currentIndexChanged.connect(self._on_bg_mode)
        self._on_bg_mode()
        return box

    # ----- kiểu chữ -----
    def _apply_preset(self, i: int) -> None:
        _, color, outline, bg = PRESETS[i]
        self.color_btn.set_color(color)
        self.outline_btn.set_color(outline)
        self.bg_combo.setCurrentIndex(self.bg_combo.findData(bg))
        self._on_bg_mode()

    def _on_bg_mode(self) -> None:
        box = bool(self.bg_combo.currentData())
        self.bg_color_btn.setVisible(box)
        self.bg_opacity.setVisible(box)
        self.outline_btn.setEnabled(not box)  # có khung nền thì chữ không viền
        self._on_style()

    def _on_style(self, *_) -> None:
        s = self.sub_style()
        match = next((i for i, (_, c, o, bg) in enumerate(PRESETS)
                      if s.color == c and s.bg_box == bg and (bg or s.outline_color == o)), -1)
        self._preset_group.setExclusive(False)
        for btn in self._preset_group.buttons():
            btn.setChecked(self._preset_group.id(btn) == match)
        self._preset_group.setExclusive(True)
        self.style_changed.emit()

    def sub_style(self) -> SubStyle:
        return SubStyle(
            font_family=self.font_combo.currentFont().family(),
            font_size=self.size_spin.value(),
            color=self.color_btn.color(),
            outline_color=self.outline_btn.color(),
            bold=self.bold_check.isChecked(),
            bg_box=bool(self.bg_combo.currentData()),
            bg_color=self.bg_color_btn.color(),
            bg_opacity=self.bg_opacity.value(),
        )

    # ----- trạng thái -----
    def target_label(self) -> str:
        """vd "tiếng Việt" để ghép vào câu."""
        label = self.tgt_combo.currentText()
        return label[:1].lower() + label[1:]

    def set_state(self, can_run: bool, has_lines: bool, has_key: bool, summary: str) -> None:
        self.btn_run.setEnabled(can_run and has_lines and has_key)
        self.btn_retranslate.setEnabled(can_run and has_lines and has_key)
        self.btn_edit_idle.setVisible(has_lines)
        self.btn_edit.setEnabled(has_lines)
        self.key_warning.setVisible(not has_key)
        self.summary.setText(summary)

    def apply_to(self, settings: TranslateSettings) -> None:
        settings.source_lang = self.src_combo.currentData()
        settings.target_lang = self.tgt_combo.currentData()
        settings.fit_duration = self.fit_check.isChecked()

    # ----- lưu cài đặt -----
    def save_settings(self, qs: QSettings) -> None:
        qs.setValue("translate/source", self.src_combo.currentData())
        qs.setValue("translate/target", self.tgt_combo.currentData())
        qs.setValue("translate/fit_duration", self.fit_check.isChecked())
        s = self.sub_style()
        for key, value in vars(s).items():
            qs.setValue(f"style/{key}", value)

    def load_settings(self, qs: QSettings) -> None:
        d = TranslateSettings()
        for combo, key, value in ((self.src_combo, "translate/source", d.source_lang),
                                  (self.tgt_combo, "translate/target", d.target_lang)):
            idx = combo.findData(qs.value(key, value))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self.fit_check.setChecked(qs.value("translate/fit_duration", d.fit_duration, type=bool))
        s = SubStyle()
        self.font_combo.setCurrentFont(QFont(qs.value("style/font_family", s.font_family)))
        self.size_spin.setValue(int(qs.value("style/font_size", s.font_size)))
        self.bold_check.setChecked(qs.value("style/bold", s.bold, type=bool))
        self.color_btn.set_color(qs.value("style/color", s.color))
        self.outline_btn.set_color(qs.value("style/outline_color", s.outline_color))
        self.bg_color_btn.set_color(qs.value("style/bg_color", s.bg_color))
        self.bg_opacity.set_value(int(qs.value("style/bg_opacity", s.bg_opacity)))
        self.bg_combo.setCurrentIndex(self.bg_combo.findData(qs.value("style/bg_box", s.bg_box, type=bool)))
        self._on_bg_mode()

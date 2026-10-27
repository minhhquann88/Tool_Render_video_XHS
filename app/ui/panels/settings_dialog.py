from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from app.models import TranslateSettings
from app.services.translate.subtrans import MODEL_CHAIN
from app.services.upload.base import Uploader
from app.ui.theme import accent
from app.ui.widgets.common import ghost, muted_label, set_prop


class _Section(QFrame):
    """Một mục cài đặt: chấm trạng thái + tên + trạng thái, nội dung bên dưới."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 14, 14, 14)
        row.setSpacing(12)
        self.icon = QLabel()
        self.icon.setObjectName("StateIcon")
        self.icon.setFixedSize(22, 22)
        self.icon.setAlignment(Qt.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(8)
        head = QHBoxLayout()
        name = QLabel(title)
        name.setObjectName("StepTitle")
        self.state = QLabel()
        self.state.setObjectName("StepStatus")
        head.addWidget(name)
        head.addWidget(self.state, 1)
        col.addLayout(head)
        self.content = QVBoxLayout()
        self.content.setSpacing(8)
        col.addLayout(self.content)
        row.addWidget(self.icon, 0, Qt.AlignTop)
        row.addLayout(col, 1)

    def set_state(self, text: str, tone: str) -> None:
        """tone: ok | warn | "" (chưa dùng)."""
        self.state.setText(f"· {text}")
        set_prop(self.state, "tone", tone)
        set_prop(self.icon, "tone", tone)
        set_prop(self, "tone", tone)
        self.icon.setText("✓" if tone == "ok" else "!" if tone == "warn" else "")


class SettingsDialog(QDialog):
    """Cài đặt dùng chung cho mọi video: cookie XHS, Gemini API key, Google Drive."""
    cookie_file_requested = Signal()
    cookie_paste_requested = Signal()
    cookie_clear_requested = Signal()
    connect_requested = Signal(str, bool)  # uploader id, đổi sang tài khoản khác
    disconnect_requested = Signal(str)  # uploader id
    cancel_login_requested = Signal(str)  # uploader id
    reopen_login_requested = Signal(str)  # uploader id
    changed = Signal()

    def __init__(self, uploaders: dict[str, Uploader], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt")
        self.setMinimumWidth(560)
        self._account = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        # cookie
        self.cookie = _Section("Cookie Xiaohongshu")
        self.cookie_info = muted_label()
        self.cookie_info.setWordWrap(True)
        row = QHBoxLayout()
        self.btn_cookie_file = QPushButton("Chọn file cookie…")
        self.btn_cookie_paste = ghost(QPushButton("Dán chuỗi cookie"))
        self.btn_cookie_clear = ghost(QPushButton("Gỡ cookie"))
        row.addWidget(self.btn_cookie_file)
        row.addWidget(self.btn_cookie_paste)
        row.addWidget(self.btn_cookie_clear)
        row.addStretch()
        self.cookie.content.addWidget(self.cookie_info)
        self.cookie.content.addLayout(row)
        layout.addWidget(self.cookie)

        # Gemini
        self.gemini = _Section("Gemini API key")
        link = QLabel('Miễn phí, lấy tại <a href="https://aistudio.google.com/apikey" style="color:#7cb7ff">'
                      'aistudio.google.com/apikey</a>')
        link.setObjectName("Muted")
        link.setOpenExternalLinks(True)
        self.key_edit = QPlainTextEdit()
        self.key_edit.setPlaceholderText("Mỗi dòng 1 key (AQ… hoặc AIza…), app tự đổi sang key sau khi key trước hết lượt")
        self.key_edit.setFixedHeight(84)
        self.key_edit.setVisible(False)
        self.btn_keys = QPushButton("Sửa key")
        self.btn_keys.setCheckable(True)
        key_row = QHBoxLayout()
        key_row.addWidget(link, 1)
        key_row.addWidget(self.btn_keys)
        self.gemini.content.addLayout(key_row)
        self.gemini.content.addWidget(self.key_edit)
        layout.addWidget(self.gemini)

        # Drive
        self.drive = _Section("Google Drive")
        self.uploader_combo = QComboBox()
        for u in uploaders.values():
            self.uploader_combo.addItem(u.name, u.id)
        self.btn_connect = QPushButton("Kết nối Google")
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Thư mục trên Drive (trống = XHS Video Studio)")
        self.folder_edit.setToolTip("App chỉ ghi được vào thư mục do chính app tạo (quyền drive.file), "
                                    "nên nhập tên thư mục; app tự tạo nếu chưa có")
        self.btn_disconnect = ghost(QPushButton("Ngắt kết nối"))
        self.drive_wait = QWidget()  # đang chờ đăng nhập trên trình duyệt
        wait_row = QHBoxLayout(self.drive_wait)
        wait_row.setContentsMargins(0, 0, 0, 0)
        wait_label = QLabel("Đang chờ đăng nhập trên trình duyệt…")
        wait_label.setObjectName("WarnText")
        self.btn_reopen = QPushButton("Mở lại trang đăng nhập")
        self.btn_cancel_login = ghost(QPushButton("Huỷ"))
        wait_row.addWidget(wait_label, 1)
        wait_row.addWidget(self.btn_reopen)
        wait_row.addWidget(self.btn_cancel_login)
        self.drive_wait.setVisible(False)
        drive_row = QHBoxLayout()
        drive_row.addWidget(self.btn_connect)
        drive_row.addWidget(self.btn_disconnect)
        drive_row.addWidget(self.folder_edit, 1)
        self.drive.content.addLayout(drive_row)
        self.drive.content.addWidget(self.drive_wait)
        layout.addWidget(self.drive)

        # nâng cao
        self.advanced = QWidget()
        form = QFormLayout(self.advanced)
        form.setContentsMargins(0, 0, 0, 0)
        defaults = TranslateSettings()
        self.model_edit = QLineEdit(defaults.model)
        self.model_edit.setToolTip("Model bắt đầu. Thứ tự thử: " + " → ".join(MODEL_CHAIN) +
                                   "; mỗi model thử hết các key từ trên xuống rồi mới xuống model sau")
        self.skip_analysis_check = QCheckBox("Bỏ lượt phân tích ngữ cảnh khi dịch (nhanh hơn, kém nhất quán)")
        form.addRow("Model Gemini", self.model_edit)
        form.addRow(self.skip_analysis_check)
        if len(uploaders) > 1:  # chỉ cho chọn khi có nhiều nơi tải lên
            form.addRow("Nơi tải lên", self.uploader_combo)
        else:
            self.uploader_combo.setVisible(False)
        self.advanced.setVisible(False)
        layout.addWidget(self.advanced)

        foot = QHBoxLayout()
        self.btn_advanced = ghost(QPushButton("Nâng cao…"))
        self.btn_advanced.setCheckable(True)
        self.btn_close = accent(QPushButton("Xong"))
        foot.addStretch()
        foot.addWidget(self.btn_advanced)
        foot.addWidget(self.btn_close)
        layout.addLayout(foot)

        self.btn_cookie_file.clicked.connect(self.cookie_file_requested)
        self.btn_cookie_paste.clicked.connect(self.cookie_paste_requested)
        self.btn_cookie_clear.clicked.connect(self.cookie_clear_requested)
        self.btn_keys.toggled.connect(self._toggle_keys)
        self.key_edit.textChanged.connect(self._update_key_state)
        self.btn_connect.clicked.connect(lambda: self.connect_requested.emit(self.uploader_id(), bool(self._account)))
        self.btn_disconnect.clicked.connect(lambda: self.disconnect_requested.emit(self.uploader_id()))
        self.btn_reopen.clicked.connect(lambda: self.reopen_login_requested.emit(self.uploader_id()))
        self.btn_cancel_login.clicked.connect(lambda: self.cancel_login_requested.emit(self.uploader_id()))
        self.uploader_combo.currentIndexChanged.connect(lambda _: self.set_drive_account(""))
        self.btn_advanced.toggled.connect(self.advanced.setVisible)
        self.btn_close.clicked.connect(self.accept)
        self._update_key_state()
        self.set_drive_account("")

    def _toggle_keys(self, on: bool) -> None:
        self.key_edit.setVisible(on)
        self.btn_keys.setText("Ẩn key" if on else "Sửa key")

    # ----- trạng thái -----
    def set_cookie_state(self, text: str, ok: bool, path: str) -> None:
        self.cookie.set_state(text, "ok" if ok else "warn" if path else "")
        self.cookie_info.setText(f"Đang dùng {path}" if path else "Cần để tải video từ link.")
        self.btn_cookie_clear.setVisible(bool(path))

    def _update_key_state(self) -> None:
        n = len(self.api_keys())
        self.gemini.set_state(f"đã lưu {n} key" if n else "chưa có", "ok" if n else "warn")
        self.changed.emit()

    def set_drive_account(self, name: str) -> None:
        self._account = name
        self.drive.set_state(f"đã kết nối {name}" if name else "chưa kết nối", "ok" if name else "")
        self.btn_connect.setText("Đổi tài khoản" if name else "Kết nối Google")
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setVisible(bool(name))
        self.drive_wait.setVisible(False)
        self.changed.emit()

    def set_drive_connecting(self) -> None:
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setVisible(False)
        self.drive_wait.setVisible(True)

    @property
    def drive_account(self) -> str:
        return self._account

    def open_keys(self) -> None:
        self.btn_keys.setChecked(True)
        self.key_edit.setFocus()

    # ----- giá trị -----
    def api_keys(self) -> list[str]:
        return [k.strip() for k in self.key_edit.toPlainText().splitlines() if k.strip()]

    def apply_to(self, settings: TranslateSettings) -> None:
        settings.api_keys = self.api_keys()
        settings.model = self.model_edit.text().strip() or TranslateSettings().model
        settings.skip_analysis = self.skip_analysis_check.isChecked()

    def uploader_id(self) -> str:
        return self.uploader_combo.currentData()

    def drive_folder(self) -> str:
        return self.folder_edit.text().strip()

    # ----- lưu cài đặt -----
    def save_settings(self, qs: QSettings) -> None:
        qs.setValue("translate/gemini_model", self.model_edit.text().strip())
        qs.setValue("translate/gemini_keys", "\n".join(self.api_keys()))
        qs.setValue("translate/skip_analysis", self.skip_analysis_check.isChecked())
        qs.setValue("export/uploader", self.uploader_id())
        qs.setValue("export/drive_folder", self.drive_folder())

    def load_settings(self, qs: QSettings) -> None:
        d = TranslateSettings()
        saved_model = str(qs.value("translate/gemini_model", "") or "").strip()
        if saved_model in MODEL_CHAIN:  # model chuẩn -> bắt đầu từ đầu chuỗi; chỉ giữ model tự gõ ngoài chuỗi
            saved_model = ""
        self.model_edit.setText(saved_model or d.model)

        def valid(k: str) -> bool:  # lỡ lưu nhầm link / đoạn chữ vào ô key -> bỏ
            return bool(k) and "://" not in k and not any(c.isspace() for c in k)

        keys = [k.strip() for k in str(qs.value("translate/gemini_keys", "") or "").splitlines() if valid(k.strip())]
        if not keys:  # bản cũ lưu 1 key ở "translate/gemini_key" -> chuyển sang danh sách
            old = str(qs.value("translate/gemini_key", "") or "").strip()
            keys = [k for k in [old] if valid(k)]
        keys = list(dict.fromkeys(keys + d.api_keys))  # key mặc định còn thiếu -> thêm vào cuối
        self.key_edit.setPlainText("\n".join(keys))
        self.skip_analysis_check.setChecked(qs.value("translate/skip_analysis", False, type=bool))
        idx = self.uploader_combo.findData(qs.value("export/uploader"))
        if idx >= 0:
            self.uploader_combo.setCurrentIndex(idx)
        self.folder_edit.setText(qs.value("export/drive_folder", ""))

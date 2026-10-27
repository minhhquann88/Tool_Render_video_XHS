from abc import ABC, abstractmethod
from pathlib import Path

from app.services.common import ProgressFn, no_progress


class Uploader(ABC):
    id: str = ""
    name: str = ""

    @abstractmethod
    def connect(self, progress: ProgressFn = no_progress, switch_account: bool = False) -> str:
        """Đăng nhập, trả về tên tài khoản. switch_account: bỏ phiên đã lưu, cho chọn tài khoản khác."""

    def current_account(self, progress: ProgressFn = no_progress) -> str:
        """Tài khoản đã đăng nhập từ trước (không mở trình duyệt); chưa đăng nhập -> ""."""
        return ""

    def disconnect(self) -> None:
        """Quên phiên đăng nhập đã lưu."""

    def cancel_login(self) -> None:
        """Dừng chờ đăng nhập đang diễn ra (connect sẽ báo lỗi "đã huỷ")."""

    def reopen_login(self) -> None:
        """Mở lại trang đăng nhập đang chờ."""

    @abstractmethod
    def upload(self, file_path: Path, folder: str, progress: ProgressFn = no_progress) -> str:
        """Upload file, trả về link chia sẻ."""

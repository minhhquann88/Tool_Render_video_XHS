from abc import ABC, abstractmethod
from pathlib import Path

from app.services.common import ProgressFn, no_progress


class Uploader(ABC):
    id: str = ""
    name: str = ""

    @abstractmethod
    def connect(self, progress: ProgressFn = no_progress) -> str:
        """Đăng nhập, trả về tên tài khoản."""

    @abstractmethod
    def upload(self, file_path: Path, folder: str, progress: ProgressFn = no_progress) -> str:
        """Upload file, trả về link chia sẻ."""

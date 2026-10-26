import time
import uuid
from pathlib import Path

from app.services.common import ProgressFn, no_progress
from app.services.upload.base import Uploader


class MockUploader(Uploader):
    id = "mock"
    name = "Giả lập (demo)"

    def connect(self, progress: ProgressFn = no_progress) -> str:
        time.sleep(0.3)
        return "demo@local"

    def upload(self, file_path: Path, folder: str, progress: ProgressFn = no_progress) -> str:
        for i in range(20):
            time.sleep(0.05)
            progress((i + 1) * 5, f"Đang upload {file_path.name}")
        return f"https://drive.google.com/file/d/DEMO_{uuid.uuid4().hex[:12]}/view"

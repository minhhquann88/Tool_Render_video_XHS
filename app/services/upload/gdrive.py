from pathlib import Path

from app.services.common import ProgressFn, no_progress
from app.services.upload.base import Uploader


class GoogleDriveUploader(Uploader):
    id = "gdrive"
    name = "Google Drive"

    def connect(self, progress: ProgressFn = no_progress) -> str:
        # TODO: OAuth (google-auth-oauthlib) với credentials.json, lưu token.json
        raise NotImplementedError("kết nối Google Drive (OAuth)")

    def upload(self, file_path: Path, folder: str, progress: ProgressFn = no_progress) -> str:
        # TODO: googleapiclient MediaFileUpload(resumable=True), parents=[folder_id]
        raise NotImplementedError("upload Google Drive")

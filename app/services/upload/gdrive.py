"""Upload Google Drive qua OAuth (client_secret.json loại "Desktop app" đặt cạnh main.py).

- Quyền `drive.file`: app chỉ thấy file / thư mục do chính app tạo -> không cần Google kiểm duyệt khi phát hành,
  nhưng không ghi được vào thư mục người dùng tự tạo. Vì vậy "thư mục" là TÊN thư mục: app tự tìm / tạo.
- Đăng nhập lần đầu mở trình duyệt; token lưu ở data/gdrive_token.json. Project để chế độ Testing thì token hết
  hạn sau 7 ngày -> tự mở trình duyệt đăng nhập lại.
"""
from __future__ import annotations

import os
import re
import threading
import time
import webbrowser
import wsgiref.simple_server
import wsgiref.util
from pathlib import Path

from app.config import BASE_DIR, DATA_DIR
from app.services.common import ProgressFn, no_progress
from app.services.upload.base import Uploader

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = DATA_DIR / "gdrive_token.json"
DEFAULT_FOLDER = "XHS Video Studio"
LOGIN_TIMEOUT_S = 300
CHUNK_SIZE = 8 * 1024 * 1024
_FOLDER_MIME = "application/vnd.google-apps.folder"


def client_secret_file() -> Path | None:
    """client_secret.json / client_secret_*.json (tên Google đặt khi tải về) / credentials.json cạnh main.py."""
    for pattern in ("client_secret.json", "client_secret*.json", "credentials.json"):
        found = sorted(BASE_DIR.glob(pattern))
        if found:
            return found[0]
    return None


class GoogleDriveUploader(Uploader):
    id = "gdrive"
    name = "Google Drive"

    def __init__(self):
        self._creds = None
        self._lock = threading.Lock()  # đăng nhập 1 lần dù nhiều video upload liên tiếp
        self._cancel = threading.Event()
        self._auth_url = ""  # trang đăng nhập đang chờ, để mở lại

    def connect(self, progress: ProgressFn = no_progress, switch_account: bool = False) -> str:
        return self._account(self._service(progress, force_login=switch_account))

    def current_account(self, progress: ProgressFn = no_progress) -> str:
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not TOKEN_FILE.exists():
            return ""
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
            if not creds.valid:
                if not (creds.expired and creds.refresh_token):
                    return ""
                creds.refresh(Request())  # hết hạn / bị thu hồi -> coi như chưa đăng nhập, không mở trình duyệt
                self._save(creds)
        except (GoogleAuthError, ValueError, OSError):
            return ""
        from googleapiclient.discovery import build

        with self._lock:
            self._creds = creds
        return self._account(build("drive", "v3", credentials=creds, cache_discovery=False))

    def disconnect(self) -> None:
        with self._lock:
            self._creds = None
            TOKEN_FILE.unlink(missing_ok=True)

    @staticmethod
    def _account(service) -> str:
        user = service.about().get(fields="user(emailAddress,displayName)").execute().get("user", {})
        return user.get("emailAddress") or user.get("displayName") or "Google Drive"

    def upload(self, file_path: Path, folder: str, progress: ProgressFn = no_progress) -> str:
        from googleapiclient.http import MediaFileUpload

        service = self._service(progress)
        folder_id = self._folder_id(service, folder.strip())
        media = MediaFileUpload(str(file_path), mimetype="video/mp4", resumable=True, chunksize=CHUNK_SIZE)
        request = service.files().create(body={"name": file_path.name, "parents": [folder_id]},
                                          media_body=media, fields="id,webViewLink")
        response = None
        while response is None:  # upload từng phần: mạng chập chờn thì thư viện tự gửi lại phần lỗi
            status, response = request.next_chunk(num_retries=3)
            if status:
                progress(int(status.progress() * 100), f"Đang upload {file_path.name}")
        progress(100, "Upload xong")
        return response["webViewLink"]

    # ------------------------------------------------------------------ đăng nhập
    def _service(self, progress: ProgressFn = no_progress, force_login: bool = False):
        from googleapiclient.discovery import build

        with self._lock:
            self._creds = self._credentials(progress, force_login)
        return build("drive", "v3", credentials=self._creds, cache_discovery=False)

    def _credentials(self, progress: ProgressFn, force_login: bool):
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = self._creds
        if creds is None and TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds and creds.valid and not force_login:
            return creds
        if creds and creds.expired and creds.refresh_token and not force_login:
            try:
                creds.refresh(Request())
                self._save(creds)
                return creds
            except RefreshError:
                pass  # token hết hạn (Testing: 7 ngày) / bị thu hồi -> đăng nhập lại
        return self._login(progress, choose_account=force_login)

    def cancel_login(self) -> None:
        """Dừng chờ đăng nhập (vd. người dùng đã tắt trình duyệt)."""
        self._cancel.set()

    def reopen_login(self) -> None:
        """Mở lại trang đăng nhập Google đang chờ (lỡ tắt trình duyệt)."""
        if self._auth_url:
            webbrowser.open(self._auth_url, new=1, autoraise=True)

    def _login(self, progress: ProgressFn, choose_account: bool = False):
        """Như InstalledAppFlow.run_local_server nhưng chờ theo từng nhịp ngắn để huỷ / mở lại được."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        secret = client_secret_file()
        if secret is None:
            raise RuntimeError(f"chưa có client_secret.json (tải từ Google Cloud > Credentials, đặt vào {BASE_DIR})")
        progress(0, "Đang mở trình duyệt để đăng nhập Google…")
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
        received: list[str] = []

        def app(environ, start_response):  # Google chuyển trình duyệt về đây kèm mã đăng nhập
            if "code=" in environ.get("QUERY_STRING", "") or "error=" in environ.get("QUERY_STRING", ""):
                received.append(wsgiref.util.request_uri(environ))
            start_response("200 OK", [("Content-type", "text/html; charset=utf-8")])
            return ["Đã đăng nhập, có thể đóng tab này và quay lại app.".encode("utf-8")]

        class _QuietHandler(wsgiref.simple_server.WSGIRequestHandler):
            def log_message(self, *args):  # không in log truy cập ra console
                pass

        server = wsgiref.simple_server.make_server("localhost", 0, app, handler_class=_QuietHandler)
        self._cancel.clear()
        try:
            flow.redirect_uri = f"http://localhost:{server.server_port}/"
            # đổi tài khoản: Google hiện danh sách tài khoản thay vì tự dùng tài khoản đang đăng nhập trên trình duyệt
            extra = {"prompt": "select_account"} if choose_account else {}
            self._auth_url, _ = flow.authorization_url(**extra)
            webbrowser.open(self._auth_url, new=1, autoraise=True)
            server.timeout = 0.5
            deadline = time.monotonic() + LOGIN_TIMEOUT_S
            while not received:
                if self._cancel.is_set():
                    raise RuntimeError("đã huỷ đăng nhập Google")
                if time.monotonic() > deadline:
                    raise RuntimeError(f"không đăng nhập Google trong {LOGIN_TIMEOUT_S // 60} phút, bấm Kết nối để thử lại")
                server.handle_request()
        finally:
            server.server_close()
            self._auth_url = ""
        if "error=" in received[0] and "code=" not in received[0]:
            raise RuntimeError("chưa cấp quyền truy cập Google Drive cho app")
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # chuyển hướng về localhost là http
        flow.fetch_token(authorization_response=received[0].replace("http://", "https://", 1))
        creds = flow.credentials
        self._save(creds)
        return creds

    @staticmethod
    def _save(creds) -> None:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    # ------------------------------------------------------------------ thư mục
    @staticmethod
    def _folder_id(service, folder: str) -> str:
        """Link / ID thư mục do app tạo -> dùng luôn; còn lại coi là tên: tìm thư mục app đã tạo, chưa có thì tạo."""
        from googleapiclient.errors import HttpError

        link = re.search(r"/folders/([\w-]+)", folder)
        folder_id = link.group(1) if link else (folder if re.fullmatch(r"[\w-]{25,}", folder) else "")
        if folder_id:
            try:
                service.files().get(fileId=folder_id, fields="id").execute()
                return folder_id
            except HttpError as e:
                if e.resp.status == 404:
                    raise RuntimeError("app không có quyền ghi vào thư mục này (chỉ ghi được vào thư mục do app tạo). "
                                       "Nhập TÊN thư mục thay cho link, app sẽ tự tạo") from e
                raise
        name = folder or DEFAULT_FOLDER
        q = f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and mimeType = '{_FOLDER_MIME}' and trashed = false"
        found = service.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
        if found:
            return found[0]["id"]
        return service.files().create(body={"name": name, "mimeType": _FOLDER_MIME}, fields="id").execute()["id"]

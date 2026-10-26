import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.services.common import ProgressFn, no_progress

# Link trong đoạn share thường dính ký tự Trung / dấu câu full-width ở cuối
_URL_RE = re.compile(r"https?://[^\s，。！？、\"'<>【】（）]+")


def extract_urls(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for url in _URL_RE.findall(text):
        seen.setdefault(url.rstrip(".,;)"), None)
    return list(seen)


@dataclass
class ScrapedVideo:
    url: str
    title: str
    video_path: Path
    author: str = ""
    cover_path: Path | None = None


class VideoScraper(ABC):
    name: str = ""

    @abstractmethod
    def can_handle(self, url: str) -> bool: ...

    def set_cookies(self, cookies: dict[str, str]) -> None:
        """Nguồn nào cần đăng nhập thì override."""

    @abstractmethod
    def download(self, url: str, dest_dir: Path, progress: ProgressFn = no_progress) -> ScrapedVideo: ...

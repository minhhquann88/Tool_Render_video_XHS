from pathlib import Path

APP_NAME = "XHS Video Studio"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOWNLOAD_DIR = DATA_DIR / "downloads"
OUTPUT_DIR = DATA_DIR / "output"
CACHE_DIR = DATA_DIR / "cache"
TTS_CACHE_DIR = CACHE_DIR / "tts"
VSF_WORK_DIR = CACHE_DIR / "vsf"  # thư mục tạm của VideoSubFinder (RGBImages…)

# VideoSubFinder bản build sẵn (Windows x64): https://sourceforge.net/projects/videosubfinder/
VSF_EXE = BASE_DIR / "tools" / "VideoSubFinder" / "VideoSubFinderWXW.exe"

# cookie.txt đặt cạnh main.py được tự nạp khi chưa chọn file nào
DEFAULT_COOKIE_FILE = BASE_DIR / "cookie.txt"
PASTED_COOKIE_FILE = DATA_DIR / "xhs_cookie.txt"

VIDEO_FILTER = "Video (*.mp4 *.mov *.mkv *.webm *.avi)"


def ensure_dirs() -> None:
    for d in (DOWNLOAD_DIR, OUTPUT_DIR, TTS_CACHE_DIR, VSF_WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)

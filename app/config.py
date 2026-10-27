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

# Gemini API key mặc định, thử lần lượt từ trên xuống (sửa được ở bước Sub)
DEFAULT_GEMINI_API_KEYS = [
    "AQ.Ab8RN6LM75Q2M-878xfvCjU6CUX-yu-By9sNxIll46jElflJyA",
    "AQ.Ab8RN6J_qFzDeTxnkyj0txWs_IVJgBKOFtX0NzkXpZLpOv3mEw",
    "AQ.Ab8RN6IODEBUJ7z528Ukn6pXbU51XdHdG23bGIzPmLJv6HIniw",
    "AQ.Ab8RN6JpyNVBCvo2cZqy5_UFoDQutEep8lJZ6C8Msk9C3Xdh7A",
]
DEFAULT_GEMINI_API_KEY = DEFAULT_GEMINI_API_KEYS[0]

VIDEO_FILTER = "Video (*.mp4 *.mov *.mkv *.webm *.avi)"


def ensure_dirs() -> None:
    for d in (DOWNLOAD_DIR, OUTPUT_DIR, TTS_CACHE_DIR, VSF_WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)

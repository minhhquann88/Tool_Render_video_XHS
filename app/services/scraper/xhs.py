import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from app.services.common import ProgressFn, no_progress
from app.services.scraper.base import ScrapedVideo, VideoScraper

_PATTERNS = [
    re.compile(r"^https?://(www\.)?(xiaohongshu|rednote)\.com/(explore|discovery/item|user/profile/[0-9a-zA-Z]+)/[0-9a-zA-Z]+"),
    re.compile(r"^https?://(xhslink|xhslink\.rednote)\.com/"),
]
_NOTE_ID = re.compile(r"/(?:explore|discovery/item|user/profile/[0-9a-zA-Z]+)/([0-9a-zA-Z]{24})")
_STATE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", re.S)
# Cookie được gắn cho cả 2 tên miền (rednote = bản quốc tế, chung tài khoản)
_COOKIE_DOMAINS = (".xiaohongshu.com", ".rednote.com")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
_CHUNK = 256 * 1024
_RETRY_WAITS = (3, 8)  # giây chờ trước mỗi lần mở lại trang khi chưa có dữ liệu bài viết


class XhsScraper(VideoScraper):
    name = "Xiaohongshu"

    def __init__(self):
        self._cookies: dict[str, str] = {}

    def can_handle(self, url: str) -> bool:
        return any(p.match(url) for p in _PATTERNS)

    def set_cookies(self, cookies: dict[str, str]) -> None:
        self._cookies = dict(cookies)

    def _session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        for name, value in self._cookies.items():
            for domain in _COOKIE_DOMAINS:
                session.cookies.set(name, value, domain=domain, path="/")
        return session

    def download(self, url: str, dest_dir: Path, progress: ProgressFn = no_progress) -> ScrapedVideo:
        if not self._cookies:
            raise ValueError("chưa gắn cookie XHS (Cài đặt › Cookie Xiaohongshu)")
        session = self._session()

        progress(0, "Đang mở bài viết…")
        resp = session.get(url, timeout=20, allow_redirects=True)
        resp.raise_for_status()
        final_url = resp.url
        if _is_login(final_url) and "xiaohongshu.com" in urlparse(final_url).netloc:
            # Cookie RedNote không đăng nhập được bản Trung -> mở cùng bài trên rednote.com
            target = parse_qs(urlparse(final_url).query).get("redirectPath", [""])[0] or final_url
            parsed = urlparse(target)
            if _NOTE_ID.search(parsed.path):
                progress(0, "Chuyển sang rednote.com…")
                resp = session.get(parsed._replace(scheme="https", netloc="www.rednote.com").geturl(), timeout=20)
                resp.raise_for_status()
                final_url = resp.url
        if _is_login(final_url):
            raise ValueError("XHS yêu cầu xác minh / đăng nhập – cookie hết hạn hoặc bị chặn, hãy lấy cookie mới")

        match = _NOTE_ID.search(urlparse(final_url).path)
        if not match:
            raise ValueError(f"không đọc được ID bài viết từ {final_url}")
        note = _find_note(_parse_state(resp.text), match.group(1))
        for wait in _RETRY_WAITS:
            if note:
                break
            # XHS thỉnh thoảng trả trang không kèm dữ liệu bài (chặn tạm khi gọi dồn dập) -> chờ rồi mở lại
            progress(0, f"XHS chưa trả dữ liệu bài viết, thử lại sau {wait}s…")
            time.sleep(wait)
            resp = session.get(final_url, timeout=20)
            resp.raise_for_status()
            note = _find_note(_parse_state(resp.text), match.group(1))
        if not note:
            raise ValueError("XHS không trả dữ liệu bài viết sau nhiều lần thử"
                             f"{_server_error(_parse_state(resp.text))} — bài có thể đã bị xoá / ẩn, cookie không có "
                             "quyền xem, hoặc đang bị chặn tạm thời (đợi vài phút rồi bấm Tải lại)")
        if note.get("type") != "video":
            raise ValueError("bài viết này là ảnh, không phải video")

        title = (note.get("title") or note.get("desc") or match.group(1)).strip().splitlines()[0][:80]
        author = (note.get("user") or {}).get("nickname", "")
        dest_dir.mkdir(parents=True, exist_ok=True)
        out_path = dest_dir / f"{match.group(1)}.mp4"
        origin = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}/"
        errors = []
        for video_url in _stream_urls(note):
            try:
                _stream_to_file(session, video_url, out_path, origin, progress)
                return ScrapedVideo(url=url, title=title, video_path=out_path, author=author)
            except requests.RequestException as e:
                errors.append(str(e))
                progress(0, "Link lỗi, thử link dự phòng…")
        raise ValueError("không tải được từ mọi link video: " + " | ".join(errors))


def _is_login(url: str) -> bool:
    path = urlparse(url).path
    return "captcha" in path or "login" in path


def _parse_state(html: str) -> dict:
    match = _STATE.search(html)
    if not match:
        raise ValueError("không tìm thấy dữ liệu bài viết trong trang (có thể link thiếu xsec_token hoặc cookie hết hạn)")
    # Đây là object JS: đổi `undefined`, `new Set([...])`, `new Map()` sang JSON hợp lệ
    raw = re.sub(r"\bundefined\b", "null", match.group(1))
    raw = re.sub(r"new (?:Set|Map)\((\[[^\[\]]*\])?\)", lambda m: m.group(1) or "[]", raw)
    return json.loads(raw)


def _find_note(state: dict, note_id: str) -> dict:
    """Dữ liệu bài viết trong trang; trang không kèm dữ liệu -> {}."""
    detail_map = (state.get("note") or {}).get("noteDetailMap") or {}
    entry = detail_map.get(note_id) or next(iter(detail_map.values()), None)
    return (entry or {}).get("note") or {}


def _server_error(state: dict) -> str:
    """Lý do XHS ghi trong trang (serverRequestInfo), vd " (mã -510001: 笔记不存在)"."""
    info = (state.get("note") or {}).get("serverRequestInfo") or {}
    code, msg = info.get("errorCode"), (info.get("errMsg") or "").strip()
    if not code and not msg:
        return ""
    return f" (mã {code}: {msg})" if msg else f" (mã {code})"


def _stream_urls(note: dict) -> list[str]:
    """Mọi link video theo thứ tự ưu tiên: h264 > codec khác, nét hơn trước, link chính rồi link dự phòng."""
    video = note.get("video") or {}
    streams = (video.get("media") or {}).get("stream") or {}
    # Tên nhóm thay đổi theo bản web (h264/h265/av1 hoặc EF4/EF5…), nên duyệt hết
    items = [s for group in streams.values() if isinstance(group, list) for s in group if s.get("masterUrl")]
    items.sort(key=lambda s: (
        "264" in f"{s.get('videoCodec', '')}{s.get('streamDesc', '')}".lower() or s in (streams.get("h264") or []),
        (s.get("height") or 0) * (s.get("width") or 0),
    ), reverse=True)
    urls = [u for s in items for u in [s["masterUrl"], *(s.get("backupUrls") or [])]]
    key = (video.get("consumer") or {}).get("originVideoKey")
    if key:
        urls.append(f"https://sns-video-bd.xhscdn.com/{key}")
    if not urls:
        raise ValueError("không tìm thấy link video trong bài viết")
    return list(dict.fromkeys(urls))


def _stream_to_file(session: requests.Session, url: str, out_path: Path, referer: str,
                    progress: ProgressFn) -> None:
    tmp = out_path.with_suffix(".part")
    with session.get(url, stream=True, timeout=30, headers={"Referer": referer}) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with tmp.open("wb") as f:
            for chunk in resp.iter_content(_CHUNK):
                f.write(chunk)
                done += len(chunk)
                if total:
                    progress(int(done * 100 / total), f"Đang tải {done / 1e6:.1f}/{total / 1e6:.1f} MB")
    tmp.replace(out_path)

# XHS Video Studio

App desktop (Python + PySide6): cào video Xiaohongshu → làm mờ sub gốc → chèn sub mới → lồng tiếng AI → render → upload Google Drive.

## Chạy

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run.bat            # hoặc: .venv\Scripts\python main.py
```

## VideoSubFinder

Luồng tìm sub: `VideoSubFinderWXW.exe` (C++, CPU) quét video → mỗi câu sub một ảnh trong `RGBImages`
(tên file chứa start/end + vị trí ảnh cắt) → RapidOCR đọc chữ + box chữ → vùng mờ theo thời gian và
file `data/output/<video>.srt`. Chữ đứng yên suốt video (cảnh báo, watermark) thành vùng mờ toàn video,
không đưa vào sub.

Cần bản build sẵn Windows x64 (`VideoSubFinder_6.10_x64.zip` trên SourceForge), giải nén thư mục
`Release_x64` thành `tools/VideoSubFinder/`. Dải quét mặc định 3%–75% chiều cao tính từ đáy khung
(`VsfRapidPipeline(top=…, bottom=…)` trong `app/services/__init__.py`).

## Cookie XHS

Cần cookie đã đăng nhập để tải video. Nút **Cookie…** ở cột trái nhận:

- File Netscape `cookie.txt` (xuất từ extension "Get cookies.txt"), hoặc file JSON (Cookie-Editor)
- Chuỗi dán trực tiếp `a1=…; web_session=…`

`cookie.txt` đặt cạnh `main.py` được tự nạp khi mở app. Cookie `web_session` là bắt buộc. Cookie của rednote.com không đăng nhập được xiaohongshu.com, nên link xiaohongshu / xhslink sẽ tự chuyển sang rednote.com.

⚠️ Cookie là phiên đăng nhập tài khoản – không chia sẻ / commit file này.

## Trạng thái các chức năng

| Bước | Trạng thái | File |
|---|---|---|
| Dán link / lọc link XHS | ✅ chạy thật | `app/services/scraper/base.py` |
| Tải video XHS / RedNote (dùng cookie) | ✅ chạy thật | `app/services/scraper/xhs.py`, `cookies.py` |
| Preview video, vùng mờ kéo/co giãn | ✅ chạy thật | `app/ui/widgets/video_canvas.py` |
| Tự động tìm vùng sub (VideoSubFinder + RapidOCR) | ✅ chạy thật | `app/services/subtitle/vsf_pipeline.py`, `vsf.py` |
| Sub gốc (OCR → .srt) / sửa / nhập-xuất .srt | ✅ OCR thật · dịch / Whisper chờ chốt | `app/services/subtitle/` |
| Danh sách voice AI + nghe thử | ✅ Edge-TTS thật | `app/services/tts/edge.py` |
| Tạo audio lồng tiếng từng dòng sub | ✅ Edge-TTS thật | `app/ui/main_window.py` |
| Render (blur + sub + voice) | 🧪 giả lập · FFmpeg chờ làm | `app/services/render/` |
| Upload Google Drive | 🧪 giả lập · OAuth chờ làm | `app/services/upload/` |

## Mở rộng

Mỗi chức năng là một interface (`base.py`) + các implementation. Thêm nguồn mới:

1. Tạo class kế thừa interface tương ứng, ví dụ `class ElevenLabsProvider(TTSProvider)` trong `app/services/tts/`.
2. Đăng ký 1 dòng trong `build_services()` ở `app/services/__init__.py`.

UI tự hiển thị nguồn mới trong combo box tương ứng.

Mọi hàm service nhận tham số `progress(pct, msg)` và chạy ở thread nền qua `TaskRunner` (`app/ui/tasks.py`); lỗi `NotImplementedError` được hiện thành "Chưa hỗ trợ: …" trong log.

## Cấu trúc

```
main.py
app/
  config.py, models.py
  services/   scraper · subtitle · tts · render · upload
  ui/         main_window.py, tasks.py, theme.py
    panels/   queue · preview · subtitle · voice · export
    widgets/  video_canvas.py, common.py
  utils/      timefmt.py, srt.py
data/         downloads · output · cache/tts   (tự tạo khi chạy)
```

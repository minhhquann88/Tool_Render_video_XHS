# XHS Video Studio

App desktop (Python + PySide6): cào video Xiaohongshu → làm mờ sub gốc → chèn sub mới → lồng tiếng AI → render → upload Google Drive.

## Cách dùng

Cột trái: dán link XHS → **Thêm & tải về** (hoặc **Mở file…**). Cột phải chọn mục tiêu cho video, app chỉ hiện các bước cần cho mục tiêu đó:

| Mục tiêu | Các bước |
|---|---|
| Chỉ che sub | Tìm & che sub gốc → Xuất video |
| Thêm sub Việt | Tìm & che sub gốc → Dịch sub → Xuất video |
| Việt hoá trọn gói | Tìm & che sub gốc → Dịch sub → Lồng tiếng AI → Xuất video |

Bấm từng bước, hoặc **Làm tự động** để chạy lần lượt các bước còn lại (**Làm cho cả N video** áp dụng cho cả danh sách).
**Xem & sửa sub** mở trình sửa sub toàn cửa sổ: sửa câu, chỉnh thời gian, xoá câu, dịch lại hoặc rút gọn câu quá dài.
Cookie XHS, Gemini API key và Google Drive nằm trong **Cài đặt** (góc trên phải).

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

Cần cookie đã đăng nhập để tải video. **Cài đặt › Cookie Xiaohongshu** nhận:

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
| Sub gốc (OCR → .srt) / sửa | ✅ OCR thật | `app/services/subtitle/` |
| Dịch sub gốc → sub mới (subtrans, Gemini 2 lượt) | ✅ cần Gemini API key (aistudio.google.com/apikey) | `app/services/translate/subtrans.py`, `app/vendor/subtrans/` |
| Danh sách voice AI + nghe thử | ✅ VieNeu-TTS v3 Turbo (offline) | `app/services/tts/vieneu.py` |
| Tạo audio lồng tiếng từng dòng sub | ✅ VieNeu-TTS v3 Turbo (offline) | `app/ui/main_window.py` |
| Render: che sub / chèn sub mới / ghép giọng (bật tắt từng phần) | ✅ FFmpeg thật (imageio-ffmpeg) | `app/services/render/ffmpeg.py` |
| Upload Google Drive | ✅ OAuth (client_secret.json cạnh main.py), quyền drive.file | `app/services/upload/gdrive.py` |

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
  services/   scraper · subtitle · translate · tts · render · upload
  ui/         main_window.py, workflow.py (mục tiêu → bước, trạng thái bước), tasks.py, theme.py
    panels/   queue · preview · workflow_panel · sub_editor · settings_dialog
    steps/    thân từng bước: detect · translate · voice · export
    widgets/  video_canvas.py, common.py
  utils/      timefmt.py, srt.py
  vendor/     subtrans (bản chép có sửa từ github.com/lepinkainen/subtrans, GPL-3)
data/         downloads · output · cache/tts   (tự tạo khi chạy)
```

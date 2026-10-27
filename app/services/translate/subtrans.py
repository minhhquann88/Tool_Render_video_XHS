"""Dịch bằng subtrans (bản chép trong app/vendor/subtrans, có sửa riêng) chạy trên Google Gemini, 2 lượt:

1. Phân tích toàn bộ sub -> ngữ cảnh (tên nhân vật, địa danh, thuật ngữ, giọng văn).
2. Dịch theo lô, dựa vào ngữ cảnh đó để dịch nhất quán.

subtrans viết cho thư viện `openai`; Gemini có endpoint tương thích OpenAI nên chỉ cần đổi base_url.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from app.config import BASE_DIR, DEFAULT_GEMINI_API_KEYS
from app.models import SubtitleLine, TranslateSettings
from app.services.common import ProgressFn, no_progress
from app.services.translate.base import Translator

VENDOR_DIR = BASE_DIR / "app" / "vendor"  # chứa gói subtrans (GPL-3, xem LICENSE.md trong đó)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
API_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _load_subtrans():
    if not (VENDOR_DIR / "subtrans").is_dir():
        raise NotImplementedError(f"chưa có subtrans ({VENDOR_DIR / 'subtrans'})")
    if str(VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(VENDOR_DIR))
    from subtrans.processing import translator
    return translator


# Thứ tự thử: hết model này trên mọi key mới xuống model sau. Model chọn ở UI là điểm bắt đầu trong chuỗi.
MODEL_CHAIN = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite")
REQUEST_TIMEOUT = 60   # giây / lần gọi; 3.6-flash dịch 1 lô 50 câu ~10-40s, quá mức này coi như model đang treo
MODEL_DOWN_S = 600     # model quá tải / treo -> các lần dịch sau bỏ qua model đó chừng này giây
RATE_LIMIT_MAX_WAIT = 65  # 429 bảo chờ ít hơn mức này = giới hạn / phút (chờ được); lâu hơn = hết lượt / ngày
RATE_LIMIT_ROUNDS = 3     # mọi key đều đang bị giới hạn / phút -> chờ rồi thử lại tối đa chừng này vòng


def _retry_delay(e: Exception) -> float | None:
    """Số giây Google bảo chờ trong lỗi 429 (RetryInfo.retryDelay hoặc 'Please retry in 1h2m3s')."""
    text = json.dumps(getattr(e, "body", None) or "", ensure_ascii=False) + str(e)
    m = re.search(r'"retryDelay":\s*"([\d.]+)s"', text)
    if m:
        return float(m.group(1))
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", text)
    if m:
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s)
    return None


def model_chain(first: str) -> list[str]:
    """Model bắt đầu + các model sau nó trong MODEL_CHAIN (model lạ thì thử nó trước rồi cả chuỗi)."""
    rest = MODEL_CHAIN[MODEL_CHAIN.index(first) + 1:] if first in MODEL_CHAIN else MODEL_CHAIN
    return [first, *[m for m in rest if m != first]]


# Nhớ giữa các lần dịch (cùng phiên app): (model, key) -> time.monotonic() lúc dùng lại được.
# Model treo / key hết lượt trong ngày thì lần bấm dịch sau đi thẳng tới cặp còn dùng được, khỏi chờ timeout lại.
_DOWN: dict[tuple[str, str], float] = {}


class _GeminiClient:
    """Bọc các client OpenAI trỏ tới Gemini (mỗi key một client) cho subtrans dùng như `client.chat.completions`.

    - bỏ `service_tier` (tham số riêng của OpenAI) trước khi gửi;
    - thử theo thứ tự model x key: model đầu với key 1, 2, ... rồi mới xuống model sau;
    - nhớ cặp (model, key) đã hỏng (trong lượt này và qua _DOWN cho các lần dịch sau) để đi thẳng tới cặp còn dùng được;
    - ghi lại lỗi: subtrans gặp lỗi thì lặng lẽ giữ nguyên chữ gốc, không báo ra ngoài.
    """

    def __init__(self, clients: list, models: list[str], log=None, keys: list[str] | None = None):
        self.chat = self
        self.completions = self
        self._clients = clients            # client thứ i dùng key thứ i
        self._keys = keys or [str(i) for i in range(len(clients))]  # để nhớ vào _DOWN
        self._models = models
        self._log = log or (lambda msg: None)
        self._dead: set[tuple[str, int]] = set()   # (model, key) không dùng nữa trong lượt này
        self._cool: dict[tuple[str, int], float] = {}  # (model, key) đang bị giới hạn / phút -> thời điểm gọi lại được
        self.errors: list[str] = []

    def _label(self, k: int) -> str:
        return f"key {k + 1}/{len(self._clients)}" if len(self._clients) > 1 else "key"

    def create(self, **kwargs):
        from openai import APIStatusError, APITimeoutError

        kwargs.pop("service_tier", None)
        kwargs.pop("model", None)  # subtrans luôn gửi model chọn ở UI; thứ tự thử do _models quyết định
        kwargs["timeout"] = min(kwargs.get("timeout") or REQUEST_TIMEOUT, REQUEST_TIMEOUT)
        last: Exception | None = None
        now = time.monotonic()
        if all(_DOWN.get((m, key), 0) > now for m in self._models for key in self._keys):
            _DOWN.clear()  # mọi cặp đều đang bị nhớ là hỏng -> thử lại từ đầu thay vì báo lỗi luôn
        for _ in range(RATE_LIMIT_ROUNDS + 1):
            for model in self._models:
                for k, client in enumerate(self._clients):
                    pair = (model, k)
                    if pair in self._dead or self._cool.get(pair, 0) > time.monotonic() \
                            or _DOWN.get((model, self._keys[k]), 0) > time.monotonic():
                        continue
                    try:
                        return client.chat.completions.create(**kwargs, model=model)
                    except (APITimeoutError, APIStatusError) as e:
                        last = e
                        status = getattr(e, "status_code", None)
                        wait = _retry_delay(e) if status == 429 else None
                        if wait is not None and wait <= RATE_LIMIT_MAX_WAIT:
                            self._cool[pair] = time.monotonic() + wait
                            self._log(f"{model} ({self._label(k)}) giới hạn số lần gọi mỗi phút, thử key / model khác…")
                        elif status == 429:
                            self._dead.add(pair)
                            _DOWN[(model, self._keys[k])] = time.monotonic() + (wait or MODEL_DOWN_S)
                            hours = f", gọi lại được sau {wait / 3600:.1f} giờ" if wait else ""
                            self._log(f"{model} ({self._label(k)}) hết lượt gọi trong ngày{hours}, chuyển tiếp…")
                        elif status in (401, 403) or (status == 400 and "api key" in _describe(e).lower()):
                            # key sai / bị khoá: bỏ key này cho mọi model
                            self._dead.update((m, k) for m in self._models)
                            self._log(f"{self._label(k)} không dùng được ({_describe(e)[:80]}), bỏ qua key này")
                        elif isinstance(e, APITimeoutError) or status in (500, 502, 503, 504):
                            # model quá tải / treo: không phụ thuộc key -> bỏ cả model
                            self._dead.update((model, i) for i in range(len(self._clients)))
                            _DOWN.update({(model, key): time.monotonic() + MODEL_DOWN_S for key in self._keys})
                            self._log(f"{model} đang quá tải ({_describe(e)[:60]}), chuyển sang model sau "
                                      f"(bỏ qua model này {MODEL_DOWN_S // 60} phút)…")
                            break
                        else:
                            self.errors.append(_describe(e))
                            raise
                    except Exception as e:
                        self.errors.append(_describe(e))
                        raise
            cooling = [t for pair, t in self._cool.items() if pair not in self._dead]
            if not cooling:
                break
            wait = max(0.0, min(cooling) - time.monotonic())  # mọi cặp còn lại đều đang bị giới hạn / phút
            self._log(f"mọi key đang bị giới hạn số lần gọi mỗi phút, đợi {wait:.0f}s rồi thử lại…")
            time.sleep(wait)
        msg = _describe(last) if last else "không còn model / key nào dùng được"
        self.errors.append(msg)
        raise RuntimeError(f"đã thử hết {len(self._models)} model x {len(self._clients)} key: {msg}")


def _describe(e: Exception) -> str:
    body = getattr(e, "body", None)  # lỗi từ API: lấy câu báo lỗi của Google thay vì chỉ "Error code: 400"
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        body = body.get("error", body)
        body = body.get("message", body) if isinstance(body, dict) else body
    return f"{getattr(e, 'status_code', type(e).__name__)}: {body or e}"


# Lượt 3 — rút gọn theo thời lượng. Giọng VieNeu đọc ~4,2 tiếng/giây; lúc xuất video được tăng tốc tới 1,35x
# và đọc sớm 0,3s (xem render/ffmpeg.py) -> nhắm ~4,8 tiếng/giây để hiếm khi phải tăng tốc hết cỡ.
SYLLABLES_PER_SEC = 4.8
FIT_SLACK = 1  # chỉ rút gọn câu vượt hạn mức hơn chừng này tiếng (lệch ít thì tăng tốc giọng lo được, rút gọn dễ sai nghĩa)
FIT_BATCH = 40


def _syllables(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _budgets(lines: list[SubtitleLine]) -> list[int]:
    """Số tiếng tối đa cho mỗi câu: tính theo khoảng từ lúc câu bắt đầu tới lúc câu sau bắt đầu."""
    out = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1].start_ms if i + 1 < len(lines) else line.end_ms + 1000
        room_s = max(line.end_ms, nxt) / 1000 - line.start_ms / 1000 + 0.3
        out.append(max(2, int(room_s * SYLLABLES_PER_SEC)))
    return out


def overlong_seconds(lines: list[SubtitleLine]) -> dict[int, float]:
    """Câu sub mới đọc không kịp trong thời lượng của nó: chỉ số câu -> số giây bị lố (ước theo số tiếng)."""
    return {i: (_syllables(l.text) - b) / SYLLABLES_PER_SEC
            for i, (l, b) in enumerate(zip(lines, _budgets(lines))) if l.text.strip() and _syllables(l.text) > b}


def _fit_to_duration(client: _GeminiClient, settings: TranslateSettings, lines: list[SubtitleLine],
                     texts: list[str], context, progress: ProgressFn,
                     only: set[int] | None = None, slack: int = FIT_SLACK) -> list[str]:
    """Câu dịch dài hơn hạn mức tiếng -> nhờ Gemini rút gọn (giữ nghĩa, xưng hô, thuật ngữ); chỉ nhận bản ngắn hơn."""
    budgets = _budgets(lines)
    long = [i for i, (t, b) in enumerate(zip(texts, budgets))
            if _syllables(t) > b + slack and (only is None or i in only)]
    if not long:
        return texts
    rules = ""
    if context is not None:
        rules = (f"Forms of address (keep exactly): {context.formality or '-'}\n"
                 f"Terms (keep identical): {json.dumps(context.terms, ensure_ascii=False)}\n")
    out = list(texts)
    for n, start in enumerate(range(0, len(long), FIT_BATCH), 1):
        chunk = long[start:start + FIT_BATCH]
        progress(80 + int((n - 1) / max(1, -(-len(long) // FIT_BATCH)) * 20),
                 f"Lượt 3: rút gọn {len(long)} câu dài cho vừa thời lượng…")
        items = [{"id": i, "max_words": budgets[i], "source": lines[i].original,
                  "prev": out[i - 1] if i else "", "current": out[i],
                  "next": out[i + 1] if i + 1 < len(out) else ""} for i in chunk]
        try:
            resp = client.create(
                model=settings.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content":
                        f"You shorten {settings.target_lang} dubbing subtitles so they can be spoken within the "
                        "time of the original line. For each item rewrite `current` to AT MOST `max_words` words "
                        "(a word = one space-separated syllable), keeping the meaning of `source`, the tone, and "
                        "natural spoken style. Drop filler, repeated subjects and words obvious from context. "
                        "`prev` / `next` are the neighbouring lines, given ONLY so you avoid repeating them: never "
                        "move their content into the current line, never add anything that is not in `source`. "
                        "Keep the same pronouns as `current`. Do not merge or split lines, do not add notes or "
                        "parentheses.\n" + rules +
                        'Return JSON: {"lines": [{"id": <id>, "text": "<shortened line>"}]}'},
                    {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
                ],
            )
            data = json.loads(resp.choices[0].message.content or "{}")
        except Exception as e:  # rút gọn là phần phụ: lỗi thì giữ bản dịch đầy đủ, không làm hỏng cả lượt dịch
            progress(95, f"Lượt 3 lỗi, giữ bản dịch đầy đủ: {_describe(e)[:80]}")
            continue
        for item in data.get("lines", []):
            i, text = item.get("id"), str(item.get("text", "")).strip()
            if i in chunk and text and _syllables(text) < _syllables(out[i]):
                out[i] = text
    return out


def _check_key(key: str) -> None:
    if "://" in key or any(c.isspace() for c in key):
        raise RuntimeError("ô API key đang chứa một đường link / đoạn chữ, không phải Gemini API key. "
                           "Dán lại key (dạng AIza…) lấy tại https://aistudio.google.com/apikey")


class SubtransTranslator(Translator):
    id = "subtrans"
    name = "subtrans (Gemini, 2 lượt)"

    def __init__(self, batch_size: int = 50):
        self.batch_size = batch_size

    @staticmethod
    def _client(settings: TranslateSettings, progress: ProgressFn) -> _GeminiClient:
        keys = list(dict.fromkeys(k.strip() for k in settings.api_keys if k.strip()))  # bỏ trùng, giữ thứ tự
        keys = keys or [os.environ[k] for k in API_KEY_ENVS if os.environ.get(k)] or \
            [k for k in DEFAULT_GEMINI_API_KEYS if k]
        if not keys:
            raise RuntimeError("chưa có Gemini API key (nhập trong Cài đặt hoặc đặt biến GEMINI_API_KEY; "
                               "lấy key miễn phí tại https://aistudio.google.com/apikey)")
        for key in keys:
            _check_key(key)

        from openai import OpenAI

        return _GeminiClient([OpenAI(api_key=k, base_url=GEMINI_BASE_URL, max_retries=0) for k in keys],
                             model_chain(settings.model), log=lambda msg: progress(10, msg), keys=keys)

    def shorten(self, lines: list[SubtitleLine], indices: list[int], settings: TranslateSettings,
                progress: ProgressFn = no_progress) -> dict[int, str]:
        """Rút gọn các câu sub mới `indices` cho vừa thời lượng; trả về câu nào đã ngắn đi."""
        client = self._client(settings, progress)
        texts = [l.text for l in lines]
        try:
            out = _fit_to_duration(client, settings, lines, texts, None, progress, only=set(indices), slack=0)
        except SystemExit as e:
            raise RuntimeError("Gemini báo vượt hạn mức (quota / rate limit), đợi một lúc rồi thử lại") from e
        if client.errors and out == texts:
            raise RuntimeError(f"Gemini lỗi: {client.errors[-1]}")
        return {i: out[i] for i in indices if out[i] != texts[i]}

    def translate(self, lines: list[SubtitleLine], title: str, settings: TranslateSettings,
                  progress: ProgressFn = no_progress) -> list[str]:
        if not lines:
            return []
        client = self._client(settings, progress)

        import pysrt

        tr = _load_subtrans()
        subs = pysrt.SubRipFile([
            pysrt.SubRipItem(index=i, start=pysrt.SubRipTime(milliseconds=l.start_ms),
                             end=pysrt.SubRipTime(milliseconds=l.end_ms), text=l.original)
            for i, l in enumerate(lines, 1)
        ])
        src, tgt = settings.source_lang, settings.target_lang
        try:  # subtrans gọi SystemExit khi hết quota -> đổi thành lỗi thường cho luồng nền
            context = None
            if not settings.skip_analysis:
                progress(5, "Lượt 1: phân tích ngữ cảnh…")
                context = tr.analyze_subtitles(subs, client, title, model=settings.model,
                                               source_lang=src, target_lang=tgt)
            out: list[str] = []
            total = (len(subs) + self.batch_size - 1) // self.batch_size
            span = 60 if settings.fit_duration else 80  # % tiến độ dành cho lượt 2
            for n, i in enumerate(range(0, len(subs), self.batch_size), 1):
                progress(20 + int((n - 1) / total * span), f"Lượt 2: dịch lô {n}/{total}…")
                batch = pysrt.SubRipFile(subs[i:i + self.batch_size])
                # service_tier="flex" chỉ để subtrans đặt timeout 900s (60s dễ hụt với lô dài); tham số bị bỏ khi gửi
                done = tr.translate_subtitles_batch(batch, client, title, context=context,
                                                    batch_size=self.batch_size, model=settings.model,
                                                    source_lang=src, target_lang=tgt, service_tier="flex")
                texts = [sub.text for sub in done]
                if client.errors and texts == [sub.text for sub in batch]:
                    # subtrans trả nguyên chữ gốc khi lô bị lỗi -> báo lỗi thật, không giả vờ đã dịch
                    raise RuntimeError(f"Gemini lỗi ở lô {n}/{total}: {client.errors[-1]}")
                out.extend(texts)
            if settings.fit_duration:
                out = _fit_to_duration(client, settings, lines, out, context, progress)
        except SystemExit as e:
            raise RuntimeError("Gemini báo vượt hạn mức (quota / rate limit), đợi một lúc rồi thử lại "
                               "hoặc kiểm tra gói của API key") from e
        progress(100, "Dịch xong")
        return out

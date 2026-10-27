"""VieNeu-TTS v3 Turbo (thư mục VieNeu-TTS/, cài bằng `pip install -e ./VieNeu-TTS`).

Chạy offline trên máy: CPU qua ONNX Runtime, có GPU NVIDIA thì tự dùng PyTorch.
Lần đầu tạo giọng sẽ tải mô hình từ Hugging Face (cần Internet một lần).
VieNeu không có tham số tốc độ / cao độ / âm lượng -> chỉnh sau bằng ffmpeg.

Nghe thử: câu mẫu mặc định của 25 giọng có sẵn được tạo trước, để trong app/assets/voice_samples
(tạo lại: `python -m app.services.tts.vieneu`). Giọng clone được tạo câu mẫu ngay lúc clone.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import threading
from pathlib import Path

from app.config import BASE_DIR, DATA_DIR, TTS_CACHE_DIR
from app.models import VoiceInfo, VoiceSettings
from app.services.common import ProgressFn, no_progress
from app.services.tts.base import SAMPLE_TEXT, TTSProvider

_GENDER = {"female": "Nữ", "male": "Nam"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BUNDLED_SAMPLES = BASE_DIR / "app" / "assets" / "voice_samples"
CLONED_FILE = DATA_DIR / "voices" / "cloned.json"
PREVIEW_DIR = TTS_CACHE_DIR / "preview"
CLONED_LOCALE = "Giọng clone"


class VieNeuTTSProvider(TTSProvider):
    id = "vieneu"
    name = "VieNeu-TTS v3 Turbo (offline)"
    supports_clone = True

    def __init__(self):
        self._voices: list[VoiceInfo] | None = None
        self._cloned: dict[str, dict] = _load_cloned()
        self._model = None
        self._lock = threading.Lock()  # một mô hình dùng chung: nghe thử + lồng tiếng + clone không chạy chồng

    # ------------------------------------------------------------------ giọng
    def list_voices(self, refresh: bool = False, progress: ProgressFn = no_progress) -> list[VoiceInfo]:
        if self._voices is None or refresh:
            # đọc thẳng file giọng đi kèm SDK, khỏi nạp mô hình chỉ để lấy danh sách
            import vieneu

            data = json.loads((Path(vieneu.__file__).parent / "assets" / "voices_v3_turbo.json")
                              .read_text(encoding="utf-8"))
            presets = sorted(data["presets"].items(),
                             key=lambda kv: (kv[1].get("featured") is None, int(kv[1].get("featured") or 0)))
            cloned = [VoiceInfo(id=name, name=f"🎙 {name}", locale=CLONED_LOCALE,
                                gender=_GENDER.get(v.get("gender", ""), ""), provider=self.id, custom=True)
                      for name, v in self._cloned.items()]
            self._voices = cloned + [
                VoiceInfo(
                    id=name,
                    name=f"⭐ {name}" if v.get("featured") is not None else name,
                    locale=f"Miền {v['region']}" if v.get("region") else "",
                    gender=_GENDER.get(v.get("gender", ""), v.get("gender", "")),
                    provider=self.id,
                )
                for name, v in presets
            ]
        return self._voices

    def clone_voice(self, name: str, audio_path: Path, progress: ProgressFn = no_progress) -> VoiceInfo:
        name = name.strip()
        if not name:
            raise ValueError("tên giọng không được để trống")
        if any(v.id == name for v in self.list_voices()):
            raise ValueError(f"đã có giọng tên \"{name}\"")
        with tempfile.TemporaryDirectory() as tmp:
            # ffmpeg đọc được mọi định dạng (mp3, m4a, cả file video) -> wav mono cho VieNeu
            clip = Path(tmp) / "ref.wav"
            _ffmpeg(["-i", str(audio_path), "-vn", "-ac", "1", "-ar", "44100", "-t", "30", str(clip)])
            with self._lock:
                model = self._get_model(progress)
                progress(40, "Đang trích đặc trưng giọng (khử nhiễu, cắt ≤ 8 giây)…")
                emb, codes = model.encode_reference(clip, denoise=True)
        self._cloned[name] = {
            "gender": "",
            "speaker_emb": [round(float(x), 6) for x in emb.reshape(-1)],
            "codes": codes.astype(int).tolist() if codes is not None else None,
        }
        _save_cloned(self._cloned)
        self._voices = None
        progress(70, "Đang tạo câu nghe thử…")
        self.preview(SAMPLE_TEXT, VoiceSettings(provider=self.id, voice_id=name))
        progress(100, "Clone xong")
        return next(v for v in self.list_voices() if v.id == name)

    def remove_voice(self, voice_id: str) -> None:
        if self._cloned.pop(voice_id, None) is not None:
            _save_cloned(self._cloned)
            self._voices = None

    # ------------------------------------------------------------------ tạo giọng
    def warm_up(self, progress: ProgressFn = no_progress) -> None:
        with self._lock:
            self._get_model(progress)

    def synthesize(self, text: str, settings: VoiceSettings, out_path: Path,
                   progress: ProgressFn = no_progress) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not _adjusted(settings):
            return self._render(text, settings.voice_id, out_path, progress)
        raw = self._render(text, settings.voice_id, out_path.with_name(out_path.stem + ".raw.wav"), progress)
        try:
            _adjust(raw, out_path, settings)
        finally:
            raw.unlink(missing_ok=True)
        return out_path

    def cached_preview(self, text: str, settings: VoiceSettings) -> Path | None:
        raw = self._sample(text, settings.voice_id)
        if raw is None:
            return None
        if not _adjusted(settings):
            return raw
        out = _adjusted_path(text, settings)
        return out if out.exists() else None

    def preview(self, text: str, settings: VoiceSettings, progress: ProgressFn = no_progress) -> Path:
        ready = self.cached_preview(text, settings)
        if ready:
            return ready
        raw = self._sample(text, settings.voice_id)
        if raw is None:  # chỉ lượt đầu với câu / giọng này mới phải chạy mô hình
            raw = self._render(text, settings.voice_id, PREVIEW_DIR / f"{_key(settings.voice_id, text)}.wav", progress)
        if not _adjusted(settings):
            return raw
        out = _adjusted_path(text, settings)
        _adjust(raw, out, settings)  # chỉnh bằng ffmpeg, chưa tới 1 giây
        return out

    # ------------------------------------------------------------------ nội bộ
    def _sample(self, text: str, voice_id: str) -> Path | None:
        key = _key(voice_id, text)
        for path in (BUNDLED_SAMPLES / f"{key}.mp3", PREVIEW_DIR / f"{key}.wav"):
            if path.exists():
                return path
        return None

    def _render(self, text: str, voice_id: str, out_path: Path, progress: ProgressFn = no_progress) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            model = self._get_model(progress)
            if voice_id in self._cloned:
                import numpy as np

                v = self._cloned[voice_id]
                voice = {"speaker_emb": np.asarray(v["speaker_emb"], dtype=np.float32),
                         "codes": np.asarray(v["codes"], dtype=np.int64) if v.get("codes") is not None else None}
            else:
                voice = voice_id if model.resolve_voice_name(voice_id) else None
            model.save(model.infer(text, voice=voice), out_path)
        return out_path

    def _get_model(self, progress: ProgressFn):
        if self._model is None:
            progress(0, "Đang nạp mô hình VieNeu-TTS (lần đầu sẽ tải về, hơi lâu)…")
            from huggingface_hub import constants
            from vieneu import Vieneu

            try:
                self._model = Vieneu()
            except Exception:
                # mất mạng / Hugging Face lỗi -> dùng bản mô hình đã tải về máy
                constants.HF_HUB_OFFLINE = True
                self._model = Vieneu()
        return self._model


def _key(voice_id: str, text: str) -> str:
    return hashlib.sha1(f"{voice_id}|{text}".encode("utf-8")).hexdigest()[:16]


def _adjusted(s: VoiceSettings) -> bool:
    return bool(s.rate or s.pitch or s.volume)


def _adjusted_path(text: str, s: VoiceSettings) -> Path:
    return PREVIEW_DIR / f"{_key(s.voice_id, text)}_{s.rate}_{s.pitch}_{s.volume}.wav"


def _load_cloned() -> dict[str, dict]:
    try:
        return json.loads(CLONED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cloned(voices: dict[str, dict]) -> None:
    CLONED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLONED_FILE.write_text(json.dumps(voices, ensure_ascii=False), encoding="utf-8")


def _ffmpeg(args: list[str]) -> None:
    from app.services.render.ffmpeg import ffmpeg_exe

    res = subprocess.run([ffmpeg_exe(), "-hide_banner", "-y", *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi: {res.stderr.strip()[-300:]}")


def _adjust(src: Path, dst: Path, s: VoiceSettings) -> None:
    """rate/volume: % so với gốc; pitch: số nửa cung (giữ nguyên tốc độ)."""
    filters = []
    if s.pitch:
        factor = 2 ** (s.pitch / 12)
        filters += [f"asetrate=48000*{factor:.5f}", "aresample=48000", f"atempo={1 / factor:.5f}"]
    if s.rate:
        filters.append(f"atempo={1 + s.rate / 100:.3f}")  # thanh trượt -50..100 nằm gọn trong 0.5..2 của atempo
    if s.volume:
        filters.append(f"volume={1 + s.volume / 100:.3f}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-i", str(src), "-af", ",".join(filters), "-ar", "48000", str(dst)])


if __name__ == "__main__":
    # tạo lại câu nghe thử của các giọng có sẵn (chạy khi đổi SAMPLE_TEXT hoặc bản VieNeu có giọng mới)
    provider = VieNeuTTSProvider()
    BUNDLED_SAMPLES.mkdir(parents=True, exist_ok=True)
    presets = [v for v in provider.list_voices() if not v.custom]
    for n, v in enumerate(presets, 1):
        out = BUNDLED_SAMPLES / f"{_key(v.id, SAMPLE_TEXT)}.mp3"
        wav = provider._render(SAMPLE_TEXT, v.id, PREVIEW_DIR / "bundle.wav")
        _ffmpeg(["-i", str(wav), "-c:a", "libmp3lame", "-b:a", "96k", str(out)])
        print(f"{n}/{len(presets)} {out.name}")

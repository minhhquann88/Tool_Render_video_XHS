import asyncio
from pathlib import Path

from app.models import VoiceInfo, VoiceSettings
from app.services.common import ProgressFn, no_progress
from app.services.tts.base import TTSProvider

_GENDER = {"Female": "Nữ", "Male": "Nam"}


class EdgeTTSProvider(TTSProvider):
    id = "edge"
    name = "Microsoft Edge TTS (miễn phí)"

    def __init__(self):
        self._voices: list[VoiceInfo] | None = None

    def list_voices(self, refresh: bool = False, progress: ProgressFn = no_progress) -> list[VoiceInfo]:
        if self._voices is None or refresh:
            import edge_tts

            raw = asyncio.run(edge_tts.list_voices())
            voices = [
                VoiceInfo(
                    id=v["ShortName"],
                    name=v["ShortName"].split("-", 2)[-1].removesuffix("Neural"),
                    locale=v["Locale"],
                    gender=_GENDER.get(v.get("Gender", ""), v.get("Gender", "")),
                    provider=self.id,
                )
                for v in raw
            ]
            self._voices = sorted(voices, key=lambda v: (v.locale, v.name))
        return self._voices

    def synthesize(self, text: str, settings: VoiceSettings, out_path: Path,
                   progress: ProgressFn = no_progress) -> Path:
        import edge_tts

        out_path.parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(
            text,
            settings.voice_id,
            rate=f"{settings.rate:+d}%",
            pitch=f"{settings.pitch:+d}Hz",
            volume=f"{settings.volume:+d}%",
        )
        asyncio.run(communicate.save(str(out_path)))
        return out_path

"""Nơi đăng ký các implementation. Thêm nguồn mới = thêm 1 class + 1 dòng ở đây."""
from dataclasses import dataclass

from app.services.render.base import Renderer
from app.services.render.mock import MockRenderer
from app.services.scraper.base import VideoScraper
from app.services.scraper.xhs import XhsScraper
from app.services.subtitle.base import RegionDetector, SubtitleSource
from app.services.subtitle.demo import BottomBandDetector, DemoSubtitleSource
from app.services.subtitle.rapidocr_detector import RapidOcrRegionDetector
from app.services.subtitle.stubs import WhisperSource
from app.services.subtitle.vsf_pipeline import VsfOcrSource, VsfRapidPipeline, VsfRegionDetector
from app.services.tts.base import TTSProvider
from app.services.tts.edge import EdgeTTSProvider
from app.services.upload.base import Uploader
from app.services.upload.gdrive import GoogleDriveUploader
from app.services.upload.mock import MockUploader


def _by_id(items):
    return {item.id: item for item in items}


@dataclass
class Services:
    scrapers: list[VideoScraper]
    detectors: dict[str, RegionDetector]
    subtitle_sources: dict[str, SubtitleSource]
    tts: dict[str, TTSProvider]
    renderers: dict[str, Renderer]
    uploaders: dict[str, Uploader]

    def scraper_for(self, url: str) -> VideoScraper | None:
        return next((s for s in self.scrapers if s.can_handle(url)), None)


def build_services() -> Services:
    vsf = VsfRapidPipeline()  # dùng chung cho tìm vùng + tạo sub -> chỉ quét video 1 lần
    return Services(
        scrapers=[XhsScraper()],
        detectors=_by_id([VsfRegionDetector(vsf), RapidOcrRegionDetector(), BottomBandDetector()]),
        subtitle_sources=_by_id([VsfOcrSource(vsf), DemoSubtitleSource(), WhisperSource()]),
        tts=_by_id([EdgeTTSProvider()]),
        renderers=_by_id([MockRenderer()]),
        uploaders=_by_id([MockUploader(), GoogleDriveUploader()]),
    )

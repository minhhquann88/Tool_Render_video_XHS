"""Đọc cookie XHS: file Netscape (cookie.txt từ extension), JSON export, hoặc chuỗi 'k=v; k2=v2'."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Cookie bắt buộc để XHS coi là đã đăng nhập
LOGIN_COOKIE = "web_session"


@dataclass
class CookieInfo:
    cookies: dict[str, str] = field(default_factory=dict)
    expired: list[str] = field(default_factory=list)
    session_expires: datetime | None = None  # None = cookie phiên / không rõ

    @property
    def logged_in(self) -> bool:
        return LOGIN_COOKIE in self.cookies

    def summary(self) -> str:
        if not self.cookies:
            return "Chưa có cookie"
        text = f"{len(self.cookies)} cookie"
        if not self.logged_in:
            return text + " · thiếu web_session (chưa đăng nhập)"
        if self.session_expires:
            text += f" · hết hạn {self.session_expires:%d/%m/%Y}"
        return text


def parse_cookies(content: str) -> CookieInfo:
    content = content.strip().lstrip("﻿")
    if content.startswith("["):
        return _parse_json(content)
    if "\t" in content or content.startswith("# Netscape"):
        return _parse_netscape(content)
    return _parse_header(content)


def load_cookie_file(path: Path) -> CookieInfo:
    return parse_cookies(path.read_text(encoding="utf-8", errors="ignore"))


def _add(info: CookieInfo, name: str, value: str, expires: float | None) -> None:
    if expires and expires < time.time():
        info.expired.append(name)
        return
    info.cookies[name] = value
    if name == LOGIN_COOKIE and expires:
        info.session_expires = datetime.fromtimestamp(expires)


def _parse_netscape(content: str) -> CookieInfo:
    info = CookieInfo()
    for line in content.splitlines():
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        expires = float(parts[4]) if parts[4].isdigit() else 0
        _add(info, parts[5], parts[6].strip(), expires or None)
    return info


def _parse_json(content: str) -> CookieInfo:
    info = CookieInfo()
    for c in json.loads(content):
        _add(info, c["name"], c["value"], c.get("expirationDate") or c.get("expires"))
    return info


def _parse_header(content: str) -> CookieInfo:
    info = CookieInfo()
    for pair in content.removeprefix("Cookie:").split(";"):
        if "=" in pair:
            name, value = pair.split("=", 1)
            _add(info, name.strip(), value.strip(), None)
    return info

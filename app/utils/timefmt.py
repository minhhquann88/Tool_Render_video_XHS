def ms_to_str(ms: int) -> str:
    """12345 -> '00:12.345'"""
    ms = max(0, int(ms))
    minutes, seconds = divmod(ms // 1000, 60)
    return f"{minutes:02d}:{seconds:02d}.{ms % 1000:03d}"


def ms_to_clock(ms: int) -> str:
    """12345 -> '00:12'"""
    minutes, seconds = divmod(max(0, int(ms)) // 1000, 60)
    return f"{minutes:02d}:{seconds:02d}"


def ms_to_srt(ms: int) -> str:
    """12345 -> '00:00:12,345'"""
    ms = max(0, int(ms))
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def str_to_ms(text: str) -> int:
    """Nhận 'ss.mmm', 'mm:ss.mmm' hoặc 'hh:mm:ss,mmm'."""
    parts = text.strip().replace(",", ".").split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"Sai định dạng thời gian: {text!r}")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) == 3 else 0
    return int(round((hours * 3600 + minutes * 60 + seconds) * 1000))

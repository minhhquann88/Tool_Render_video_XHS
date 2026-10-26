import re

from app.models import SubtitleLine
from app.utils.timefmt import ms_to_srt, str_to_ms

_TIME_LINE = re.compile(r"(\S+)\s*-->\s*(\S+)")


def parse_srt(content: str) -> list[SubtitleLine]:
    lines: list[SubtitleLine] = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip())
    for block in blocks:
        rows = block.split("\n")
        for i, row in enumerate(rows):
            match = _TIME_LINE.search(row)
            if match:
                text = "\n".join(rows[i + 1:]).strip()
                lines.append(SubtitleLine(str_to_ms(match.group(1)), str_to_ms(match.group(2)), text=text))
                break
    return lines


def to_srt(lines: list[SubtitleLine]) -> str:
    out = []
    for i, line in enumerate(lines, 1):
        out.append(f"{i}\n{ms_to_srt(line.start_ms)} --> {ms_to_srt(line.end_ms)}\n{line.text}\n")
    return "\n".join(out)

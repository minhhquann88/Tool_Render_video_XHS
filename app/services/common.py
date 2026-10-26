from typing import Callable

# progress(phần_trăm 0..100, mô_tả)
ProgressFn = Callable[[int, str], None]


def no_progress(pct: int, msg: str = "") -> None:
    pass

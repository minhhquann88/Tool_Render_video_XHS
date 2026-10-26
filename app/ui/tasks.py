"""Chạy service ở thread nền, callback trả về luôn chạy trên UI thread."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThreadPool, Signal


class _Bridge(QObject):
    progress = Signal(int, int, str)
    result = Signal(int, object)
    error = Signal(int, str)


class TaskRunner(QObject):
    def __init__(self, parent=None, on_unhandled_error: Callable[[str], None] | None = None):
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._bridge = _Bridge(self)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.result.connect(self._on_result)
        self._bridge.error.connect(self._on_error)
        self._callbacks: dict[int, tuple] = {}
        self._next_id = 0
        self.on_unhandled_error = on_unhandled_error

    def submit(self, fn: Callable[..., Any], *args,
               on_result: Callable[[Any], None] | None = None,
               on_error: Callable[[str], None] | None = None,
               on_progress: Callable[[int, str], None] | None = None,
               **kwargs) -> int:
        """fn phải nhận keyword `progress(pct, msg)`."""
        tid = self._next_id
        self._next_id += 1
        self._callbacks[tid] = (on_result, on_error, on_progress)
        bridge = self._bridge

        def emit(signal, *values):
            try:
                signal.emit(*values)
            except RuntimeError:  # cửa sổ đã đóng
                pass

        def report(pct: int, msg: str = "") -> None:
            emit(bridge.progress, tid, int(pct), str(msg))

        def job():
            try:
                res = fn(*args, progress=report, **kwargs)
            except NotImplementedError as e:
                emit(bridge.error, tid, f"Chưa hỗ trợ: {e}" if str(e) else "Chức năng chưa được cài đặt")
            except Exception as e:
                traceback.print_exc()
                emit(bridge.error, tid, f"{type(e).__name__}: {e}")
            else:
                emit(bridge.result, tid, res)

        self._pool.start(job)
        return tid

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self._callbacks.clear()
        self._pool.clear()
        self._pool.waitForDone(timeout_ms)

    def _on_progress(self, tid: int, pct: int, msg: str) -> None:
        cb = self._callbacks.get(tid)
        if cb and cb[2]:
            cb[2](pct, msg)

    def _on_result(self, tid: int, res: object) -> None:
        cb = self._callbacks.pop(tid, None)
        if cb and cb[0]:
            cb[0](res)

    def _on_error(self, tid: int, msg: str) -> None:
        cb = self._callbacks.pop(tid, None)
        if cb and cb[1]:
            cb[1](msg)
        elif cb is not None and self.on_unhandled_error:
            self.on_unhandled_error(msg)

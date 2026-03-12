"""
背景執行器基類

所有 Runner 繼承此類。
使用 threading + queue.Queue 與 tkinter 非同步溝通，
GUI 端用 after(100, poll_queue) 輪詢，嚴格遵守 tkinter 單執行緒規則。
"""

import queue
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class RunnerMessage:
    """Runner 發送給 GUI 的訊息"""

    msg_type: str       # "log" | "progress" | "done" | "error"
    text: str = ""
    progress: float = -1.0  # 0.0~1.0，-1 表示不更新進度條


class BaseRunner:
    """背景執行器基類"""

    def __init__(self):
        self.queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, **kwargs):
        """在背景 thread 啟動執行（非阻塞）"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_safe, kwargs=kwargs, daemon=True
        )
        self._thread.start()

    def stop(self):
        """請求停止（設置 stop event，讓 _run 自行檢查）"""
        self._stop_event.set()

    def is_running(self) -> bool:
        """是否正在執行中"""
        return self._thread is not None and self._thread.is_alive()

    def _run(self, **kwargs):
        """子類實作：實際工作邏輯，可呼叫 _emit() 發送訊息"""
        raise NotImplementedError

    def _run_safe(self, **kwargs):
        """包裝 _run，捕捉例外並送到 queue"""
        try:
            self._run(**kwargs)
            self.queue.put(RunnerMessage("done", "執行完成"))
        except InterruptedError:
            self.queue.put(RunnerMessage("done", "已中止"))
        except Exception as e:
            import traceback
            detail = traceback.format_exc()
            self.queue.put(RunnerMessage("error", f"{e}\n\n{detail}"))

    def _emit(self, text: str, progress: float = -1.0):
        """發送日誌訊息（可附帶進度更新）"""
        self.queue.put(RunnerMessage("log", text, progress))

    def _emit_progress(self, progress: float, text: str = ""):
        """只更新進度條，不輸出日誌"""
        self.queue.put(RunnerMessage("progress", text, progress))

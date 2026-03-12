"""
共用 GUI 元件

提供各分頁共用的 tkinter 元件：
- LogPanel: 唯讀捲動文字區
- ProgressSection: 進度條 + 百分比 + 經過時間
- FileChooserRow: 檔案路徑輸入 + 瀏覽按鈕
- DirChooserRow: 目錄路徑輸入 + 瀏覽按鈕
- RunStopButton: 執行/中止切換按鈕
"""

import time
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional


class LogPanel(ttk.Frame):
    """唯讀捲動日誌面板"""

    def __init__(self, parent, height: int = 12, **kwargs):
        super().__init__(parent, **kwargs)

        self.text = tk.Text(
            self,
            height=height,
            state="disabled",
            font=("Courier New", 10) if tk.TkVersion >= 8.5 else ("Courier", 10),
            wrap="word",
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            selectbackground="#264f78",
            relief="flat",
            bd=1,
        )
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)

        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 設定 tag 顏色
        self.text.configure(state="normal")
        self.text.tag_configure("error", foreground="#f44747")
        self.text.tag_configure("success", foreground="#4ec9b0")
        self.text.tag_configure("warn", foreground="#ce9178")
        self.text.configure(state="disabled")

    def append(self, text: str, tag: str = ""):
        """在末尾附加文字（自動捲動到底部）"""
        self.text.configure(state="normal")
        if tag:
            self.text.insert("end", text + "\n", tag)
        else:
            self.text.insert("end", text + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self):
        """清空日誌"""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


class ProgressSection(ttk.Frame):
    """進度條 + 百分比 + 經過時間"""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        self._start_time: Optional[float] = None
        self._timer_id = None

        # 進度條
        self.bar = ttk.Progressbar(self, mode="determinate", length=400)
        self.bar.pack(side="left", fill="x", expand=True)

        # 百分比標籤
        self._pct_var = tk.StringVar(value="0%")
        ttk.Label(self, textvariable=self._pct_var, width=5).pack(side="left", padx=(6, 0))

        # 經過時間標籤
        self._time_var = tk.StringVar(value="00:00")
        ttk.Label(self, textvariable=self._time_var, width=7, foreground="gray").pack(
            side="left", padx=(6, 0)
        )

    def start(self):
        """啟動計時"""
        self._start_time = time.time()
        self.set(0.0)
        self._tick()

    def stop(self):
        """停止計時"""
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    def set(self, value: float):
        """設定進度 0.0~1.0"""
        pct = max(0.0, min(1.0, value))
        self.bar["value"] = pct * 100
        self._pct_var.set(f"{int(pct * 100)}%")

    def _tick(self):
        """每秒更新計時"""
        if self._start_time:
            elapsed = int(time.time() - self._start_time)
            m, s = divmod(elapsed, 60)
            self._time_var.set(f"{m:02d}:{s:02d}")
        self._timer_id = self.after(1000, self._tick)


class FileChooserRow(ttk.Frame):
    """檔案路徑輸入列（Label + Entry + 瀏覽按鈕）"""

    def __init__(
        self,
        parent,
        label: str,
        filetypes: list = None,
        default: str = "",
        **kwargs,
    ):
        super().__init__(parent, **kwargs)

        self._filetypes = filetypes or [("所有檔案", "*.*")]

        ttk.Label(self, text=label, width=12, anchor="e").pack(side="left")
        self._var = tk.StringVar(value=default)
        ttk.Entry(self, textvariable=self._var, width=50).pack(side="left", padx=(4, 4))
        ttk.Button(self, text="瀏覽", width=6, command=self._browse).pack(side="left")

    def _browse(self):
        path = filedialog.askopenfilename(filetypes=self._filetypes)
        if path:
            self._var.set(path)

    @property
    def value(self) -> str:
        return self._var.get().strip()

    @value.setter
    def value(self, v: str):
        self._var.set(v)


class DirChooserRow(ttk.Frame):
    """目錄路徑輸入列（Label + Entry + 瀏覽按鈕）"""

    def __init__(self, parent, label: str, default: str = "", **kwargs):
        super().__init__(parent, **kwargs)

        ttk.Label(self, text=label, width=12, anchor="e").pack(side="left")
        self._var = tk.StringVar(value=default)
        ttk.Entry(self, textvariable=self._var, width=50).pack(side="left", padx=(4, 4))
        ttk.Button(self, text="瀏覽", width=6, command=self._browse).pack(side="left")

    def _browse(self):
        path = filedialog.askdirectory()
        if path:
            self._var.set(path)

    @property
    def value(self) -> str:
        return self._var.get().strip()

    @value.setter
    def value(self, v: str):
        self._var.set(v)


class RunStopButton(ttk.Button):
    """執行/中止切換按鈕"""

    def __init__(
        self,
        parent,
        on_run: Callable,
        on_stop: Callable,
        run_text: str = "開始執行",
        stop_text: str = "中止執行",
        **kwargs,
    ):
        self._on_run = on_run
        self._on_stop = on_stop
        self._run_text = run_text
        self._stop_text = stop_text
        self._running = False

        super().__init__(parent, text=run_text, command=self._toggle, width=14, **kwargs)

    def _toggle(self):
        if self._running:
            self._on_stop()
        else:
            self._on_run()

    def set_running(self, running: bool):
        self._running = running
        self.configure(text=self._stop_text if running else self._run_text)


def make_section_label(parent, text: str) -> ttk.Label:
    """建立分區標題標籤"""
    return ttk.Label(parent, text=text, font=("", 10, "bold"))


def make_separator(parent) -> ttk.Separator:
    """建立水平分隔線"""
    return ttk.Separator(parent, orient="horizontal")

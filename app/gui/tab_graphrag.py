"""
Step 2：建構知識圖分頁

選定 graphrag_root 目錄後，呼叫 `graphrag index` 建立知識圖譜。
由於 GraphRAG 不回報百分比，使用 indeterminate 進度條。
"""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from app import config as cfg
from app.gui.widgets import (
    DirChooserRow,
    LogPanel,
    ProgressSection,
    RunStopButton,
    make_section_label,
    make_separator,
)
from app.runners.graphrag_runner import GraphragRunner, INDETERMINATE


class GraphragTab(ttk.Frame):
    """Step 2：建構知識圖分頁"""

    def __init__(self, parent):
        super().__init__(parent, padding=16)
        self._runner: Optional[GraphragRunner] = None
        self._indeterminate_running = False
        self._build_ui()
        self._load_config()

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── 目錄設定 ──────────────────────────────────────────────────
        make_section_label(self, "GraphRAG 根目錄").pack(anchor="w", pady=(0, 6))

        self._root_chooser = DirChooserRow(self, label="graphrag_root")
        self._root_chooser.pack(fill="x", pady=3)
        ttk.Label(
            self,
            text="（需包含 settings.yaml；input_graphrag/ 為文件來源）",
            foreground="gray",
            font=("", 9),
        ).pack(anchor="w", padx=(90, 0))

        make_separator(self).pack(fill="x", pady=10)

        # ── 執行控制 ──────────────────────────────────────────────────
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", pady=(0, 6))

        self._run_btn = RunStopButton(
            ctrl_frame,
            on_run=self._on_run,
            on_stop=self._on_stop,
            run_text="開始建圖",
            stop_text="中止執行",
        )
        self._run_btn.pack(side="left")

        self._progress = ProgressSection(ctrl_frame)
        self._progress.pack(side="left", fill="x", expand=True, padx=(16, 0))

        # ── 日誌面板 ──────────────────────────────────────────────────
        make_section_label(self, "執行日誌").pack(anchor="w", pady=(8, 4))
        self._log = LogPanel(self, height=18)
        self._log.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # 設定載入
    # ------------------------------------------------------------------

    def _load_config(self):
        conf = cfg.load()
        graphrag_root = conf.get("graphrag_root", "")
        if graphrag_root:
            self._root_chooser.value = graphrag_root

    def refresh_config(self):
        self._load_config()

    # ------------------------------------------------------------------
    # 事件處理
    # ------------------------------------------------------------------

    def _on_run(self):
        graphrag_root = self._root_chooser.value
        if not graphrag_root:
            messagebox.showwarning("缺少設定", "請先選擇 graphrag_root 目錄")
            return

        conf = cfg.load()
        if not conf.get("graphrag_api_key") and not conf.get("azure_openai_api_key"):
            if not messagebox.askyesno(
                "設定不完整",
                "尚未設定 GraphRAG API Key 或 Azure OpenAI API Key。\n是否繼續執行（可能會失敗）？",
            ):
                return

        self._log.clear()
        self._progress.start()
        self._run_btn.set_running(True)

        self._runner = GraphragRunner()
        self._runner.start(graphrag_root=graphrag_root)
        self._poll()

    def _on_stop(self):
        if self._runner and self._runner.is_running():
            self._runner.stop()
            self._log.append("正在中止...", tag="warn")

    def _poll(self):
        if self._runner is None:
            return
        try:
            while True:
                msg = self._runner.queue.get_nowait()
                self._handle_message(msg)
        except Exception:
            pass

        if self._runner.is_running():
            self.after(100, self._poll)
        else:
            try:
                while True:
                    msg = self._runner.queue.get_nowait()
                    self._handle_message(msg)
            except Exception:
                pass

    def _handle_message(self, msg):
        if msg.msg_type == "log":
            self._log.append(msg.text)
            if msg.progress >= 0:
                self._stop_indeterminate()
                self._progress.set(msg.progress)
        elif msg.msg_type == "progress":
            if msg.progress == INDETERMINATE:
                self._start_indeterminate()
            elif msg.progress >= 0:
                self._stop_indeterminate()
                self._progress.set(msg.progress)
        elif msg.msg_type == "done":
            self._log.append(msg.text, tag="success")
            self._on_done()
        elif msg.msg_type == "error":
            self._log.append(f"執行錯誤:\n{msg.text}", tag="error")
            self._on_done(error=True)

    def _start_indeterminate(self):
        if not self._indeterminate_running:
            self._progress.bar.configure(mode="indeterminate")
            self._progress.bar.start(15)
            self._progress._pct_var.set("...")
            self._indeterminate_running = True

    def _stop_indeterminate(self):
        if self._indeterminate_running:
            self._progress.bar.stop()
            self._progress.bar.configure(mode="determinate")
            self._indeterminate_running = False

    def _on_done(self, error: bool = False):
        self._stop_indeterminate()
        self._progress.stop()
        self._run_btn.set_running(False)
        if not error:
            self._progress.set(1.0)

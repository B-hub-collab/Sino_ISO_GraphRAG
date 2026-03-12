"""
Step 1：文件拆分分頁

上傳 PDF 契約文件，自動拆分為 GraphRAG 可處理的條款文字檔。
支援三種文件類型：工程契約、投標須知（含補充）、投標須知附錄A。
"""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from app import config as cfg
from app.gui.widgets import (
    DirChooserRow,
    FileChooserRow,
    LogPanel,
    ProgressSection,
    RunStopButton,
    make_section_label,
    make_separator,
)
from app.runners.split_runner import SplitRunner

PDF_TYPES = [("PDF 檔案", "*.pdf"), ("所有檔案", "*.*")]


class SplitTab(ttk.Frame):
    """Step 1：文件拆分分頁"""

    def __init__(self, parent):
        super().__init__(parent, padding=16)
        self._runner: Optional[SplitRunner] = None
        self._build_ui()
        self._load_config()

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── PDF 來源 ──────────────────────────────────────────────────
        make_section_label(self, "PDF 來源（至少選一個）").pack(anchor="w", pady=(0, 6))

        self._contract_chooser = FileChooserRow(
            self, label="工程契約", filetypes=PDF_TYPES
        )
        self._contract_chooser.pack(fill="x", pady=3)

        self._bidding_chooser = FileChooserRow(
            self, label="投標須知", filetypes=PDF_TYPES
        )
        self._bidding_chooser.pack(fill="x", pady=3)

        self._appendix_chooser = FileChooserRow(
            self, label="附錄A", filetypes=PDF_TYPES
        )
        self._appendix_chooser.pack(fill="x", pady=3)

        make_separator(self).pack(fill="x", pady=10)

        # ── 輸出設定 ──────────────────────────────────────────────────
        make_section_label(self, "輸出設定").pack(anchor="w", pady=(0, 6))

        self._output_chooser = DirChooserRow(self, label="輸出目錄")
        ttk.Label(
            self, text="（即 input_graphrag/ 目錄，GraphRAG 建圖時的輸入來源）",
            foreground="gray", font=("", 9),
        ).pack(anchor="w", padx=(90, 0))
        self._output_chooser.pack(fill="x", pady=3)

        make_separator(self).pack(fill="x", pady=10)

        # ── 執行控制 ──────────────────────────────────────────────────
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", pady=(0, 6))

        self._run_btn = RunStopButton(
            ctrl_frame,
            on_run=self._on_run,
            on_stop=self._on_stop,
            run_text="開始拆分",
            stop_text="中止執行",
        )
        self._run_btn.pack(side="left")

        self._progress = ProgressSection(ctrl_frame)
        self._progress.pack(side="left", fill="x", expand=True, padx=(16, 0))

        # ── 日誌面板 ──────────────────────────────────────────────────
        make_section_label(self, "執行日誌").pack(anchor="w", pady=(8, 4))
        self._log = LogPanel(self, height=14)
        self._log.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # 設定載入
    # ------------------------------------------------------------------

    def _load_config(self):
        conf = cfg.load()
        graphrag_root = conf.get("graphrag_root", "")
        if graphrag_root:
            self._output_chooser.value = str(Path(graphrag_root) / "input_graphrag")

    def refresh_config(self):
        self._load_config()

    # ------------------------------------------------------------------
    # 事件處理
    # ------------------------------------------------------------------

    def _on_run(self):
        contract_pdf = self._contract_chooser.value or None
        bidding_pdf = self._bidding_chooser.value or None
        appendix_pdf = self._appendix_chooser.value or None
        output_dir = self._output_chooser.value

        if not any([contract_pdf, bidding_pdf, appendix_pdf]):
            messagebox.showwarning("缺少來源", "請至少選擇一個 PDF 檔案")
            return
        if not output_dir:
            messagebox.showwarning("缺少設定", "請先選擇輸出目錄")
            return

        self._log.clear()
        self._progress.start()
        self._run_btn.set_running(True)

        self._runner = SplitRunner()
        self._runner.start(
            input_graphrag_dir=output_dir,
            contract_pdf=contract_pdf,
            bidding_pdf=bidding_pdf,
            appendix_pdf=appendix_pdf,
        )
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
                self._progress.set(msg.progress)
        elif msg.msg_type == "progress":
            if msg.progress >= 0:
                self._progress.set(msg.progress)
        elif msg.msg_type == "done":
            self._log.append(msg.text, tag="success")
            self._on_done()
        elif msg.msg_type == "error":
            self._log.append(f"執行錯誤:\n{msg.text}", tag="error")
            self._on_done(error=True)

    def _on_done(self, error: bool = False):
        self._progress.stop()
        self._run_btn.set_running(False)

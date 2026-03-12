"""
Step 5：報告匯出分頁

從稽核結果目錄或 batch_summary JSON 匯出 DOCX/PDF 報告。
"""

import tkinter as tk
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
from app.runners.report_runner import ReportRunner


class ReportTab(ttk.Frame):
    """報告匯出分頁"""

    def __init__(self, parent):
        super().__init__(parent, padding=16)
        self._runner: Optional[ReportRunner] = None
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        make_section_label(self, "資料來源").pack(anchor="w", pady=(0, 6))

        # 來源模式選擇
        mode_frame = ttk.Frame(self)
        mode_frame.pack(fill="x", pady=3)
        self._source_mode = tk.StringVar(value="dir")
        ttk.Radiobutton(
            mode_frame, text="從目錄讀取所有稽核報告",
            variable=self._source_mode, value="dir",
            command=self._on_mode_change,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_frame, text="指定 batch_summary JSON",
            variable=self._source_mode, value="file",
            command=self._on_mode_change,
        ).pack(side="left", padx=(16, 0))

        self._source_dir = DirChooserRow(self, label="稽核報告目錄")
        self._source_dir.pack(fill="x", pady=3)

        self._source_file = FileChooserRow(
            self,
            label="彙總 JSON 檔",
            filetypes=[("JSON 檔案", "*.json"), ("所有檔案", "*.*")],
        )
        self._source_file.pack(fill="x", pady=3)

        self._output_chooser = DirChooserRow(self, label="報告輸出目錄")
        self._output_chooser.pack(fill="x", pady=3)

        make_separator(self).pack(fill="x", pady=10)

        make_section_label(self, "匯出格式").pack(anchor="w", pady=(0, 6))
        fmt_frame = ttk.Frame(self)
        fmt_frame.pack(fill="x", pady=3)
        self._export_docx = tk.BooleanVar(value=True)
        self._export_pdf = tk.BooleanVar(value=False)
        ttk.Checkbutton(fmt_frame, text="Word (.docx)", variable=self._export_docx).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(fmt_frame, text="PDF (.pdf)", variable=self._export_pdf).pack(side="left")

        make_separator(self).pack(fill="x", pady=10)

        # 執行控制
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", pady=(0, 6))
        self._run_btn = RunStopButton(
            ctrl_frame, on_run=self._on_run, on_stop=self._on_stop,
            run_text="匯出報告", stop_text="中止匯出",
        )
        self._run_btn.pack(side="left")
        self._progress = ProgressSection(ctrl_frame)
        self._progress.pack(side="left", fill="x", expand=True, padx=(16, 0))

        make_section_label(self, "執行日誌").pack(anchor="w", pady=(8, 4))
        self._log = LogPanel(self, height=14)
        self._log.pack(fill="both", expand=True)

        self._on_mode_change()

    def _load_config(self):
        conf = cfg.load()
        self._source_dir.value = conf.get("output_dir", "")
        self._output_chooser.value = conf.get("output_dir", "")

    def refresh_config(self):
        self._load_config()

    def _on_mode_change(self):
        mode = self._source_mode.get()
        if mode == "dir":
            self._source_dir.pack(fill="x", pady=3)
            self._source_file.pack_forget()
        else:
            self._source_dir.pack_forget()
            self._source_file.pack(fill="x", pady=3)

    def _get_source(self) -> str:
        if self._source_mode.get() == "dir":
            return self._source_dir.value
        return self._source_file.value

    def _get_formats(self):
        formats = []
        if self._export_docx.get():
            formats.append("docx")
        if self._export_pdf.get():
            formats.append("pdf")
        return formats

    def _on_run(self):
        source = self._get_source()
        output_dir = self._output_chooser.value
        formats = self._get_formats()

        if not source:
            messagebox.showwarning("缺少設定", "請先選擇資料來源")
            return
        if not output_dir:
            messagebox.showwarning("缺少設定", "請先選擇輸出目錄")
            return
        if not formats:
            messagebox.showwarning("缺少設定", "請至少選擇一種匯出格式")
            return

        self._log.clear()
        self._progress.start()
        self._run_btn.set_running(True)

        self._runner = ReportRunner()
        self._runner.start(source=source, output_dir=output_dir, formats=formats)
        self._poll()

    def _on_stop(self):
        if self._runner and self._runner.is_running():
            self._runner.stop()

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
        elif msg.msg_type == "done":
            self._log.append(msg.text, tag="success")
            self._progress.stop()
            self._run_btn.set_running(False)
        elif msg.msg_type == "error":
            self._log.append(f"錯誤:\n{msg.text}", tag="error")
            self._progress.stop()
            self._run_btn.set_running(False)

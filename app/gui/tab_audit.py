"""
Step 4：批次稽核分頁

讀取稽核規則 Excel，批次執行 Local Search + 合規分析，
在 GUI 顯示即時進度與日誌，完成後顯示統計摘要。
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
from app.runners.audit_runner import AuditRunner


class AuditTab(ttk.Frame):
    """批次稽核分頁"""

    def __init__(self, parent):
        super().__init__(parent, padding=16)
        self._runner: Optional[AuditRunner] = None
        self._poll_id = None
        self._build_ui()
        self._load_config()

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── 檔案設定 ──────────────────────────────────────────────────
        make_section_label(self, "檔案設定").pack(anchor="w", pady=(0, 6))

        self._rules_chooser = FileChooserRow(
            self,
            label="稽核規則檔",
            filetypes=[("Excel 檔案", "*.xlsx *.xls"), ("所有檔案", "*.*")],
        )
        self._rules_chooser.pack(fill="x", pady=3)

        self._output_chooser = DirChooserRow(self, label="輸出目錄")
        self._output_chooser.pack(fill="x", pady=3)

        make_separator(self).pack(fill="x", pady=10)

        # ── 執行設定 ──────────────────────────────────────────────────
        make_section_label(self, "執行設定").pack(anchor="w", pady=(0, 6))

        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill="x", pady=3)

        self._filter_mode = tk.StringVar(value="all")
        ttk.Radiobutton(
            filter_frame, text="全部規則", variable=self._filter_mode,
            value="all", command=self._on_filter_mode_change,
        ).pack(side="left")
        ttk.Radiobutton(
            filter_frame, text="指定規則 ID：", variable=self._filter_mode,
            value="custom", command=self._on_filter_mode_change,
        ).pack(side="left", padx=(16, 4))
        self._rule_ids_var = tk.StringVar()
        self._rule_ids_entry = ttk.Entry(filter_frame, textvariable=self._rule_ids_var, width=36)
        self._rule_ids_entry.pack(side="left")
        ttk.Label(filter_frame, text="（空格分隔，例：RULE_001 RULE_005）", foreground="gray").pack(
            side="left", padx=(6, 0)
        )
        self._on_filter_mode_change()

        export_frame = ttk.Frame(self)
        export_frame.pack(fill="x", pady=6)
        ttk.Label(export_frame, text="完成後匯出：").pack(side="left")
        self._export_docx = tk.BooleanVar(value=True)
        self._export_pdf = tk.BooleanVar(value=False)
        ttk.Checkbutton(export_frame, text="DOCX", variable=self._export_docx).pack(side="left", padx=(8, 4))
        ttk.Checkbutton(export_frame, text="PDF", variable=self._export_pdf).pack(side="left")

        make_separator(self).pack(fill="x", pady=10)

        # ── 執行控制 ──────────────────────────────────────────────────
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", pady=(0, 6))

        self._run_btn = RunStopButton(
            ctrl_frame,
            on_run=self._on_run,
            on_stop=self._on_stop,
            run_text="開始稽核",
            stop_text="中止執行",
        )
        self._run_btn.pack(side="left")

        self._progress = ProgressSection(ctrl_frame)
        self._progress.pack(side="left", fill="x", expand=True, padx=(16, 0))

        # ── 日誌面板 ──────────────────────────────────────────────────
        make_section_label(self, "執行日誌").pack(anchor="w", pady=(8, 4))
        self._log = LogPanel(self, height=14)
        self._log.pack(fill="both", expand=True)

        # ── 統計摘要（執行完成後顯示）────────────────────────────────
        self._summary_frame = ttk.LabelFrame(self, text="稽核統計", padding=8)
        # 初始隱藏，完成後 pack
        self._summary_labels: dict = {}
        self._build_summary_panel(self._summary_frame)

    def _build_summary_panel(self, parent):
        """建立統計摘要面板（6 格）"""
        items = [
            ("risk", "RISK_DETECTED", "#f44747"),
            ("compliant", "COMPLIANT", "#4ec9b0"),
            ("uncertain", "UNCERTAIN", "#ce9178"),
            ("na", "NOT_APPLICABLE", "gray"),
            ("high", "HIGH 風險", "#f44747"),
            ("medium", "MEDIUM 風險", "#ce9178"),
        ]
        for i, (key, label, color) in enumerate(items):
            cell = ttk.Frame(parent)
            cell.grid(row=0, column=i, padx=12, pady=4)
            var = tk.StringVar(value="0")
            self._summary_labels[key] = var
            ttk.Label(cell, textvariable=var, font=("", 18, "bold"), foreground=color).pack()
            ttk.Label(cell, text=label, font=("", 8), foreground="gray").pack()

    # ------------------------------------------------------------------
    # 設定載入
    # ------------------------------------------------------------------

    def _load_config(self):
        conf = cfg.load()
        self._rules_chooser.value = conf.get("rules_file", "")
        self._output_chooser.value = conf.get("output_dir", "")

    def refresh_config(self):
        """由主視窗在切換分頁時呼叫，重新載入最新設定"""
        self._load_config()

    # ------------------------------------------------------------------
    # 事件處理
    # ------------------------------------------------------------------

    def _on_filter_mode_change(self):
        mode = self._filter_mode.get()
        state = "normal" if mode == "custom" else "disabled"
        self._rule_ids_entry.configure(state=state)

    def _get_rule_ids(self):
        if self._filter_mode.get() == "all":
            return None
        text = self._rule_ids_var.get().strip()
        if not text:
            return None
        return [rid.strip() for rid in text.split() if rid.strip()]

    def _get_export_formats(self):
        formats = []
        if self._export_docx.get():
            formats.append("docx")
        if self._export_pdf.get():
            formats.append("pdf")
        return formats or None

    def _on_run(self):
        rules_file = self._rules_chooser.value
        output_dir = self._output_chooser.value

        if not rules_file:
            messagebox.showwarning("缺少設定", "請先選擇稽核規則檔案")
            return
        if not output_dir:
            messagebox.showwarning("缺少設定", "請先選擇輸出目錄")
            return

        # 確認設定
        conf = cfg.load()
        if not conf.get("azure_openai_api_key"):
            if not messagebox.askyesno(
                "設定不完整",
                "尚未設定 Azure OpenAI API Key。\n是否繼續執行（可能會失敗）？"
            ):
                return

        # 清空舊結果
        self._log.clear()
        self._summary_frame.pack_forget()
        self._progress.start()
        self._run_btn.set_running(True)

        rule_ids = self._get_rule_ids()
        export_formats = self._get_export_formats()

        self._runner = AuditRunner()
        self._runner.start(
            rules_file=rules_file,
            output_dir=output_dir,
            rule_ids=rule_ids,
            export_formats=export_formats,
        )
        self._poll()

    def _on_stop(self):
        if self._runner and self._runner.is_running():
            self._runner.stop()
            self._log.append("正在中止...", tag="warn")

    def _poll(self):
        """輪詢 runner queue，更新 GUI"""
        if self._runner is None:
            return

        try:
            while True:
                msg = self._runner.queue.get_nowait()
                self._handle_message(msg)
        except Exception:
            pass

        if self._runner.is_running():
            self._poll_id = self.after(100, self._poll)
        else:
            # 排空剩餘訊息
            try:
                while True:
                    msg = self._runner.queue.get_nowait()
                    self._handle_message(msg)
            except Exception:
                pass

    def _handle_message(self, msg):
        from app.runners.base_runner import RunnerMessage
        if msg.msg_type == "log":
            self._log.append(msg.text)
            if msg.progress >= 0:
                self._progress.set(msg.progress)
        elif msg.msg_type == "progress":
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

        if not error and self._runner and self._runner.summary:
            self._update_summary(self._runner.summary)
            self._summary_frame.pack(fill="x", pady=(10, 0))

    def _update_summary(self, summary):
        self._summary_labels["risk"].set(str(summary.risk_detected_count))
        self._summary_labels["compliant"].set(str(summary.compliant_count))
        self._summary_labels["uncertain"].set(str(summary.uncertain_count))
        self._summary_labels["na"].set(str(summary.not_applicable_count))
        self._summary_labels["high"].set(str(summary.high_severity_count))
        self._summary_labels["medium"].set(str(summary.medium_severity_count))

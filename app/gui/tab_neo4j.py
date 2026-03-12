"""
Step 3：匯入 Neo4j 分頁

選定 GraphRAG output 目錄後，將 parquet 資料與向量 embeddings
匯入 Neo4j 圖資料庫，並建立向量索引。
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
from app.runners.neo4j_import_runner import Neo4jImportRunner


class Neo4jImportTab(ttk.Frame):
    """Step 3：匯入 Neo4j 分頁"""

    def __init__(self, parent):
        super().__init__(parent, padding=16)
        self._runner: Optional[Neo4jImportRunner] = None
        self._build_ui()
        self._load_config()

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── 目錄設定 ──────────────────────────────────────────────────
        make_section_label(self, "資料來源").pack(anchor="w", pady=(0, 6))

        self._output_chooser = DirChooserRow(self, label="GraphRAG 輸出")
        self._output_chooser.pack(fill="x", pady=3)
        ttk.Label(
            self,
            text="（GraphRAG 產生的 output/ 目錄，包含各 parquet 子目錄）",
            foreground="gray",
            font=("", 9),
        ).pack(anchor="w", padx=(90, 0))

        make_separator(self).pack(fill="x", pady=10)

        # ── 執行選項 ──────────────────────────────────────────────────
        make_section_label(self, "執行選項").pack(anchor="w", pady=(0, 6))

        opt_frame = ttk.Frame(self)
        opt_frame.pack(fill="x", pady=3)

        self._clear_existing = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt_frame,
            text="匯入前清空現有 Neo4j 資料庫",
            variable=self._clear_existing,
        ).pack(side="left")
        ttk.Label(
            opt_frame,
            text="（⚠ 不可復原）",
            foreground="#f44747",
            font=("", 9),
        ).pack(side="left", padx=(6, 0))

        opt_frame2 = ttk.Frame(self)
        opt_frame2.pack(fill="x", pady=3)

        self._run_vector_index = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt_frame2,
            text="同步建立／更新實體向量索引（setup_vector_index.py）",
            variable=self._run_vector_index,
        ).pack(side="left")

        make_separator(self).pack(fill="x", pady=10)

        # ── 執行控制 ──────────────────────────────────────────────────
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", pady=(0, 6))

        self._run_btn = RunStopButton(
            ctrl_frame,
            on_run=self._on_run,
            on_stop=self._on_stop,
            run_text="開始匯入",
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
            output_dir = str(Path(graphrag_root) / "output")
            self._output_chooser.value = output_dir

    def refresh_config(self):
        self._load_config()

    # ------------------------------------------------------------------
    # 事件處理
    # ------------------------------------------------------------------

    def _on_run(self):
        output_dir = self._output_chooser.value
        if not output_dir:
            messagebox.showwarning("缺少設定", "請先選擇 GraphRAG 輸出目錄")
            return

        conf = cfg.load()
        if not conf.get("neo4j_password"):
            if not messagebox.askyesno(
                "設定不完整",
                "尚未設定 Neo4j 密碼。\n是否繼續執行（可能會失敗）？",
            ):
                return

        clear = self._clear_existing.get()
        if clear:
            if not messagebox.askyesno(
                "確認清空資料庫",
                "即將清空整個 Neo4j 資料庫，此動作不可復原！\n確定要繼續嗎？",
                icon="warning",
            ):
                return

        self._log.clear()
        self._progress.start()
        self._run_btn.set_running(True)

        self._runner = Neo4jImportRunner()
        self._runner.start(
            output_dir=output_dir,
            clear_existing=clear,
            run_vector_index=self._run_vector_index.get(),
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
        if not error:
            self._progress.set(1.0)

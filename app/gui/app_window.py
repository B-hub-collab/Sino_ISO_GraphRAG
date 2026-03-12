"""
主視窗

ttk.Notebook 多分頁架構：
  [設定] [Step1:文件拆分] [Step2:建構知識圖] [Step3:匯入Neo4j] [Step4:批次稽核] [Step5:匯出報告]

切換分頁時自動從設定分頁取得最新設定。
"""

import tkinter as tk
from tkinter import ttk

from app.gui.tab_settings import SettingsTab
from app.gui.tab_split import SplitTab
from app.gui.tab_graphrag import GraphragTab
from app.gui.tab_neo4j import Neo4jImportTab
from app.gui.tab_audit import AuditTab
from app.gui.tab_report import ReportTab


class AuditApp(tk.Tk):
    """契約稽核系統主視窗"""

    APP_TITLE = "契約自動稽核系統"
    APP_VERSION = "1.0.0"
    WIN_WIDTH = 1020
    WIN_HEIGHT = 740

    def __init__(self):
        super().__init__()

        self.title(f"{self.APP_TITLE}  v{self.APP_VERSION}")
        self.geometry(f"{self.WIN_WIDTH}x{self.WIN_HEIGHT}")
        self.minsize(860, 600)

        self._setup_style()
        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        # 切換分頁時重新載入設定
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

    # ------------------------------------------------------------------
    # 樣式
    # ------------------------------------------------------------------

    def _setup_style(self):
        style = ttk.Style(self)
        # 嘗試使用系統原生主題
        available = style.theme_names()
        for theme in ("clam", "alt", "default"):
            if theme in available:
                style.theme_use(theme)
                break

        style.configure("TNotebook.Tab", padding=(14, 6), font=("", 10))
        style.configure("Header.TLabel", font=("", 13, "bold"))
        style.configure("Sub.TLabel", font=("", 9), foreground="gray")

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _build_header(self):
        header = ttk.Frame(self, padding=(16, 10, 16, 0))
        header.pack(fill="x")

        ttk.Label(header, text=self.APP_TITLE, style="Header.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="政府採購契約自動稽核平台  |  Microsoft GraphRAG + Neo4j + Azure OpenAI",
            style="Sub.TLabel",
        ).pack(side="left", padx=(12, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(8, 0))

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # 設定分頁
        self.tab_settings = SettingsTab(self.notebook)
        self.notebook.add(self.tab_settings, text="  設定  ")

        # Step 1：文件拆分
        self.tab_split = SplitTab(self.notebook)
        self.notebook.add(self.tab_split, text=" Step 1：文件拆分 ")

        # Step 2：建構知識圖
        self.tab_graphrag = GraphragTab(self.notebook)
        self.notebook.add(self.tab_graphrag, text=" Step 2：建構知識圖 ")

        # Step 3：匯入 Neo4j
        self.tab_neo4j = Neo4jImportTab(self.notebook)
        self.notebook.add(self.tab_neo4j, text=" Step 3：匯入 Neo4j ")

        # Step 4：批次稽核
        self.tab_audit = AuditTab(self.notebook)
        self.notebook.add(self.tab_audit, text=" Step 4：批次稽核 ")

        # Step 5：匯出報告
        self.tab_report = ReportTab(self.notebook)
        self.notebook.add(self.tab_report, text=" Step 5：匯出報告 ")

        # 預設開啟 Step 4（已有資料可立即使用）
        self.notebook.select(self.tab_audit)

    def _build_statusbar(self):
        bar = ttk.Frame(self, relief="sunken", padding=(8, 2))
        bar.pack(fill="x", side="bottom")

        self._status_var = tk.StringVar(value="就緒")
        ttk.Label(bar, textvariable=self._status_var, foreground="gray", font=("", 9)).pack(side="left")
        ttk.Label(bar, text=f"v{self.APP_VERSION}", foreground="#aaa", font=("", 9)).pack(side="right")

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def _on_tab_change(self, event):
        """切換分頁時，通知目標分頁重新載入最新設定"""
        tab = self.notebook.nametowidget(self.notebook.select())
        if hasattr(tab, "refresh_config"):
            tab.refresh_config()

"""
設定分頁

管理 Azure OpenAI、Neo4j 連線設定及路徑設定。
儲存到 ~/.sino_iso_audit/config.json。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from app import config as cfg
from app.gui.widgets import DirChooserRow, FileChooserRow, make_section_label, make_separator


class SettingsTab(ttk.Frame):
    """設定分頁"""

    def __init__(self, parent):
        super().__init__(parent, padding=16)
        self._vars: dict = {}
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------

    def _build_ui(self):
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas, padding=(8, 8))
        self._inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._inner_id, width=e.width))

        self._build_azure_section(inner)
        make_separator(inner).pack(fill="x", pady=10)
        self._build_neo4j_section(inner)
        make_separator(inner).pack(fill="x", pady=10)
        self._build_paths_section(inner)
        make_separator(inner).pack(fill="x", pady=10)
        self._build_buttons(inner)

    def _build_azure_section(self, parent):
        make_section_label(parent, "Azure OpenAI 設定").pack(anchor="w", pady=(0, 8))

        frame = ttk.Frame(parent)
        frame.pack(fill="x")

        fields = [
            ("Endpoint", "azure_openai_endpoint", False),
            ("API Key", "azure_openai_api_key", True),
            ("API Version", "azure_openai_api_version", False),
            ("Chat Deployment", "azure_openai_chat_deployment", False),
            ("Embedding Deployment", "azure_openai_embedding_deployment", False),
        ]
        self._build_fields(frame, fields)

        # GraphRAG API Key
        gframe = ttk.Frame(parent)
        gframe.pack(fill="x", pady=(6, 0))
        extra = [("GraphRAG Key", "graphrag_api_key", True)]
        self._build_fields(gframe, extra)

    def _build_neo4j_section(self, parent):
        make_section_label(parent, "Neo4j 設定").pack(anchor="w", pady=(0, 8))
        frame = ttk.Frame(parent)
        frame.pack(fill="x")
        fields = [
            ("URI", "neo4j_uri", False),
            ("使用者名稱", "neo4j_user", False),
            ("密碼", "neo4j_password", True),
        ]
        self._build_fields(frame, fields)

    def _build_paths_section(self, parent):
        make_section_label(parent, "路徑設定").pack(anchor="w", pady=(0, 8))

        self._rules_chooser = FileChooserRow(
            parent,
            label="稽核規則檔",
            filetypes=[("Excel 檔案", "*.xlsx *.xls"), ("所有檔案", "*.*")],
        )
        self._rules_chooser.pack(fill="x", pady=3)

        self._output_chooser = DirChooserRow(parent, label="輸出目錄")
        self._output_chooser.pack(fill="x", pady=3)

        self._graphrag_root_chooser = DirChooserRow(parent, label="GraphRAG 根目錄")
        self._graphrag_root_chooser.pack(fill="x", pady=3)

        self._input_dir_chooser = DirChooserRow(parent, label="文件輸入目錄")
        self._input_dir_chooser.pack(fill="x", pady=3)

    def _build_fields(self, parent, fields: list):
        """建立 label + entry 組合（表格排版）"""
        for label, key, is_secret in fields:
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label + ":", width=22, anchor="e").pack(side="left")
            var = tk.StringVar()
            self._vars[key] = var
            show = "*" if is_secret else ""
            entry = ttk.Entry(row, textvariable=var, width=52, show=show)
            entry.pack(side="left", padx=(6, 0))

    def _build_buttons(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(4, 0))

        ttk.Button(frame, text="儲存設定", command=self._save, width=14).pack(side="left", padx=(0, 8))
        ttk.Button(frame, text="測試 Azure 連線", command=self._test_azure, width=18).pack(side="left", padx=(0, 8))
        ttk.Button(frame, text="測試 Neo4j 連線", command=self._test_neo4j, width=18).pack(side="left")

        self._status_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self._status_var, foreground="gray").pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------------
    # 資料操作
    # ------------------------------------------------------------------

    def _load(self):
        """從 config.json 載入設定到 UI"""
        conf = cfg.load()
        for key, var in self._vars.items():
            var.set(conf.get(key, ""))
        self._rules_chooser.value = conf.get("rules_file", "")
        self._output_chooser.value = conf.get("output_dir", "")
        self._graphrag_root_chooser.value = conf.get("graphrag_root", "")
        self._input_dir_chooser.value = conf.get("input_dir", "")

    def _collect(self) -> dict:
        """從 UI 收集設定"""
        conf = {}
        for key, var in self._vars.items():
            conf[key] = var.get().strip()
        conf["rules_file"] = self._rules_chooser.value
        conf["output_dir"] = self._output_chooser.value
        conf["graphrag_root"] = self._graphrag_root_chooser.value
        conf["input_dir"] = self._input_dir_chooser.value
        return conf

    def _save(self):
        """儲存設定"""
        conf = self._collect()
        cfg.save(conf)
        self._status_var.set("設定已儲存")
        messagebox.showinfo("儲存成功", "設定已儲存到 ~/.sino_iso_audit/config.json")

    def get_config(self) -> dict:
        """供其他分頁取得目前設定（不儲存）"""
        return self._collect()

    # ------------------------------------------------------------------
    # 連線測試
    # ------------------------------------------------------------------

    def _test_azure(self):
        """測試 Azure OpenAI 連線"""
        self._status_var.set("測試 Azure 連線中...")
        self.update_idletasks()
        conf = self._collect()
        try:
            from openai import AzureOpenAI
            client = AzureOpenAI(
                api_key=conf.get("azure_openai_api_key", ""),
                api_version=conf.get("azure_openai_api_version", "2025-01-01-preview"),
                azure_endpoint=conf.get("azure_openai_endpoint", ""),
            )
            # 呼叫 list models 驗證連線
            client.models.list()
            self._status_var.set("Azure OpenAI 連線成功")
            messagebox.showinfo("連線成功", "Azure OpenAI 連線測試通過")
        except Exception as e:
            self._status_var.set(f"Azure 連線失敗: {e}")
            messagebox.showerror("連線失敗", f"Azure OpenAI 連線失敗:\n{e}")

    def _test_neo4j(self):
        """測試 Neo4j 連線"""
        self._status_var.set("測試 Neo4j 連線中...")
        self.update_idletasks()
        conf = self._collect()
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                conf.get("neo4j_uri", "bolt://localhost:7687"),
                auth=(
                    conf.get("neo4j_user", "neo4j"),
                    conf.get("neo4j_password", ""),
                ),
            )
            driver.verify_connectivity()
            driver.close()
            self._status_var.set("Neo4j 連線成功")
            messagebox.showinfo("連線成功", "Neo4j 連線測試通過")
        except Exception as e:
            self._status_var.set(f"Neo4j 連線失敗: {e}")
            messagebox.showerror("連線失敗", f"Neo4j 連線失敗:\n{e}")

"""
佔位分頁（Step 1/2/3 開發中）

用於尚未實作的步驟分頁。
"""

import tkinter as tk
from tkinter import ttk


class PlaceholderTab(ttk.Frame):
    """尚未實作的步驟佔位分頁"""

    def __init__(self, parent, step_num: int, title: str, description: str):
        super().__init__(parent, padding=32)

        # 置中顯示
        inner = ttk.Frame(self)
        inner.place(relx=0.5, rely=0.4, anchor="center")

        ttk.Label(
            inner,
            text=f"Step {step_num}",
            font=("", 14, "bold"),
            foreground="#555",
        ).pack(pady=(0, 4))

        ttk.Label(
            inner,
            text=title,
            font=("", 20, "bold"),
        ).pack(pady=(0, 12))

        ttk.Label(
            inner,
            text=description,
            font=("", 11),
            foreground="gray",
            justify="center",
            wraplength=480,
        ).pack(pady=(0, 20))

        ttk.Label(
            inner,
            text="開發中，即將推出",
            font=("", 10),
            foreground="#aaa",
            relief="flat",
            padding=8,
        ).pack()

    def refresh_config(self):
        pass

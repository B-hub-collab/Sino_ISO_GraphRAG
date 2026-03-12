"""
報告匯出執行器
"""

import sys
from pathlib import Path
from typing import List

from .base_runner import BaseRunner


class ReportRunner(BaseRunner):
    """報告匯出背景執行器"""

    def _run(
        self,
        source: str,
        output_dir: str,
        formats: List[str],
    ):
        contracts_dir = Path(__file__).parent.parent.parent
        if str(contracts_dir) not in sys.path:
            sys.path.insert(0, str(contracts_dir))

        from report_export import export_report

        self._emit(f"來源: {source}")
        self._emit(f"輸出目錄: {output_dir}")
        self._emit(f"格式: {', '.join(formats)}\n")

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        self._emit("載入稽核資料...")
        paths = export_report(Path(source), out_path, formats=formats)

        for p in paths:
            self._emit(f"報告已匯出: {p}", 1.0)

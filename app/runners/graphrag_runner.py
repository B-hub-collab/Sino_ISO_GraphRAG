"""
GraphRAG 建圖執行器

在背景 thread 執行 `graphrag index`，逐行捕捉 stdout/stderr 輸出回報給 GUI。
由於 GraphRAG 不提供進度百分比，使用 indeterminate 模式（進度條來回跑）。
"""

import subprocess
import sys
from pathlib import Path

from .base_runner import BaseRunner

# 標記 indeterminate 進度的特殊值
INDETERMINATE = -2.0


class GraphragRunner(BaseRunner):
    """GraphRAG 建圖背景執行器"""

    def _run(self, graphrag_root: str):
        root = Path(graphrag_root)
        if not (root / "settings.yaml").exists():
            raise RuntimeError(f"找不到 settings.yaml，請確認 graphrag_root 是否正確：{graphrag_root}")

        cmd = [sys.executable, "-m", "graphrag", "index", "--root", str(root)]
        self._emit(f"執行指令：{' '.join(cmd)}")
        self._emit(f"工作目錄：{root}\n")

        # 發送 indeterminate 信號（progress == -2.0）
        self.queue.put(__import__("app.runners.base_runner", fromlist=["RunnerMessage"]).RunnerMessage(
            "progress", "", INDETERMINATE
        ))

        process = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        for line in process.stdout:
            if self._stop_event.is_set():
                process.terminate()
                raise InterruptedError("使用者中止執行")
            line = line.rstrip()
            if line:
                self._emit(line)

        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"graphrag index 執行失敗（exit code {process.returncode}）")

        self._emit("\n建圖完成", 1.0)
        output_dir = root / "output"
        if output_dir.exists():
            parquets = list(output_dir.rglob("*.parquet"))
            self._emit(f"輸出目錄：{output_dir}（{len(parquets)} 個 parquet 檔案）")

"""
GraphRAG 建圖執行器

使用 GraphRAG Python API 執行建圖，避免 PyInstaller 打包後 subprocess 問題。
由於 GraphRAG 不提供進度百分比，使用 indeterminate 模式（進度條來回跑）。
"""

import asyncio
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

        self._emit(f"GraphRAG 根目錄：{root}")
        self._emit(f"開始建立知識圖譜...\n")

        # 發送 indeterminate 信號（progress == -2.0）
        self.queue.put(__import__("app.runners.base_runner", fromlist=["RunnerMessage"]).RunnerMessage(
            "progress", "", INDETERMINATE
        ))

        try:
            # 使用 GraphRAG Python API
            from graphrag.api import build_index
            from graphrag.config.load_config import load_config

            self._emit("載入 GraphRAG 設定...")
            config = load_config(root)

            self._emit("執行 GraphRAG indexing（這可能需要幾分鐘）...")

            # 執行建圖
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(build_index(config=config, root=root))
                self._emit(f"建圖結果：{result}")
            finally:
                loop.close()

        except ImportError as e:
            self._emit(f"GraphRAG API 導入失敗：{e}")
            self._emit("嘗試使用命令列方式...")
            self._run_subprocess(root)
            return

        self._emit("\n建圖完成", 1.0)
        output_dir = root / "output"
        if output_dir.exists():
            parquets = list(output_dir.rglob("*.parquet"))
            self._emit(f"輸出目錄：{output_dir}（{len(parquets)} 個 parquet 檔案）")

    def _run_subprocess(self, root: Path):
        """Fallback: 使用 subprocess 執行（僅開發模式）"""
        # 在開發模式下使用 Python，打包後這個方法不應該被調用
        python_exe = sys.executable
        if getattr(sys, "frozen", False):
            # 打包後無法使用 subprocess 方式
            raise RuntimeError("打包版本必須使用 GraphRAG Python API，請確認 graphrag 套件已正確安裝")

        cmd = [python_exe, "-m", "graphrag", "index", "--root", str(root)]
        self._emit(f"執行指令：{' '.join(cmd)}")

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

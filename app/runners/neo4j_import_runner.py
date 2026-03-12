"""
Neo4j 匯入執行器

在背景 thread 執行 GraphRAGImporter（import_graphrag_to_neo4j.py），
將 print 輸出重導向到 queue，逐步回報進度給 GUI。
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .base_runner import BaseRunner


class _QueueStream(io.TextIOBase):
    """將 print 輸出導向 queue"""

    def __init__(self, runner: "Neo4jImportRunner"):
        self._runner = runner

    def write(self, text: str) -> int:
        text = text.strip()
        if text:
            self._runner._emit(text)
        return len(text)

    def flush(self):
        pass


class Neo4jImportRunner(BaseRunner):
    """Neo4j 匯入背景執行器"""

    def _run(
        self,
        output_dir: str,
        clear_existing: bool = False,
        run_vector_index: bool = True,
    ):
        contracts_dir = Path(__file__).parent.parent.parent
        if str(contracts_dir) not in sys.path:
            sys.path.insert(0, str(contracts_dir))

        # 注入設定到 os.environ
        from app.config import inject_to_env, load as load_config
        config = load_config()
        inject_to_env(config)

        from data_pipeline.import_graphrag_to_neo4j import GraphRAGImporter

        stream = _QueueStream(self)
        self._emit("初始化 GraphRAG 匯入器...")

        with redirect_stdout(stream):
            importer = GraphRAGImporter(output_dir=output_dir)

        steps = [
            ("驗證 Neo4j 連線", importer.verify_connection),
            ("建立約束與索引", importer.create_constraints_and_indexes),
            ("匯入實體（Entities）", importer.import_entities),
            ("建立向量索引", importer.create_vector_indexes),
            ("匯入關係（Relationships）", importer.import_relationships),
            ("匯入社群（Communities）", importer.import_communities),
            ("匯入文本單元（TextUnits）", importer.import_text_units),
            ("驗證匯入結果", importer.verify_import),
        ]

        # 清空資料庫（可選）
        if clear_existing:
            self._emit("\n清空現有資料庫...")
            with redirect_stdout(stream):
                if not importer.clear_database(auto_confirm=True):
                    importer.close()
                    raise RuntimeError("清空資料庫失敗或被取消")

        total = len(steps)
        try:
            for i, (label, func) in enumerate(steps):
                if self._stop_event.is_set():
                    raise InterruptedError("使用者中止執行")

                self._emit(f"\n[{i + 1}/{total}] {label}...")
                with redirect_stdout(stream):
                    result = func()

                # verify_connection 返回 bool
                if i == 0 and result is False:
                    raise RuntimeError("Neo4j 連線失敗，請檢查設定")

                self._emit_progress((i + 1) / total)

        finally:
            importer.close()

        # 向量索引（setup_vector_index.py）
        if run_vector_index:
            self._emit("\n建立/更新實體向量索引（setup_vector_index.py）...")
            self._run_vector_index(stream)

        self._emit("\n匯入完成", 1.0)

    def _run_vector_index(self, stream):
        """呼叫 VectorIndexBuilder"""
        from data_pipeline.setup_vector_index import VectorIndexBuilder

        with redirect_stdout(stream):
            builder = VectorIndexBuilder()

        steps = [
            ("建立向量索引定義", builder.create_vector_index),
            ("生成實體 Embeddings", builder.generate_entity_embeddings),
            ("驗證向量索引狀態", builder.verify_index),
        ]

        try:
            for label, func in steps:
                if self._stop_event.is_set():
                    raise InterruptedError("使用者中止執行")
                self._emit(f"  {label}...")
                with redirect_stdout(stream):
                    func()
        finally:
            builder.close()

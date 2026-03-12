"""
文件拆分執行器

負責在背景 thread 執行 PDF 拆分，透過 queue 回報進度給 GUI。
使用 DocumentProcessor 將 PDF 拆成 input_graphrag/ 的條款文字檔。
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Optional

from .base_runner import BaseRunner


class _QueueStream(io.TextIOBase):
    """將 print 輸出導向 queue"""

    def __init__(self, runner: "SplitRunner"):
        self._runner = runner

    def write(self, text: str) -> int:
        text = text.strip()
        if text:
            self._runner._emit(text)
        return len(text)

    def flush(self):
        pass


class SplitRunner(BaseRunner):
    """PDF 文件拆分背景執行器"""

    def _run(
        self,
        input_graphrag_dir: str,
        contract_pdf: Optional[str] = None,
        bidding_pdf: Optional[str] = None,
        appendix_pdf: Optional[str] = None,
    ):
        contracts_dir = Path(__file__).parent.parent.parent
        if str(contracts_dir) not in sys.path:
            sys.path.insert(0, str(contracts_dir))

        from data_pipeline.prepare_documents_for_graphrag import DocumentProcessor

        processor = DocumentProcessor(
            input_dir=str(Path(input_graphrag_dir).parent),
            output_dir=input_graphrag_dir,
        )

        tasks = []
        if contract_pdf:
            tasks.append(("contract", contract_pdf, processor.process_contract))
        if bidding_pdf:
            tasks.append(("bidding", bidding_pdf, processor.process_bidding_document))
        if appendix_pdf:
            tasks.append(("appendix_a", appendix_pdf, processor.process_appendix_a))

        if not tasks:
            raise RuntimeError("請至少選擇一個 PDF 檔案")

        total = len(tasks)
        stream = _QueueStream(self)

        for i, (label, pdf_path, func) in enumerate(tasks):
            if self._stop_event.is_set():
                raise InterruptedError("使用者中止執行")

            self._emit(f"\n[{i + 1}/{total}] 處理 {Path(pdf_path).name}...")
            with redirect_stdout(stream):
                count = func(pdf_path)
            self._emit(f"完成：產生 {count} 個條款檔案", (i + 1) / total)

        self._emit(f"\n輸出目錄：{input_graphrag_dir}")
        out_files = list(Path(input_graphrag_dir).glob("*.txt"))
        self._emit(f"目前共 {len(out_files)} 個文本檔案", 1.0)

"""
批次稽核執行器

負責在背景 thread 執行批次稽核，透過 queue 回報進度給 GUI。
"""

import sys
from pathlib import Path
from typing import List, Optional

from .base_runner import BaseRunner


class AuditRunner(BaseRunner):
    """批次稽核背景執行器"""

    def __init__(self):
        super().__init__()
        self.summary = None  # 執行完成後可從這裡取結果

    def _run(
        self,
        rules_file: str,
        output_dir: str,
        rule_ids: Optional[List[str]] = None,
        export_formats: Optional[List[str]] = None,
    ):
        # 確保 contracts 目錄在 sys.path
        contracts_dir = Path(__file__).parent.parent.parent
        if str(contracts_dir) not in sys.path:
            sys.path.insert(0, str(contracts_dir))

        # 注入設定到 os.environ（必須在 import 之前）
        from app.config import inject_to_env, load as load_config
        config = load_config()
        inject_to_env(config)

        # 重設模組狀態，確保 client 使用最新的 env
        self._reset_module_state(config, output_dir)

        # import（此時 env 已注入）
        from audit_agent_interactive import load_audit_rules
        from audit_batch import run_batch_audit, save_batch_summary

        # 載入規則
        self._emit("載入稽核規則...")
        rules = load_audit_rules(rules_file)
        if not rules:
            raise RuntimeError(f"無法載入規則檔案: {rules_file}")

        if rule_ids:
            target_count = len([r for r in rules if r["id"] in rule_ids])
        else:
            target_count = len(rules)

        self._emit(f"載入 {len(rules)} 條規則，本次執行 {target_count} 條\n")

        # 進度 callback
        def on_progress(current: int, total: int, rule_id: str):
            if self._stop_event.is_set():
                raise InterruptedError("使用者中止執行")
            self._emit(f"[{current}/{total}] 稽核 {rule_id}...", current / total)

        def on_error(rule_id: str, error: Exception):
            self._emit(f"  {rule_id} 執行失敗: {error}")

        # 執行批次稽核
        self._emit("開始批次稽核...")
        summary = run_batch_audit(
            rules=rules,
            rule_ids=rule_ids,
            on_progress=on_progress,
            on_error=on_error,
            stop_on_error=False,
        )
        self.summary = summary

        # 儲存彙總
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        summary_file = save_batch_summary(summary, out_path)
        self._emit(f"\n批次彙總已儲存: {summary_file}", 1.0)

        # 輸出統計
        self._emit("\n--- 稽核統計 ---")
        self._emit(f"完成: {summary.completed}  |  失敗: {summary.failed}  |  略過: {summary.skipped}")
        self._emit(f"RISK_DETECTED:  {summary.risk_detected_count}")
        self._emit(f"COMPLIANT:      {summary.compliant_count}")
        self._emit(f"UNCERTAIN:      {summary.uncertain_count}")
        self._emit(f"NOT_APPLICABLE: {summary.not_applicable_count}")
        self._emit(f"HIGH 風險: {summary.high_severity_count}  |  MEDIUM 風險: {summary.medium_severity_count}")
        self._emit(f"總執行時間: {summary.elapsed_seconds:.1f} 秒")

        # 匯出報告
        if export_formats:
            self._emit(f"\n匯出報告格式: {', '.join(export_formats)}")
            from report_export import export_report
            paths = export_report(summary, out_path, formats=export_formats)
            for p in paths:
                self._emit(f"報告已匯出: {p}")

    def _reset_module_state(self, config: dict, output_dir: str):
        """
        重設 audit_agent_interactive 的模組級狀態。

        audit_agent_interactive 有模組級 client = AzureOpenAI(...)，
        在 import 時立即執行並讀取 os.getenv()。
        透過從 sys.modules 移除後重新 import，確保使用最新的 env。
        """
        for mod_name in ["audit_agent_interactive", "audit_batch"]:
            if mod_name in sys.modules:
                del sys.modules[mod_name]

        # 重新 import（此時 env 已注入，client 會讀到正確的 key）
        import audit_agent_interactive

        # Monkey-patch OUTPUT_DIR 為 GUI 指定的目錄
        audit_agent_interactive.OUTPUT_DIR = Path(output_dir)
        audit_agent_interactive.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Monkey-patch DEPLOYMENT_NAME
        deployment = config.get("azure_openai_chat_deployment", "o4-mini")
        audit_agent_interactive.DEPLOYMENT_NAME = deployment

        # 重置 Neo4j search 單例（確保用新的設定重新連線）
        audit_agent_interactive._neo4j_search = None

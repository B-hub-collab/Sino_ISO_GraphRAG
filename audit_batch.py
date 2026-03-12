"""
批次稽核模式

提供非互動式的批次契約稽核功能，可一次執行全部或指定的稽核規則。

用法:
    python audit_batch.py                                    # 全部規則
    python audit_batch.py --rule-ids RULE_001 RULE_005       # 指定規則
    python audit_batch.py --export docx                      # 批次 + 匯出報告
    python audit_batch.py --stop-on-error                    # 遇錯即停
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

# 確保模組路徑
sys.path.insert(0, str(Path(__file__).parent))

from audit_agent_interactive import (
    RULES_FILE,
    OUTPUT_DIR,
    load_audit_rules,
    generate_optimized_query,
    query_contract_local_search,
    analyze_compliance,
    save_result,
)


# ==========================================
# 資料結構
# ==========================================

@dataclass
class AuditResult:
    """單規則稽核結果"""

    rule: Dict
    query_info: Dict
    rag_result: Dict
    compliance: Dict
    elapsed_seconds: float
    success: bool
    error: Optional[str] = None

    @property
    def rule_id(self) -> str:
        return self.rule.get("id", "UNKNOWN")

    @property
    def status(self) -> str:
        return self.compliance.get("status", "ERROR")

    @property
    def severity(self) -> str:
        return self.compliance.get("severity", "UNKNOWN")


@dataclass
class BatchAuditSummary:
    """批次稽核彙總"""

    total_rules: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    results: List[AuditResult] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    elapsed_seconds: float = 0.0

    @property
    def risk_detected_count(self) -> int:
        return sum(1 for r in self.results if r.status == "RISK_DETECTED")

    @property
    def compliant_count(self) -> int:
        return sum(1 for r in self.results if r.status == "COMPLIANT")

    @property
    def uncertain_count(self) -> int:
        return sum(1 for r in self.results if r.status == "UNCERTAIN")

    @property
    def not_applicable_count(self) -> int:
        return sum(1 for r in self.results if r.status == "NOT_APPLICABLE")

    @property
    def high_severity_count(self) -> int:
        return sum(1 for r in self.results if r.severity == "HIGH")

    @property
    def medium_severity_count(self) -> int:
        return sum(1 for r in self.results if r.severity == "MEDIUM")


# ==========================================
# 核心功能
# ==========================================

def audit_rule_noninteractive(
    rule: Dict,
    generate_query_fn: Optional[Callable] = None,
    search_fn: Optional[Callable] = None,
    analyze_fn: Optional[Callable] = None,
) -> AuditResult:
    """
    非互動式執行單規則稽核（無需使用者確認）

    Args:
        rule: 稽核規則 dict
        generate_query_fn: 查詢生成函數（預設使用 generate_optimized_query）
        search_fn: 搜尋函數（預設使用 query_contract_local_search）
        analyze_fn: 合規分析函數（預設使用 analyze_compliance）

    Returns:
        AuditResult
    """
    if generate_query_fn is None:
        generate_query_fn = generate_optimized_query
    if search_fn is None:
        search_fn = query_contract_local_search
    if analyze_fn is None:
        analyze_fn = analyze_compliance

    start = time.time()

    try:
        # 步驟 1: Query Generation
        query_info = generate_query_fn(rule)

        # 步驟 2: Local Search
        rag_result = search_fn(query_info["graph_query"])

        # 步驟 3: 合規分析
        compliance = analyze_fn(rule, query_info, rag_result)

        elapsed = time.time() - start

        return AuditResult(
            rule=rule,
            query_info=query_info,
            rag_result=rag_result,
            compliance=compliance,
            elapsed_seconds=round(elapsed, 2),
            success=True,
        )

    except Exception as e:
        elapsed = time.time() - start
        return AuditResult(
            rule=rule,
            query_info={},
            rag_result={},
            compliance={
                "status": "ERROR",
                "severity": "UNKNOWN",
                "reason": f"稽核執行失敗: {str(e)}",
                "evidence": "",
                "clause_reference": "",
                "recommendation": "需人工審查",
            },
            elapsed_seconds=round(elapsed, 2),
            success=False,
            error=str(e),
        )


def run_batch_audit(
    rules: List[Dict],
    rule_ids: Optional[List[str]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_error: Optional[Callable[[str, Exception], None]] = None,
    stop_on_error: bool = False,
    generate_query_fn: Optional[Callable] = None,
    search_fn: Optional[Callable] = None,
    analyze_fn: Optional[Callable] = None,
) -> BatchAuditSummary:
    """
    批次執行稽核

    Args:
        rules: 全部稽核規則
        rule_ids: 指定要執行的規則 ID（None = 全部）
        on_progress: 進度回呼 (current, total, rule_id)
        on_error: 錯誤回呼 (rule_id, exception)
        stop_on_error: 遇錯即停
        generate_query_fn: 自訂查詢生成函數
        search_fn: 自訂搜尋函數
        analyze_fn: 自訂合規分析函數

    Returns:
        BatchAuditSummary
    """
    # 篩選規則
    if rule_ids:
        target_rules = [r for r in rules if r["id"] in rule_ids]
        skipped = len(rules) - len(target_rules)
    else:
        target_rules = rules
        skipped = 0

    summary = BatchAuditSummary(
        total_rules=len(target_rules),
        skipped=skipped,
        start_time=datetime.now().isoformat(),
    )

    batch_start = time.time()

    for idx, rule in enumerate(target_rules, 1):
        rule_id = rule["id"]

        if on_progress:
            on_progress(idx, len(target_rules), rule_id)

        result = audit_rule_noninteractive(
            rule,
            generate_query_fn=generate_query_fn,
            search_fn=search_fn,
            analyze_fn=analyze_fn,
        )

        summary.results.append(result)

        if result.success:
            summary.completed += 1
            # 儲存個別結果
            save_result(rule, result.query_info, result.rag_result, result.compliance)
        else:
            summary.failed += 1
            if on_error:
                on_error(rule_id, Exception(result.error or "Unknown error"))
            if stop_on_error:
                print(f"\n停止: {rule_id} 執行失敗 - {result.error}")
                break

    summary.end_time = datetime.now().isoformat()
    summary.elapsed_seconds = round(time.time() - batch_start, 2)

    return summary


def save_batch_summary(summary: BatchAuditSummary, output_dir: Optional[Path] = None) -> Path:
    """
    儲存批次稽核彙總報告

    Args:
        summary: 批次稽核彙總
        output_dir: 輸出目錄（預設 audit_reports/）

    Returns:
        彙總檔案路徑
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = output_dir / f"batch_summary_{timestamp}.json"

    data = {
        "batch_id": f"batch_{timestamp}",
        "start_time": summary.start_time,
        "end_time": summary.end_time,
        "elapsed_seconds": summary.elapsed_seconds,
        "total_rules": summary.total_rules,
        "completed": summary.completed,
        "failed": summary.failed,
        "skipped": summary.skipped,
        "statistics": {
            "risk_detected": summary.risk_detected_count,
            "compliant": summary.compliant_count,
            "uncertain": summary.uncertain_count,
            "not_applicable": summary.not_applicable_count,
            "high_severity": summary.high_severity_count,
            "medium_severity": summary.medium_severity_count,
        },
        "results": [
            {
                "rule_id": r.rule_id,
                "category": r.rule.get("category", ""),
                "risk_pattern": r.rule.get("risk_pattern", ""),
                "status": r.status,
                "severity": r.severity,
                "clause_reference": r.compliance.get("clause_reference", ""),
                "reason": r.compliance.get("reason", ""),
                "recommendation": r.compliance.get("recommendation", ""),
                "success": r.success,
                "error": r.error,
                "elapsed_seconds": r.elapsed_seconds,
            }
            for r in summary.results
        ],
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filename


def print_batch_summary(summary: BatchAuditSummary) -> None:
    """印出批次稽核摘要"""
    print("\n" + "=" * 80)
    print("  批次稽核摘要")
    print("=" * 80)
    print(f"  執行時間: {summary.elapsed_seconds:.1f} 秒")
    print(f"  規則總數: {summary.total_rules}")
    print(f"  完成: {summary.completed}  |  失敗: {summary.failed}  |  略過: {summary.skipped}")
    print("-" * 80)
    print(f"  RISK_DETECTED: {summary.risk_detected_count}")
    print(f"  COMPLIANT:     {summary.compliant_count}")
    print(f"  UNCERTAIN:     {summary.uncertain_count}")
    print(f"  NOT_APPLICABLE:{summary.not_applicable_count}")
    print("-" * 80)
    print(f"  HIGH 風險: {summary.high_severity_count}  |  MEDIUM 風險: {summary.medium_severity_count}")
    print("=" * 80)

    # 逐規則摘要
    if summary.results:
        print("\n  逐規則結果:")
        print(f"  {'Rule ID':<12} {'Category':<16} {'Status':<18} {'Severity':<10} {'Time':<8}")
        print("  " + "-" * 68)
        for r in summary.results:
            category = r.rule.get("category", "")[:14]
            status_display = r.status if r.success else f"ERROR({r.error[:20]})" if r.error else "ERROR"
            print(
                f"  {r.rule_id:<12} {category:<16} {status_display:<18} {r.severity:<10} {r.elapsed_seconds:>5.1f}s"
            )
        print()


def default_progress_callback(current: int, total: int, rule_id: str) -> None:
    """預設進度顯示"""
    print(f"\n[{current}/{total}] 稽核 {rule_id}...")


def default_error_callback(rule_id: str, error: Exception) -> None:
    """預設錯誤顯示"""
    print(f"  {rule_id} 失敗: {error}")


# ==========================================
# CLI
# ==========================================

def main():
    """批次稽核 CLI 入口"""
    parser = argparse.ArgumentParser(
        description="契約批次稽核",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python audit_batch.py                                    # 全部規則
  python audit_batch.py --rule-ids RULE_001 RULE_005       # 指定規則
  python audit_batch.py --export docx                      # 批次 + 匯出
  python audit_batch.py --stop-on-error                    # 遇錯即停
        """,
    )
    parser.add_argument(
        "--rules-file",
        default=RULES_FILE,
        help=f"稽核規則 Excel 檔案路徑 (預設: {RULES_FILE})",
    )
    parser.add_argument(
        "--rule-ids",
        nargs="*",
        help="指定規則 ID (例: RULE_001 RULE_005)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"輸出目錄 (預設: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="遇到錯誤時停止執行",
    )
    parser.add_argument(
        "--export",
        choices=["pdf", "docx", "both"],
        help="批次完成後匯出報告",
    )

    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("  契約自動稽核 - 批次模式")
    print("=" * 80)

    # 載入規則
    print("\n載入稽核規則...")
    rules = load_audit_rules(args.rules_file)

    if not rules:
        print("無法載入規則，程式結束。")
        sys.exit(1)

    print(f"成功載入 {len(rules)} 條規則")

    if args.rule_ids:
        print(f"指定執行: {', '.join(args.rule_ids)}")

    # 執行批次稽核
    summary = run_batch_audit(
        rules=rules,
        rule_ids=args.rule_ids,
        on_progress=default_progress_callback,
        on_error=default_error_callback,
        stop_on_error=args.stop_on_error,
    )

    # 印出摘要
    print_batch_summary(summary)

    # 儲存彙總
    output_dir = Path(args.output_dir)
    summary_path = save_batch_summary(summary, output_dir)
    print(f"批次彙總已儲存: {summary_path}")

    # 匯出報告
    if args.export:
        try:
            from report_export import export_report

            formats = ["pdf", "docx"] if args.export == "both" else [args.export]
            paths = export_report(summary, output_dir, formats=formats)
            for p in paths:
                print(f"報告已匯出: {p}")
        except ImportError:
            print("報告匯出模組 (report_export) 尚未安裝，略過匯出。")
        except Exception as e:
            print(f"報告匯出失敗: {e}")


if __name__ == "__main__":
    main()

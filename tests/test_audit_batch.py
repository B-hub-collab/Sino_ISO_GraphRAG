"""
tests/test_audit_batch.py

audit_batch.py 的單元測試。
使用 unittest.mock patch 取代 LLM / Neo4j 呼叫，
全部測試不需要外部服務。
"""

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from audit_batch import (
    AuditResult,
    BatchAuditSummary,
    audit_rule_noninteractive,
    default_error_callback,
    default_progress_callback,
    print_batch_summary,
    run_batch_audit,
    save_batch_summary,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ==========================================
# Helpers
# ==========================================

def _make_rule(rule_id: str = "RULE_001", category: str = "責任險") -> dict:
    return {
        "id": rule_id,
        "category": category,
        "risk_pattern": "甲方/機關為受益人",
        "action": "發出提醒",
        "explanation": "責任險應以被保險人為受益人。",
    }


def _make_compliance(status: str = "COMPLIANT", severity: str = "LOW") -> dict:
    return {
        "status": status,
        "severity": severity,
        "reason": "測試理由",
        "evidence": "第十條",
        "clause_reference": "第十條",
        "recommendation": "維持現有條款",
    }


def _make_query_info() -> dict:
    return {
        "graph_query": "請檢索契約中責任險條款",
        "key_terms": ["責任險", "受益人"],
        "search_focus": "受益人確認",
    }


def _make_rag_result(success: bool = True) -> dict:
    return {
        "success": success,
        "answer": "第十條未發現問題。" if success else "查詢失敗",
    }


# ==========================================
# AuditResult
# ==========================================

class TestAuditResult:
    def test_rule_id_property(self):
        r = AuditResult(
            rule=_make_rule("RULE_005"),
            query_info=_make_query_info(),
            rag_result=_make_rag_result(),
            compliance=_make_compliance(),
            elapsed_seconds=1.0,
            success=True,
        )
        assert r.rule_id == "RULE_005"

    def test_status_property(self):
        r = AuditResult(
            rule=_make_rule(),
            query_info=_make_query_info(),
            rag_result=_make_rag_result(),
            compliance=_make_compliance("RISK_DETECTED", "HIGH"),
            elapsed_seconds=1.0,
            success=True,
        )
        assert r.status == "RISK_DETECTED"

    def test_severity_property(self):
        r = AuditResult(
            rule=_make_rule(),
            query_info=_make_query_info(),
            rag_result=_make_rag_result(),
            compliance=_make_compliance("COMPLIANT", "LOW"),
            elapsed_seconds=1.0,
            success=True,
        )
        assert r.severity == "LOW"

    def test_error_default_none(self):
        r = AuditResult(
            rule=_make_rule(),
            query_info=_make_query_info(),
            rag_result=_make_rag_result(),
            compliance=_make_compliance(),
            elapsed_seconds=1.0,
            success=True,
        )
        assert r.error is None

    def test_missing_rule_id_returns_unknown(self):
        r = AuditResult(
            rule={},
            query_info={},
            rag_result={},
            compliance={},
            elapsed_seconds=0.0,
            success=False,
        )
        assert r.rule_id == "UNKNOWN"
        assert r.status == "ERROR"
        assert r.severity == "UNKNOWN"


# ==========================================
# BatchAuditSummary
# ==========================================

class TestBatchAuditSummary:
    def _make_summary(self, statuses_severities) -> BatchAuditSummary:
        results = [
            AuditResult(
                rule=_make_rule(f"RULE_{i:03d}"),
                query_info=_make_query_info(),
                rag_result=_make_rag_result(),
                compliance=_make_compliance(s, sev),
                elapsed_seconds=1.0,
                success=True,
            )
            for i, (s, sev) in enumerate(statuses_severities, 1)
        ]
        return BatchAuditSummary(
            total_rules=len(results),
            completed=len(results),
            results=results,
        )

    def test_risk_detected_count(self):
        s = self._make_summary([
            ("RISK_DETECTED", "HIGH"),
            ("RISK_DETECTED", "MEDIUM"),
            ("COMPLIANT", "LOW"),
        ])
        assert s.risk_detected_count == 2

    def test_compliant_count(self):
        s = self._make_summary([("COMPLIANT", "LOW"), ("COMPLIANT", "LOW")])
        assert s.compliant_count == 2

    def test_uncertain_count(self):
        s = self._make_summary([("UNCERTAIN", "LOW"), ("COMPLIANT", "LOW")])
        assert s.uncertain_count == 1

    def test_not_applicable_count(self):
        s = self._make_summary([("NOT_APPLICABLE", "LOW")])
        assert s.not_applicable_count == 1

    def test_high_severity_count(self):
        s = self._make_summary([
            ("RISK_DETECTED", "HIGH"),
            ("RISK_DETECTED", "MEDIUM"),
        ])
        assert s.high_severity_count == 1

    def test_medium_severity_count(self):
        s = self._make_summary([
            ("RISK_DETECTED", "HIGH"),
            ("RISK_DETECTED", "MEDIUM"),
            ("COMPLIANT", "LOW"),
        ])
        assert s.medium_severity_count == 1

    def test_empty_summary(self):
        s = BatchAuditSummary()
        assert s.risk_detected_count == 0
        assert s.compliant_count == 0
        assert s.high_severity_count == 0


# ==========================================
# audit_rule_noninteractive
# ==========================================

class TestAuditRuleNoninteractive:
    def test_success_flow(self):
        rule = _make_rule("RULE_001")
        query_fn = MagicMock(return_value=_make_query_info())
        search_fn = MagicMock(return_value=_make_rag_result())
        analyze_fn = MagicMock(return_value=_make_compliance())

        result = audit_rule_noninteractive(
            rule,
            generate_query_fn=query_fn,
            search_fn=search_fn,
            analyze_fn=analyze_fn,
        )

        assert result.success is True
        assert result.rule_id == "RULE_001"
        assert result.status == "COMPLIANT"
        assert result.error is None
        assert result.elapsed_seconds >= 0

    def test_functions_called_in_order(self):
        """三個函數依序被呼叫，且傳入正確參數"""
        rule = _make_rule()
        query_info = _make_query_info()
        rag_result = _make_rag_result()
        compliance = _make_compliance()

        query_fn = MagicMock(return_value=query_info)
        search_fn = MagicMock(return_value=rag_result)
        analyze_fn = MagicMock(return_value=compliance)

        audit_rule_noninteractive(rule, query_fn, search_fn, analyze_fn)

        query_fn.assert_called_once_with(rule)
        search_fn.assert_called_once_with(query_info["graph_query"])
        analyze_fn.assert_called_once_with(rule, query_info, rag_result)

    def test_generate_query_raises_returns_error_result(self):
        rule = _make_rule("RULE_ERR")
        query_fn = MagicMock(side_effect=RuntimeError("LLM timeout"))
        search_fn = MagicMock()
        analyze_fn = MagicMock()

        result = audit_rule_noninteractive(rule, query_fn, search_fn, analyze_fn)

        assert result.success is False
        assert result.rule_id == "RULE_ERR"
        assert result.status == "ERROR"
        assert "LLM timeout" in (result.error or "")
        search_fn.assert_not_called()
        analyze_fn.assert_not_called()

    def test_search_raises_returns_error_result(self):
        query_fn = MagicMock(return_value=_make_query_info())
        search_fn = MagicMock(side_effect=ConnectionError("Neo4j 連線失敗"))
        analyze_fn = MagicMock()

        result = audit_rule_noninteractive(
            _make_rule(), query_fn, search_fn, analyze_fn
        )

        assert result.success is False
        assert "Neo4j" in (result.error or "")
        analyze_fn.assert_not_called()

    def test_analyze_raises_returns_error_result(self):
        query_fn = MagicMock(return_value=_make_query_info())
        search_fn = MagicMock(return_value=_make_rag_result())
        analyze_fn = MagicMock(side_effect=ValueError("解析錯誤"))

        result = audit_rule_noninteractive(
            _make_rule(), query_fn, search_fn, analyze_fn
        )

        assert result.success is False
        assert "解析錯誤" in (result.error or "")

    def test_elapsed_seconds_recorded(self):
        query_fn = MagicMock(return_value=_make_query_info())
        search_fn = MagicMock(return_value=_make_rag_result())
        analyze_fn = MagicMock(return_value=_make_compliance())

        result = audit_rule_noninteractive(
            _make_rule(), query_fn, search_fn, analyze_fn
        )

        assert isinstance(result.elapsed_seconds, float)
        assert result.elapsed_seconds >= 0

    def test_uses_default_functions_when_none_provided(self):
        """未傳入函數時，使用 audit_agent_interactive 的預設函數"""
        # 只測試不傳參數時不會 TypeError，實際呼叫 patch 掉
        with (
            patch("audit_batch.generate_optimized_query", return_value=_make_query_info()) as mock_q,
            patch("audit_batch.query_contract_local_search", return_value=_make_rag_result()) as mock_s,
            patch("audit_batch.analyze_compliance", return_value=_make_compliance()) as mock_a,
        ):
            result = audit_rule_noninteractive(_make_rule())
            mock_q.assert_called_once()
            mock_s.assert_called_once()
            mock_a.assert_called_once()
            assert result.success is True


# ==========================================
# run_batch_audit
# ==========================================

def _mock_fns(status: str = "COMPLIANT", severity: str = "LOW"):
    return (
        MagicMock(return_value=_make_query_info()),
        MagicMock(return_value=_make_rag_result()),
        MagicMock(return_value=_make_compliance(status, severity)),
    )


class TestRunBatchAudit:
    def test_all_rules_executed(self):
        rules = [_make_rule(f"RULE_{i:03d}") for i in range(1, 4)]
        q, s, a = _mock_fns()

        summary = run_batch_audit(rules, generate_query_fn=q, search_fn=s, analyze_fn=a)

        assert summary.total_rules == 3
        assert summary.completed == 3
        assert summary.failed == 0
        assert len(summary.results) == 3

    def test_filter_by_rule_ids(self):
        rules = [_make_rule(f"RULE_{i:03d}") for i in range(1, 6)]
        q, s, a = _mock_fns()

        summary = run_batch_audit(
            rules,
            rule_ids=["RULE_001", "RULE_003"],
            generate_query_fn=q,
            search_fn=s,
            analyze_fn=a,
        )

        assert summary.total_rules == 2
        assert {r.rule_id for r in summary.results} == {"RULE_001", "RULE_003"}

    def test_skipped_count_with_filter(self):
        rules = [_make_rule(f"RULE_{i:03d}") for i in range(1, 6)]
        q, s, a = _mock_fns()

        summary = run_batch_audit(
            rules,
            rule_ids=["RULE_001"],
            generate_query_fn=q,
            search_fn=s,
            analyze_fn=a,
        )

        assert summary.skipped == 4

    def test_stop_on_error(self):
        rules = [_make_rule(f"RULE_{i:03d}") for i in range(1, 5)]

        def fail_on_second(rule):
            if rule["id"] == "RULE_002":
                raise RuntimeError("simulate failure")
            return _make_query_info()

        q = MagicMock(side_effect=fail_on_second)
        s = MagicMock(return_value=_make_rag_result())
        a = MagicMock(return_value=_make_compliance())

        summary = run_batch_audit(
            rules,
            stop_on_error=True,
            generate_query_fn=q,
            search_fn=s,
            analyze_fn=a,
        )

        # RULE_001 成功，RULE_002 失敗後停止，RULE_003/004 不執行
        assert summary.completed == 1
        assert summary.failed == 1
        assert len(summary.results) == 2

    def test_continue_on_error_by_default(self):
        rules = [_make_rule(f"RULE_{i:03d}") for i in range(1, 4)]

        def fail_on_second(rule):
            if rule["id"] == "RULE_002":
                raise RuntimeError("simulate failure")
            return _make_query_info()

        q = MagicMock(side_effect=fail_on_second)
        s = MagicMock(return_value=_make_rag_result())
        a = MagicMock(return_value=_make_compliance())

        summary = run_batch_audit(rules, generate_query_fn=q, search_fn=s, analyze_fn=a)

        # 全部三條都執行到
        assert len(summary.results) == 3
        assert summary.completed == 2
        assert summary.failed == 1

    def test_progress_callback_called(self):
        rules = [_make_rule(f"RULE_{i:03d}") for i in range(1, 4)]
        q, s, a = _mock_fns()
        progress_calls = []

        def on_progress(current, total, rule_id):
            progress_calls.append((current, total, rule_id))

        run_batch_audit(rules, on_progress=on_progress, generate_query_fn=q, search_fn=s, analyze_fn=a)

        assert len(progress_calls) == 3
        assert progress_calls[0] == (1, 3, "RULE_001")
        assert progress_calls[2] == (3, 3, "RULE_003")

    def test_error_callback_called_on_failure(self):
        rules = [_make_rule("RULE_001"), _make_rule("RULE_002")]

        def fail_always(rule):
            raise RuntimeError("always fail")

        error_calls = []

        def on_error(rule_id, exc):
            error_calls.append((rule_id, str(exc)))

        run_batch_audit(
            rules,
            on_error=on_error,
            generate_query_fn=MagicMock(side_effect=fail_always),
            search_fn=MagicMock(),
            analyze_fn=MagicMock(),
        )

        assert len(error_calls) == 2
        assert error_calls[0][0] == "RULE_001"

    def test_start_end_time_set(self):
        rules = [_make_rule()]
        q, s, a = _mock_fns()

        summary = run_batch_audit(rules, generate_query_fn=q, search_fn=s, analyze_fn=a)

        assert summary.start_time
        assert summary.end_time
        assert summary.elapsed_seconds >= 0

    def test_empty_rules_list(self):
        summary = run_batch_audit([])
        assert summary.total_rules == 0
        assert summary.completed == 0
        assert summary.results == []

    def test_individual_results_saved(self, tmp_path):
        """run_batch_audit 內部會呼叫 save_result 儲存個別 JSON"""
        rules = [_make_rule("RULE_001")]
        q, s, a = _mock_fns()

        with patch("audit_batch.save_result") as mock_save:
            run_batch_audit(rules, generate_query_fn=q, search_fn=s, analyze_fn=a)
            mock_save.assert_called_once()


# ==========================================
# save_batch_summary
# ==========================================

class TestSaveBatchSummary:
    def _make_full_summary(self) -> BatchAuditSummary:
        results = [
            AuditResult(
                rule=_make_rule("RULE_001"),
                query_info=_make_query_info(),
                rag_result=_make_rag_result(),
                compliance=_make_compliance("RISK_DETECTED", "HIGH"),
                elapsed_seconds=5.0,
                success=True,
            ),
            AuditResult(
                rule=_make_rule("RULE_002"),
                query_info=_make_query_info(),
                rag_result=_make_rag_result(),
                compliance=_make_compliance("COMPLIANT", "LOW"),
                elapsed_seconds=3.0,
                success=True,
            ),
        ]
        return BatchAuditSummary(
            total_rules=2,
            completed=2,
            failed=0,
            skipped=0,
            results=results,
            start_time="2026-02-26T10:00:00",
            end_time="2026-02-26T10:01:00",
            elapsed_seconds=60.0,
        )

    def test_file_created(self, tmp_path: Path):
        summary = self._make_full_summary()
        path = save_batch_summary(summary, tmp_path)
        assert path.exists()

    def test_filename_pattern(self, tmp_path: Path):
        summary = self._make_full_summary()
        path = save_batch_summary(summary, tmp_path)
        assert path.name.startswith("batch_summary_")
        assert path.suffix == ".json"

    def test_json_structure(self, tmp_path: Path):
        summary = self._make_full_summary()
        path = save_batch_summary(summary, tmp_path)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert "batch_id" in data
        assert "start_time" in data
        assert "end_time" in data
        assert "elapsed_seconds" in data
        assert "total_rules" in data
        assert "statistics" in data
        assert "results" in data

    def test_statistics_correct(self, tmp_path: Path):
        summary = self._make_full_summary()
        path = save_batch_summary(summary, tmp_path)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        stats = data["statistics"]
        assert stats["risk_detected"] == 1
        assert stats["compliant"] == 1
        assert stats["high_severity"] == 1

    def test_results_list_length(self, tmp_path: Path):
        summary = self._make_full_summary()
        path = save_batch_summary(summary, tmp_path)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert len(data["results"]) == 2

    def test_result_fields_present(self, tmp_path: Path):
        summary = self._make_full_summary()
        path = save_batch_summary(summary, tmp_path)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        result = data["results"][0]
        for field in ["rule_id", "category", "status", "severity", "reason", "success"]:
            assert field in result

    def test_creates_output_dir_if_missing(self, tmp_path: Path):
        new_dir = tmp_path / "nested" / "output"
        summary = self._make_full_summary()
        path = save_batch_summary(summary, new_dir)
        assert path.exists()

    def test_valid_json_encoding(self, tmp_path: Path):
        """中文內容可正確序列化"""
        summary = self._make_full_summary()
        path = save_batch_summary(summary, tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "責任險" in text


# ==========================================
# print_batch_summary (smoke tests)
# ==========================================

class TestPrintBatchSummary:
    def _make_summary_with(self, statuses_severities) -> BatchAuditSummary:
        results = [
            AuditResult(
                rule=_make_rule(f"RULE_{i:03d}"),
                query_info=_make_query_info(),
                rag_result=_make_rag_result(),
                compliance=_make_compliance(s, sev),
                elapsed_seconds=1.0,
                success=True,
            )
            for i, (s, sev) in enumerate(statuses_severities, 1)
        ]
        return BatchAuditSummary(
            total_rules=len(results), completed=len(results), results=results
        )

    def test_no_crash_normal(self, capsys):
        summary = self._make_summary_with([
            ("RISK_DETECTED", "HIGH"),
            ("COMPLIANT", "LOW"),
        ])
        print_batch_summary(summary)
        out = capsys.readouterr().out
        assert "RISK_DETECTED" in out
        assert "COMPLIANT" in out

    def test_no_crash_empty(self, capsys):
        summary = BatchAuditSummary()
        print_batch_summary(summary)
        out = capsys.readouterr().out
        assert "批次稽核摘要" in out

    def test_failed_result_shows_error(self, capsys):
        results = [
            AuditResult(
                rule=_make_rule("RULE_ERR"),
                query_info={},
                rag_result={},
                compliance={"status": "ERROR", "severity": "UNKNOWN"},
                elapsed_seconds=0.5,
                success=False,
                error="模擬錯誤訊息",
            )
        ]
        summary = BatchAuditSummary(
            total_rules=1, completed=0, failed=1, results=results
        )
        print_batch_summary(summary)
        out = capsys.readouterr().out
        assert "ERROR" in out


# ==========================================
# Callback helpers
# ==========================================

class TestDefaultCallbacks:
    def test_progress_callback_output(self, capsys):
        default_progress_callback(2, 5, "RULE_002")
        out = capsys.readouterr().out
        assert "2" in out
        assert "5" in out
        assert "RULE_002" in out

    def test_error_callback_output(self, capsys):
        default_error_callback("RULE_003", Exception("test error"))
        out = capsys.readouterr().out
        assert "RULE_003" in out
        assert "test error" in out

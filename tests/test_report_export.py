"""
tests/test_report_export.py

report_export.py 的單元測試。
不需要 Neo4j / OpenAI 連線，全部為本地邏輯測試。
"""

import json
import sys
from pathlib import Path

import pytest

# 確保 contracts/ 在路徑上
sys.path.insert(0, str(Path(__file__).parent.parent))

from report_export import (
    ReportData,
    _build_report_data,
    _build_report_data_from_summary,
    _escape_xml,
    export_report,
    export_to_docx,
    export_to_pdf,
    load_audit_results,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ==========================================
# Fixtures
# ==========================================

@pytest.fixture
def single_report_json(tmp_path: Path) -> Path:
    """複製單一稽核報告 JSON 到 tmp_path"""
    src = FIXTURES / "sample_audit_report.json"
    dst = tmp_path / "稽核_RULE_002_20260226_100000.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


@pytest.fixture
def multi_report_dir(tmp_path: Path) -> Path:
    """建立含兩份稽核 JSON 的目錄"""
    src = FIXTURES / "sample_audit_report.json"
    base = json.loads(src.read_text(encoding="utf-8"))

    for rule_id, status, severity in [
        ("RULE_001", "COMPLIANT", "LOW"),
        ("RULE_002", "RISK_DETECTED", "HIGH"),
        ("RULE_003", "UNCERTAIN", "LOW"),
    ]:
        report = dict(base)
        report["rule"] = dict(base["rule"], id=rule_id)
        report["compliance_analysis"] = dict(
            base["compliance_analysis"], status=status, severity=severity
        )
        (tmp_path / f"稽核_{rule_id}_20260226_100000.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return tmp_path


@pytest.fixture
def batch_summary_json(tmp_path: Path) -> Path:
    """複製 batch_summary JSON 到 tmp_path"""
    src = FIXTURES / "sample_batch_summary.json"
    dst = tmp_path / "batch_summary_20260226_100000.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


@pytest.fixture
def sample_report_data(multi_report_dir: Path) -> ReportData:
    return load_audit_results(multi_report_dir)


# ==========================================
# 資料載入
# ==========================================

class TestLoadAuditResults:
    def test_load_from_directory(self, multi_report_dir: Path):
        data = load_audit_results(multi_report_dir)
        assert isinstance(data, ReportData)
        assert data.rules_audited == 3

    def test_load_from_single_json(self, single_report_json: Path):
        data = load_audit_results(single_report_json)
        assert isinstance(data, ReportData)
        assert data.rules_audited == 1

    def test_load_from_batch_summary_json(self, batch_summary_json: Path):
        data = load_audit_results(batch_summary_json)
        assert isinstance(data, ReportData)
        assert data.rules_audited == 3

    def test_load_invalid_source_raises(self, tmp_path: Path):
        with pytest.raises((ValueError, FileNotFoundError)):
            load_audit_results(tmp_path / "nonexistent_path")

    def test_load_empty_directory_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_audit_results(tmp_path)

    def test_title_default(self, multi_report_dir: Path):
        data = load_audit_results(multi_report_dir)
        assert data.title == "契約稽核報告"

    def test_generated_at_set(self, multi_report_dir: Path):
        data = load_audit_results(multi_report_dir)
        assert data.generated_at  # 不為空


# ==========================================
# 統計計算
# ==========================================

class TestBuildReportData:
    def _make_result(self, status: str, severity: str) -> dict:
        return {
            "rule": {"id": "RULE_001", "category": "test", "risk_pattern": "test", "action": "", "explanation": ""},
            "query_generation": {},
            "local_search_result": {"success": True, "answer": ""},
            "compliance_analysis": {"status": status, "severity": severity, "reason": "", "evidence": "", "clause_reference": "", "recommendation": ""},
        }

    def test_risk_detected_count(self):
        results = [
            self._make_result("RISK_DETECTED", "HIGH"),
            self._make_result("RISK_DETECTED", "MEDIUM"),
            self._make_result("COMPLIANT", "LOW"),
        ]
        data = _build_report_data(results)
        assert data.summary_stats["RISK_DETECTED"] == 2
        assert data.summary_stats["COMPLIANT"] == 1

    def test_severity_count(self):
        results = [
            self._make_result("RISK_DETECTED", "HIGH"),
            self._make_result("RISK_DETECTED", "MEDIUM"),
            self._make_result("COMPLIANT", "LOW"),
        ]
        data = _build_report_data(results)
        assert data.severity_stats["HIGH"] == 1
        assert data.severity_stats["MEDIUM"] == 1
        assert data.severity_stats["LOW"] == 1

    def test_empty_results(self):
        data = _build_report_data([])
        assert data.rules_audited == 0
        assert data.summary_stats["RISK_DETECTED"] == 0

    def test_uncertain_and_not_applicable(self):
        results = [
            self._make_result("UNCERTAIN", "LOW"),
            self._make_result("NOT_APPLICABLE", "LOW"),
        ]
        data = _build_report_data(results)
        assert data.summary_stats["UNCERTAIN"] == 1
        assert data.summary_stats["NOT_APPLICABLE"] == 1

    def test_rules_audited_count(self):
        results = [self._make_result("COMPLIANT", "LOW") for _ in range(5)]
        data = _build_report_data(results)
        assert data.rules_audited == 5


class TestBuildReportDataFromSummary:
    def test_statistics_mapped_correctly(self):
        raw = {
            "batch_id": "batch_test",
            "total_rules": 5,
            "end_time": "2026-02-26T10:00:00",
            "statistics": {
                "risk_detected": 2,
                "compliant": 2,
                "uncertain": 1,
                "not_applicable": 0,
                "high_severity": 1,
                "medium_severity": 1,
            },
        }
        data = _build_report_data_from_summary(raw)
        assert data.rules_audited == 5
        assert data.summary_stats["RISK_DETECTED"] == 2
        assert data.severity_stats["HIGH"] == 1

    def test_empty_results_list(self):
        raw = {
            "batch_id": "batch_test",
            "total_rules": 0,
            "end_time": "2026-02-26T10:00:00",
            "statistics": {},
        }
        data = _build_report_data_from_summary(raw)
        assert data.results == []


# ==========================================
# _escape_xml
# ==========================================

class TestEscapeXml:
    def test_ampersand(self):
        assert _escape_xml("A & B") == "A &amp; B"

    def test_less_than(self):
        assert _escape_xml("a < b") == "a &lt; b"

    def test_greater_than(self):
        assert _escape_xml("a > b") == "a &gt; b"

    def test_double_quote(self):
        assert _escape_xml('say "hello"') == "say &quot;hello&quot;"

    def test_combined(self):
        result = _escape_xml('<tag attr="v">&</tag>')
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result
        assert "&quot;" in result

    def test_empty_string(self):
        assert _escape_xml("") == ""

    def test_none_returns_empty(self):
        assert _escape_xml(None) == ""

    def test_no_special_chars_unchanged(self):
        assert _escape_xml("正常文字 normal text") == "正常文字 normal text"


# ==========================================
# docx 匯出
# ==========================================

class TestExportToDocx:
    def test_file_created(self, sample_report_data: ReportData, tmp_path: Path):
        output = tmp_path / "report.docx"
        export_to_docx(sample_report_data, output)
        assert output.exists()

    def test_file_non_empty(self, sample_report_data: ReportData, tmp_path: Path):
        output = tmp_path / "report.docx"
        export_to_docx(sample_report_data, output)
        assert output.stat().st_size > 1000

    def test_returns_output_path(self, sample_report_data: ReportData, tmp_path: Path):
        output = tmp_path / "report.docx"
        result = export_to_docx(sample_report_data, output)
        assert result == output

    def test_valid_docx_format(self, sample_report_data: ReportData, tmp_path: Path):
        """產生的檔案可被 python-docx 讀取"""
        from docx import Document

        output = tmp_path / "report.docx"
        export_to_docx(sample_report_data, output)
        doc = Document(str(output))
        # 確認有標題段落
        assert any(p.text for p in doc.paragraphs)

    def test_empty_results_no_crash(self, tmp_path: Path):
        data = ReportData(
            title="空報告", generated_at="2026-02-26", rules_audited=0
        )
        output = tmp_path / "empty.docx"
        export_to_docx(data, output)
        assert output.exists()

    def test_special_chars_in_content(self, tmp_path: Path):
        """包含 XML 特殊字元的內容不會導致匯出失敗"""
        results = [{
            "rule": {"id": "RULE_001", "category": "test & <check>", "risk_pattern": "a > b", "action": "", "explanation": ""},
            "query_generation": {"graph_query": 'query "test"', "key_terms": []},
            "local_search_result": {"success": True, "answer": "內容 & 更多 <內容>"},
            "compliance_analysis": {"status": "COMPLIANT", "severity": "LOW", "reason": "", "evidence": "", "clause_reference": "", "recommendation": ""},
        }]
        data = _build_report_data(results)
        output = tmp_path / "special.docx"
        export_to_docx(data, output)
        assert output.exists()


# ==========================================
# PDF 匯出
# ==========================================

class TestExportToPdf:
    def test_file_created(self, sample_report_data: ReportData, tmp_path: Path):
        output = tmp_path / "report.pdf"
        export_to_pdf(sample_report_data, output)
        assert output.exists()

    def test_file_non_empty(self, sample_report_data: ReportData, tmp_path: Path):
        output = tmp_path / "report.pdf"
        export_to_pdf(sample_report_data, output)
        assert output.stat().st_size > 1000

    def test_returns_output_path(self, sample_report_data: ReportData, tmp_path: Path):
        output = tmp_path / "report.pdf"
        result = export_to_pdf(sample_report_data, output)
        assert result == output

    def test_valid_pdf_header(self, sample_report_data: ReportData, tmp_path: Path):
        """確認輸出為合法 PDF（以 %PDF- 開頭）"""
        output = tmp_path / "report.pdf"
        export_to_pdf(sample_report_data, output)
        header = output.read_bytes()[:5]
        assert header == b"%PDF-"

    def test_empty_results_no_crash(self, tmp_path: Path):
        data = ReportData(
            title="空報告", generated_at="2026-02-26", rules_audited=0
        )
        output = tmp_path / "empty.pdf"
        export_to_pdf(data, output)
        assert output.exists()


# ==========================================
# export_report 高階函數
# ==========================================

class TestExportReport:
    def test_export_docx_only(self, multi_report_dir: Path, tmp_path: Path):
        paths = export_report(multi_report_dir, tmp_path, formats=["docx"])
        assert len(paths) == 1
        assert paths[0].suffix == ".docx"
        assert paths[0].exists()

    def test_export_pdf_only(self, multi_report_dir: Path, tmp_path: Path):
        paths = export_report(multi_report_dir, tmp_path, formats=["pdf"])
        assert len(paths) == 1
        assert paths[0].suffix == ".pdf"

    def test_export_both_formats(self, multi_report_dir: Path, tmp_path: Path):
        paths = export_report(multi_report_dir, tmp_path, formats=["docx", "pdf"])
        assert len(paths) == 2
        suffixes = {p.suffix for p in paths}
        assert suffixes == {".docx", ".pdf"}

    def test_filename_prefix(self, multi_report_dir: Path, tmp_path: Path):
        paths = export_report(multi_report_dir, tmp_path, formats=["docx"], filename_prefix="my_report")
        assert paths[0].name.startswith("my_report_")

    def test_output_dir_created(self, multi_report_dir: Path, tmp_path: Path):
        new_dir = tmp_path / "new_subdir"
        export_report(multi_report_dir, new_dir, formats=["docx"])
        assert new_dir.exists()

    def test_default_format_is_docx(self, multi_report_dir: Path, tmp_path: Path):
        paths = export_report(multi_report_dir, tmp_path)
        assert len(paths) == 1
        assert paths[0].suffix == ".docx"

    def test_unsupported_format_skipped(self, multi_report_dir: Path, tmp_path: Path):
        paths = export_report(multi_report_dir, tmp_path, formats=["txt"])
        assert len(paths) == 0

    def test_from_batch_summary_json(self, batch_summary_json: Path, tmp_path: Path):
        paths = export_report(batch_summary_json, tmp_path, formats=["docx"])
        assert len(paths) == 1
        assert paths[0].exists()

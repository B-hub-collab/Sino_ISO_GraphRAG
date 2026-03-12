# Changelog

所有重要的專案變更都會記錄在此檔案。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)，
版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

## [Unreleased]

### 計劃中
- 批次稽核模式
- 稽核報告匯出（PDF/Word）
- 單元測試框架
- GitHub Actions CI/CD

## [0.1.0] - 2026-01-14

### Added
- 初始專案建立
- 稽核代理人互動式介面 (audit_agent_interactive.py)
- Agentic RAG 系統 (agent_graph/)
- Query Generation Agent - 自動優化查詢語句
- GraphRAG Local Search 整合
- LLM 合規性分析
- JSON 格式稽核報告輸出
- 支援多種查詢引擎（Cypher、Local Search、GraphRAG Global、Hybrid）
- 專案文檔 (README.md、claude.md)
- Git 版本控制規範
- Code Style 規範（不使用 emoji）

### Technical Details
- 使用 Azure OpenAI (o4-mini)
- LangGraph 狀態圖框架
- Neo4j 圖資料庫整合
- Microsoft GraphRAG CLI 整合

---

## 變更類型說明

- `Added` - 新功能
- `Changed` - 既有功能變更
- `Deprecated` - 即將移除的功能
- `Removed` - 已移除的功能
- `Fixed` - Bug 修復
- `Security` - 安全性修正

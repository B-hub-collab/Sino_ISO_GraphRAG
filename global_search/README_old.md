# Global Search - Neo4j 全域社群搜尋

此資料夾包含 Neo4j Global Search 的實現和測試。

## 檔案說明

- **`neo4j_global_search.py`**: Global Search 核心模組
  - Map-Reduce 架構
  - 社群摘要檢索與分析
  - 基於社群的全域問答

- **`test_global_search.py`**: 完整測試套件
  - 社群檢索測試
  - Map 階段測試
  - 完整 Global Search 流程測試

## 使用方法

### 直接使用
```python
from global_search import Neo4jGlobalSearch
from langchain_neo4j import Neo4jGraph
from langchain_openai import AzureChatOpenAI

# 初始化
graph = Neo4jGraph(url="...", username="...", password="...")
llm = AzureChatOpenAI(...)

# 創建 Global Search
global_search = Neo4jGlobalSearch(
    graph=graph,
    llm=llm,
    level=0,                      # 社群層級
    max_communities=10,           # 最多檢索社群數
    importance_threshold=5.0      # 重要性閾值
)

# 執行搜尋
answer = global_search.search("這份契約的主要風險有哪些？")
print(answer)
```

### 運行測試
```bash
conda run -n graphrag310 python global_search/test_global_search.py
```

## Global Search 架構（Map-Reduce）

### 1. Retrieve階段
從 Neo4j 檢索指定層級的社群摘要（Community Reports）

### 2. Map 階段
對每個社群摘要：
- 提取與查詢相關的要點
- LLM 評分（0-10）
- 輸出: `{points: [...], rating: 0-10}`

### 3. Reduce 階段
- 過濾低分要點（threshold: 5.0）
- 聚合所有高分要點
- 生成連貫的最終答案

## 適用場景

- 全域性問題（需要整體理解）
- 摘要性查詢（風險分析、主題總結）
- 概念性問題（不聚焦特定實體）

## 與 GraphRAG CLI 對比

| 特性 | GraphRAG CLI | Neo4j Global Search |
|------|--------------|---------------------|
| 數據源 | Parquet 檔案 | Neo4j 圖資料庫 |
| 可配置性 | 固定 | 高度可配置 |
| 整合性 | 獨立工具 | LangChain 整合 |

# Local Search - Neo4j 局部圖探索

此資料夾包含 Neo4j Local Search 的實現和測試。

## 檔案說明

- **`neo4j_local_search.py`**: Local Search 核心模組
  - 實體提取與匹配
  - 局部子圖檢索
  - 基於圖結構的問答

- **`test_local_search.py`**: 完整測試套件
  - 單元測試（實體提取、匹配、子圖檢索）
  - 整合測試（完整 Local Search 流程）

## 使用方法

### 直接使用
```python
from local_search import Neo4jLocalSearch
from langchain_neo4j import Neo4jGraph
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

# 初始化
graph = Neo4jGraph(url="...", username="...", password="...")
llm = AzureChatOpenAI(...)
embeddings = AzureOpenAIEmbeddings(...)

# 創建 Local Search
local_search = Neo4jLocalSearch(graph=graph, llm=llm, embeddings=embeddings)

# 執行搜尋
answer = local_search.search("甲方與哪些實體關聯最緊密？", max_hops=2)
print(answer)
```

### 運行測試
```bash
conda run -n graphrag310 python local_search/test_local_search.py
```

## Local Search 架構

1. **實體提取**: 從用戶查詢中提取關鍵實體
2. **實體匹配**: 使用向量相似度匹配 Neo4j 中的實體
3. **子圖檢索**: 從匹配實體擴展 N 跳鄰居
4. **答案生成**: 基於子圖上下文生成回答

## 性能

- 平均查詢時間: ~26 秒
- 成功率: 100%
- 適用場景: 實體關係探索、局部網絡分析

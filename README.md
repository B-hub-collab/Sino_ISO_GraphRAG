# 契約自動稽核系統 (Contract Audit System)

基於 GraphRAG 和 Neo4j 的智能合同分析系統，支持多種搜索策略和自動化稽核。

## 專案結構

```
contracts/
├── data_pipeline/          # 📊 數據處理管線
│   ├── prepare_documents_for_graphrag.py  # PDF 切分
│   ├── import_with_apoc.py               # Neo4j 導入（主要）
│   ├── import_communities_only.py        # Community 導入
│   ├── setup_vector_index.py            # 向量索引建立
│   └── README.md
│
├── local_search/           # 🔍 Local Search 模組
│   ├── neo4j_local_search.py            # Local Search 核心
│   ├── test_local_search.py             # 測試套件
│   └── README.md
│
├── global_search/          # 🌐 Global Search 模組
│   ├── neo4j_global_search.py           # Global Search 核心（Map-Reduce）
│   ├── test_global_search.py            # 測試套件
│   └── README.md
│
├── agent_graph/            # 🤖 Agent 系統
│   ├── main.py                         # Agent 入口
│   ├── graph.py                        # LangGraph 定義
│   ├── nodes.py                        # Agent 節點
│   ├── state.py                        # State 定義
│   ├── prompts.py                      # Prompt 模板
│   └── neo4j_local_search.py          # (原始位置，保留向後兼容)
│
└── README.md               # 本文件
```

## 快速開始

### 1. 環境設定

```bash
# 安裝依賴
conda create -n graphrag310 python=3.10
conda activate graphrag310
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入 API keys
```

### 2. 數據處理流程

```bash
# Step 1: 文件切分
python data_pipeline/prepare_documents_for_graphrag.py

# Step 2: GraphRAG 索引
graphrag index

# Step 3: 導入 Neo4j
python data_pipeline/import_with_apoc.py --clear --auto-confirm

# Step 4: 建立向量索引
python data_pipeline/setup_vector_index.py
```

### 3. 使用搜索功能

#### Local Search (局部圖探索)
```python
from local_search import Neo4jLocalSearch

local_search = Neo4jLocalSearch(graph, llm, embeddings)
answer = local_search.search("甲方與哪些實體關聯最緊密？")
```

#### Global Search (全域摘要)
```python
from global_search import Neo4jGlobalSearch

global_search = Neo4jGlobalSearch(graph, llm)
answer = global_search.search("這份契約的主要風險有哪些？")
```

#### Agent 系統（整合多引擎）
```bash
python -m agent_graph.main
# 或
python -m agent_graph.main "甲方的主要責任是什麼？"
```

## 核心功能

### 🔍 Local Search
- 基於實體關係的局部圖探索
- 支持 N-hop 鄰居檢索
- 適用場景：實體關係分析、局部網絡探索

### 🌐 Global Search  
- Map-Reduce 架構處理社群摘要
- 適用場景：全域性問題、風險分析、主題總結

### 📊 Data Pipeline
- PDF 文件自動切分
- GraphRAG 索引構建
- Neo4j 數據導入與索引

### 🤖 Agent System
- 多引擎智能路由（Cypher, Local, Global, Hybrid）
- LangGraph 工作流
- 互動式查詢界面

## 技術棧

- **圖資料庫**: Neo4j Aura
- **GraphRAG**: Microsoft GraphRAG
- **LLM**: Azure OpenAI (GPT-4o-mini)
- **Embeddings**: Azure OpenAI (text-embedding-3-large)
- **框架**: LangChain, LangGraph

## 測試

```bash
# Local Search 測試
conda run -n graphrag310 python local_search/test_local_search.py

# Global Search 測試
conda run -n graphrag310 python global_search/test_global_search.py
```

## 專案進度

查看 [task.md](.gemini/antigravity/brain/task.md) 了解當前進度。

## License

MIT License

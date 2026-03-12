# Data Pipeline - 數據處理管線

此資料夾包含所有與文件切分、GraphRAG 索引、Neo4j 導入相關的腳本。

## 檔案說明

### 1. 文件準備
- **`prepare_documents_for_graphrag.py`**: 將 PDF 契約文件切分成適合 GraphRAG 的文本塊

### 2. Neo4j 導入
- **`import_with_apoc.py`**: 主要導入腳本（使用 APOC，適用於 Neo4j Aura）
  - 導入 Entities, Relationships, Communities, Text Units
  - 使用方法: `python import_with_apoc.py [--clear] [--auto-confirm]`

- **`import_graphrag_to_neo4j.py`**: 替代導入方案
  
- **`import_communities_only.py`**: 僅導入 Community 和 Community Reports
  - 用於補充現有數據庫

### 3. 索引建立
- **`setup_vector_index.py`**: 建立 Neo4j 向量索引
  - 為 Entity 節點創建向量索引
  - 支持語義搜索

## 使用流程

```bash
# Step 1: 準備文件
python data_pipeline/prepare_documents_for_graphrag.py

# Step 2: 運行 GraphRAG 索引（在專案根目錄）
graphrag index

# Step 3: 導入到 Neo4j
python data_pipeline/import_with_apoc.py --clear --auto-confirm

# Step 4: 建立向量索引
python data_pipeline/setup_vector_index.py
```

## 相關配置

- GraphRAG 配置: `../settings.yaml`
- 環境變數: `../.env`
- 輸入文件: `../input/`
- GraphRAG 輸出: `../output/`

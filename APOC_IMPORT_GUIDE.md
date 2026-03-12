# GraphRAG 至 Neo4j 導入指南（使用 APOC）

本指南說明如何使用官方 APOC 工具將 GraphRAG 輸出導入到 Neo4j 圖資料庫。

## 系統要求

- Neo4j 5.26+ 
- Python 3.8+
- APOC 擴展（包含 Hadoop Dependencies）

## 快速開始

### 1. 安裝 APOC

運行自動安裝腳本：

```bash
cd /home/boya/Sino_ISO/contracts
bash scripts/setup_apoc.sh
```

腳本將會：
- 下載 APOC Extended JAR
- 下載 APOC Hadoop Dependencies JAR（支持 Parquet）
- 配置 Neo4j（啟用文件導入）

**重要：** 安裝後需要重啟 Neo4j：

```bash
sudo systemctl restart neo4j
# 或
/path/to/neo4j/bin/neo4j restart
```

### 2. 驗證 APOC 安裝

在 Neo4j Browser 中執行：

```cypher
RETURN apoc.version()
```

應該返回 APOC 版本號。

### 3. 導入 GraphRAG 數據

使用 Python 腳本導入：

```bash
# 導入數據（不刪除現有數據）
python import_with_apoc.py

# 清空並導入（⚠️ 會刪除所有數據）
python import_with_apoc.py --clear --auto-confirm

# 指定自定義輸出目錄
python import_with_apoc.py --output-dir /path/to/graphrag/output
```

導入過程將：
1. 驗證 APOC 安裝
2. 創建約束和索引
3. 導入實體（Entities）
4. 導入關係（Relationships）
5. 導入社群（Communities）
6. 導入社群摘要（Community Reports）
7. 導入文本單元（Text Units）
8. 建立各類關係連接
9. 驗證導入結果

### 4. 建立向量索引

向量索引用於實體對齊功能：

```bash
# 執行所有步驟（創建索引、生成 embeddings、驗證）
python setup_vector_index.py --all

# 或分步執行：

# 步驟 1: 創建向量索引
python setup_vector_index.py --create

# 步驟 2: 生成 embeddings（可能需要較長時間）
python setup_vector_index.py --generate

# 步驟 3: 驗證索引狀態
python setup_vector_index.py --verify

# 步驟 4: 測試向量搜索
python setup_vector_index.py --test-search "契約條款"
```

**注意：** 生成 embeddings 會調用 Azure OpenAI API，可能需要 10-30 分鐘（取決於實體數量）。

## 驗證導入結果

### 在 Neo4j Browser 中查詢

```cypher
// 檢查實體數量
MATCH (e:Entity) RETURN count(e)

// 檢查關係數量
MATCH ()-[r:RELATED_TO]->() RETURN count(r)

// 檢查社群數量
MATCH (c:Community) RETURN count(c)

// 檢查文本單元數量
MATCH (t:TextUnit) RETURN count(t)

// 檢查實體類型分布
MATCH (e:Entity)
RETURN e.type AS type, count(*) AS count
ORDER BY count DESC
LIMIT 10

// 檢查社群層級
MATCH (c:Community)
RETURN c.level AS level, count(*) AS count
ORDER BY level

// 檢查向量索引
SHOW INDEXES
```

### 預期結果

導入成功後，您應該看到：
- **Entity**: > 100個實體
- **RELATED_TO**: > 100個關係
- **Community**: > 10個社群
- **TextUnit**: > 100個文本單元
- **向量索引**: 狀態為 ONLINE

## 文件結構

```
contracts/
├── scripts/
│   ├── apoc_import_graphrag.cypher  # Cypher 導入腳本
│   └── setup_apoc.sh                # APOC 安裝腳本
├── import_with_apoc.py              # Python 導入工具
├── setup_vector_index.py            # 向量索引工具
└── output/                          # GraphRAG 輸出目錄
    ├── entities.parquet
    ├── relationships.parquet
    ├── communities.parquet
    ├── community_reports.parquet
    └── text_units.parquet
```

## 常見問題

### Q1: APOC 未安裝或無法使用

**錯誤信息：** `There is no procedure with the name apoc.version`

**解決方法：**
1. 執行 `bash scripts/setup_apoc.sh`
2. 重啟 Neo4j
3. 檢查 `$NEO4J_HOME/plugins/` 目錄是否有 APOC JAR 檔案

### Q2: 無法讀取 Parquet 檔案

**錯誤信息：** `Failed to load the external resource`

**解決方法：**
1. 確認 `output/` 目錄中有 Parquet 檔案
2. 檢查 Neo4j 配置：`apoc.import.file.enabled=true`
3. 確認路徑正確（使用絕對路徑）

### Q3: 向量索引創建失敗

**錯誤信息：** `Vector index creation failed`

**解決方法：**
1. 確認 Neo4j 版本 >= 5.11（向量索引支持）
2. 檢查是否已有同名索引：`SHOW INDEXES`
3. 如需重建：`python setup_vector_index.py --rebuild`

### Q4: Embedding 生成速度慢

**解決方法：**
1. 調整批次大小：`python setup_vector_index.py --generate --batch-size 50`
2. 檢查 Azure OpenAI API 速率限制
3. 過程可中斷，重新運行會從未處理的實體繼續

## 高級用法

### 手動執行 Cypher 腳本

如果您更喜歡手動控制，可以直接在 Neo4j Browser 中執行 Cypher：

1. 打開 `scripts/apoc_import_graphrag.cypher`
2. 替換 `GRAPHRAG_OUTPUT_PATH` 為實際路徑
3. 逐個複製並執行語句

### 自定義導入

修改 `scripts/apoc_import_graphrag.cypher` 以：
- 添加自定義屬性
- 更改節點標籤
- 添加額外的索引
- 自定義關係類型

## 下一步

導入完成後，您可以：

1. **測試查詢** - 使用 Neo4j Browser 探索圖譜
2. **配置 Local Search** - 完善 `neo4j_local_search.py`
3. **測試實體對齊** - 運行 `agent_graph/nodes.py` 中的 `align_entities`
4. **運行稽核** - 使用 `audit_agent_interactive.py`

## 參考資料

- [Neo4j APOC 文檔](https://neo4j.com/docs/apoc/)
- [APOC Parquet 支持](https://neo4j.com/docs/apoc/current/import/parquet/)
- [Neo4j 向量索引](https://neo4j.com/docs/cypher-manual/current/indexes-for-vector-search/)

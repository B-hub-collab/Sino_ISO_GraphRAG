// ==========================================
// GraphRAG to Neo4j Import Script (APOC)
// ==========================================
// 使用 APOC 從 GraphRAG Parquet 檔案導入數據到 Neo4j
// 執行方式：在 Neo4j Browser 中執行，或使用 Python 腳本

// ==========================================
// 1. 清空數據庫（可選，謹慎使用）
// ==========================================
// MATCH (n) DETACH DELETE n;

// ==========================================
// 2. 創建約束和索引
// ==========================================
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT community_id IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT text_unit_id IF NOT EXISTS FOR (t:TextUnit) REQUIRE t.id IS UNIQUE;

// 創建常規索引以提升性能
CREATE INDEX entity_title IF NOT EXISTS FOR (e:Entity) ON (e.title);
CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type);
CREATE INDEX community_level IF NOT EXISTS FOR (c:Community) ON (c.level);

// ==========================================
// 3. 導入實體（Entities）
// ==========================================
CALL apoc.load.parquet('file:///GRAPHRAG_OUTPUT_PATH/entities.parquet') 
YIELD value
CREATE (e:Entity {
  id: value.id,
  title: value.title,
  type: value.type,
  description: value.description,
  frequency: toInteger(COALESCE(value.frequency, 0)),
  degree: toInteger(COALESCE(value.degree, 0)),
  human_readable_id: toInteger(COALESCE(value.human_readable_id, 0))
});

// ==========================================
// 4. 導入關係（Relationships）
// ==========================================
CALL apoc.load.parquet('file:///GRAPHRAG_OUTPUT_PATH/relationships.parquet') 
YIELD value
MATCH (source:Entity {title: value.source})
MATCH (target:Entity {title: value.target})
CREATE (source)-[r:RELATED_TO {
  id: value.id,
  description: COALESCE(value.description, ''),
  weight: toFloat(COALESCE(value.weight, 1.0)),
  human_readable_id: toInteger(COALESCE(value.human_readable_id, 0))
}]->(target);

// ==========================================
// 5. 導入社群（Communities）
// ==========================================
CALL apoc.load.parquet('file:///GRAPHRAG_OUTPUT_PATH/communities.parquet') 
YIELD value
CREATE (c:Community {
  id: value.id,
  community: toInteger(value.community),
  level: toInteger(value.level),
  title: COALESCE(value.title, ''),
  size: toInteger(COALESCE(value.size, 0)),
  human_readable_id: toInteger(COALESCE(value.human_readable_id, 0))
});

// ==========================================
// 6. 連接實體到社群
// ==========================================
CALL apoc.load.parquet('file:///GRAPHRAG_OUTPUT_PATH/communities.parquet') 
YIELD value
WITH value WHERE value.entity_ids IS NOT NULL
MATCH (c:Community {id: value.id})
UNWIND value.entity_ids AS entity_id
MATCH (e:Entity {id: entity_id})
MERGE (e)-[:BELONGS_TO]->(c);

// ==========================================
// 7. 導入社群摘要（Community Reports）
// ==========================================
CALL apoc.load.parquet('file:///GRAPHRAG_OUTPUT_PATH/community_reports.parquet') 
YIELD value
MATCH (c:Community {community: toInteger(value.community), level: toInteger(value.level)})
SET c.summary = COALESCE(value.summary, ''),
    c.full_content = COALESCE(value.full_content, ''),
    c.rank = toFloat(COALESCE(value.rank, 0.0)),
    c.rank_explanation = COALESCE(value.rank_explanation, ''),
    c.findings = value.findings;

// ==========================================
// 8. 導入文本單元（Text Units）
// ==========================================
CALL apoc.load.parquet('file:///GRAPHRAG_OUTPUT_PATH/text_units.parquet') 
YIELD value
CREATE (t:TextUnit {
  id: value.id,
  text: value.text,
  n_tokens: toInteger(COALESCE(value.n_tokens, 0)),
  document_ids: value.document_ids,
  entity_ids: value.entity_ids,
  relationship_ids: value.relationship_ids
});

// ==========================================
// 9. 連接文本單元到實體
// ==========================================
MATCH (t:TextUnit)
WHERE t.entity_ids IS NOT NULL
UNWIND t.entity_ids AS entity_id
MATCH (e:Entity {id: entity_id})
MERGE (t)-[:MENTIONS]->(e);

// ==========================================
// 10. 驗證導入結果
// ==========================================
MATCH (e:Entity) RETURN count(e) AS entity_count;
MATCH ()-[r:RELATED_TO]->() RETURN count(r) AS relationship_count;
MATCH (c:Community) RETURN count(c) AS community_count;
MATCH (t:TextUnit) RETURN count(t) AS text_unit_count;

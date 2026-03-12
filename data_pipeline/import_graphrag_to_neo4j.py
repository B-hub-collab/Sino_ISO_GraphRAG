"""
GraphRAG 至 Neo4j 完整導入工具

將 Microsoft GraphRAG CLI 產出的 parquet + LanceDB 完整匯入 Neo4j。
支援 Neo4j Aura 雲端服務（純 Python + Cypher，不依賴 APOC 本地檔案功能）。

匯入內容：
  1. Entities + Embeddings（從 LanceDB 讀取，不花 API 費用）
  2. Relationships
  3. Communities 結構 + Reports（summary, full_content, rank, findings）
  4. Community Embeddings（從 LanceDB 讀取）
  5. TextUnits + MENTIONS 關係 + Embeddings（從 LanceDB 讀取）
  6. Vector Indexes（entity_embeddings, community_embeddings, text_unit_embeddings）

資料來源：
  - parquet: entities, relationships, communities, community_reports, text_units
  - LanceDB: default-entity-description, default-community-full_content, default-text_unit-text
"""

import os
import json
import pandas as pd
import lancedb
from pathlib import Path
from neo4j import GraphDatabase
from dotenv import load_dotenv
from tqdm import tqdm
from typing import Dict

load_dotenv()


class GraphRAGImporter:
    """GraphRAG 至 Neo4j 完整導入器"""

    VECTOR_DIM = 3072  # text-embedding-3-large

    def __init__(self, output_dir: str = "output"):
        # Neo4j 連接
        self.neo4j_uri = os.getenv("NEO4J_URI")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD")

        if not all([self.neo4j_uri, self.neo4j_password]):
            raise ValueError("請設置 NEO4J_URI 和 NEO4J_PASSWORD 環境變數")

        self.driver = GraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password)
        )

        # GraphRAG 輸出目錄
        self.output_dir = Path(output_dir)
        if not self.output_dir.exists():
            raise ValueError(f"輸出目錄不存在: {self.output_dir}")

        # LanceDB 連接
        lancedb_path = self.output_dir / "lancedb"
        if not lancedb_path.exists():
            raise ValueError(f"LanceDB 目錄不存在: {lancedb_path}")
        self.lancedb = lancedb.connect(str(lancedb_path))

        print(f"Neo4j URI:  {self.neo4j_uri}")
        print(f"輸出目錄:   {self.output_dir}")
        print(f"LanceDB:    {lancedb_path}")
        print(f"LanceDB tables: {self.lancedb.table_names()}")

    def close(self):
        self.driver.close()

    def _load_lancedb_embeddings(self, table_name: str) -> Dict[str, list]:
        """從 LanceDB 讀取 embedding，回傳 {id: vector} dict"""
        table = self.lancedb.open_table(table_name)
        df = table.to_pandas()
        embedding_map = {}
        for _, row in df.iterrows():
            vec = row['vector']
            if hasattr(vec, 'tolist'):
                vec = vec.tolist()
            embedding_map[row['id']] = vec
        return embedding_map

    # ================================================================
    # Step 1: 連接驗證
    # ================================================================

    def verify_connection(self) -> bool:
        """驗證 Neo4j 連接"""
        print("\n[Step 1] 驗證 Neo4j 連接...")
        try:
            with self.driver.session() as session:
                session.run("RETURN 1 AS test").single()
                print("  ✓ 連接成功")

                try:
                    result = session.run("RETURN apoc.version() AS version")
                    version = result.single()["version"]
                    print(f"  ✓ APOC 版本: {version}")
                except Exception:
                    print("  ⚠ APOC 未安裝（不影響匯入）")

                return True
        except Exception as e:
            print(f"  ✗ 連接失敗: {e}")
            return False

    # ================================================================
    # Step 2: 清空數據庫
    # ================================================================

    def clear_database(self, auto_confirm: bool = False):
        """清空數據庫（分批刪除，適用 Aura）"""
        if not auto_confirm:
            print("\n⚠️  警告: 此操作將刪除 Neo4j 中的所有數據")
            response = input("確定要繼續嗎？ (yes/no): ")
            if response.lower() != 'yes':
                print("操作已取消")
                return False

        print("\n[Step 2] 清空數據庫...")
        with self.driver.session() as session:
            batch_size = 10000
            total_deleted = 0
            while True:
                result = session.run(f"""
                    MATCH (n)
                    WITH n LIMIT {batch_size}
                    DETACH DELETE n
                    RETURN count(n) AS deleted
                """)
                deleted = result.single()["deleted"]
                total_deleted += deleted
                if deleted > 0:
                    print(f"  已刪除 {total_deleted} 個節點...")
                if deleted < batch_size:
                    break

        print(f"  ✓ 數據庫已清空（共刪除 {total_deleted} 個節點）")
        return True

    # ================================================================
    # Step 3: 建立 Constraints + Indexes
    # ================================================================

    def create_constraints_and_indexes(self):
        """建立約束和索引"""
        print("\n[Step 3] 建立約束和索引...")

        with self.driver.session() as session:
            constraints = [
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT community_id IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT text_unit_id IF NOT EXISTS FOR (t:TextUnit) REQUIRE t.id IS UNIQUE",
            ]
            for c in constraints:
                try:
                    session.run(c)
                    name = c.split("CONSTRAINT")[1].split("IF")[0].strip()
                    print(f"  ✓ 約束: {name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"  - 約束已存在（跳過）")

            indexes = [
                "CREATE INDEX entity_title IF NOT EXISTS FOR (e:Entity) ON (e.title)",
                "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
                "CREATE INDEX community_level IF NOT EXISTS FOR (c:Community) ON (c.level)",
            ]
            for idx in indexes:
                try:
                    session.run(idx)
                    name = idx.split("INDEX")[1].split("IF")[0].strip()
                    print(f"  ✓ 索引: {name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"  - 索引已存在（跳過）")

    # ================================================================
    # Step 4: 匯入 Entities + Embeddings（from LanceDB）
    # ================================================================

    def import_entities(self, batch_size: int = 200):
        """匯入實體 + embedding（從 LanceDB 讀取）"""
        print("\n[Step 4] 匯入實體...")

        df = pd.read_parquet(self.output_dir / "entities.parquet")
        print(f"  Parquet: {len(df)} 個實體")

        # 從 LanceDB 讀取 embedding
        print("  從 LanceDB 讀取 entity embeddings...")
        embedding_map = self._load_lancedb_embeddings('default-entity-description')
        print(f"  LanceDB: {len(embedding_map)} 個 embedding（{self.VECTOR_DIM}-dim）")

        # 資料清理
        df['type'] = df['type'].fillna('UNKNOWN').str.strip().str.strip('"')
        df['description'] = df['description'].fillna('')
        df['frequency'] = df.get('frequency', pd.Series(dtype=int)).fillna(0).astype(int)
        df['degree'] = df.get('degree', pd.Series(dtype=int)).fillna(0).astype(int)
        df['human_readable_id'] = df.get('human_readable_id', pd.Series(dtype=int)).fillna(0).astype(int)

        # 批次匯入
        total_batches = (len(df) + batch_size - 1) // batch_size
        embedded_count = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), batch_size), total=total_batches, desc="  匯入實體"):
                batch_df = df.iloc[i:i + batch_size]
                entities = []

                for _, row in batch_df.iterrows():
                    entity = {
                        'id': row['id'],
                        'title': row['title'],
                        'type': row['type'],
                        'description': row['description'],
                        'frequency': int(row['frequency']),
                        'degree': int(row['degree']),
                        'human_readable_id': int(row['human_readable_id']),
                    }
                    embedding = embedding_map.get(row['id'])
                    if embedding is not None:
                        entity['embedding'] = embedding
                        embedded_count += 1
                    entities.append(entity)

                # 分兩組：有 embedding 的和沒有的
                with_emb = [e for e in entities if 'embedding' in e]
                without_emb = [e for e in entities if 'embedding' not in e]

                if with_emb:
                    session.run("""
                        UNWIND $entities AS entity
                        CREATE (e:Entity {
                            id: entity.id,
                            title: entity.title,
                            type: entity.type,
                            description: entity.description,
                            embedding: entity.embedding,
                            frequency: entity.frequency,
                            degree: entity.degree,
                            human_readable_id: entity.human_readable_id
                        })
                    """, entities=with_emb)

                if without_emb:
                    session.run("""
                        UNWIND $entities AS entity
                        CREATE (e:Entity {
                            id: entity.id,
                            title: entity.title,
                            type: entity.type,
                            description: entity.description,
                            frequency: entity.frequency,
                            degree: entity.degree,
                            human_readable_id: entity.human_readable_id
                        })
                    """, entities=without_emb)

        print(f"  ✓ 已匯入 {len(df)} 個實體（{embedded_count} 個含 embedding）")

    # ================================================================
    # Step 5: 建立 Vector Indexes
    # ================================================================

    def create_vector_indexes(self):
        """建立向量索引（entity + community + text_unit）"""
        print("\n[Step 5] 建立向量索引...")

        indexes = [
            ("entity_embeddings", "Entity", "embedding"),
            ("community_embeddings", "Community", "embedding"),
            ("text_unit_embeddings", "TextUnit", "embedding"),
        ]

        with self.driver.session() as session:
            for index_name, label, prop in indexes:
                result = session.run("""
                    SHOW INDEXES YIELD name, type
                    WHERE type = 'VECTOR' AND name = $name
                    RETURN count(*) AS count
                """, name=index_name)

                if result.single()["count"] > 0:
                    print(f"  - {index_name} 已存在（跳過）")
                    continue

                session.run(f"""
                    CREATE VECTOR INDEX {index_name} IF NOT EXISTS
                    FOR (n:{label})
                    ON n.{prop}
                    OPTIONS {{
                        indexConfig: {{
                            `vector.dimensions`: {self.VECTOR_DIM},
                            `vector.similarity_function`: 'cosine'
                        }}
                    }}
                """)
                print(f"  ✓ {index_name}（{label}.{prop}, {self.VECTOR_DIM}-dim, cosine）")

    # ================================================================
    # Step 6: 匯入 Relationships
    # ================================================================

    def import_relationships(self, batch_size: int = 500):
        """匯入關係"""
        print("\n[Step 6] 匯入關係...")

        df = pd.read_parquet(self.output_dir / "relationships.parquet")
        print(f"  共 {len(df)} 個關係")

        df['description'] = df['description'].fillna('')
        df['weight'] = df['weight'].fillna(1.0).astype(float)
        df['human_readable_id'] = df.get('human_readable_id', pd.Series(dtype=int)).fillna(0).astype(int)

        total_batches = (len(df) + batch_size - 1) // batch_size

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), batch_size), total=total_batches, desc="  匯入關係"):
                batch = df.iloc[i:i + batch_size].to_dict('records')
                session.run("""
                    UNWIND $relationships AS rel
                    MATCH (source:Entity {title: rel.source})
                    MATCH (target:Entity {title: rel.target})
                    CREATE (source)-[r:RELATED_TO {
                        id: rel.id,
                        description: rel.description,
                        weight: rel.weight,
                        human_readable_id: rel.human_readable_id
                    }]->(target)
                """, relationships=batch)

        print(f"  ✓ 已匯入 {len(df)} 個關係")

    # ================================================================
    # Step 7: 匯入 Communities + Reports + Embeddings
    # ================================================================

    def import_communities(self, batch_size: int = 100):
        """匯入社群結構 + 報告 + embedding"""
        print("\n[Step 7] 匯入社群...")

        # --- 7a: 匯入社群結構（from communities.parquet）---
        df = pd.read_parquet(self.output_dir / "communities.parquet")
        print(f"  communities.parquet: {len(df)} 個社群")

        df['title'] = df['title'].fillna('')
        df['size'] = df.get('size', pd.Series(dtype=int)).fillna(0).astype(int)
        df['level'] = df['level'].astype(int)
        df['community'] = df['community'].astype(int)
        df['human_readable_id'] = df.get('human_readable_id', pd.Series(dtype=int)).fillna(0).astype(int)

        total_batches = (len(df) + batch_size - 1) // batch_size

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), batch_size), total=total_batches, desc="  匯入社群節點"):
                batch = df.iloc[i:i + batch_size].to_dict('records')
                session.run("""
                    UNWIND $communities AS comm
                    CREATE (c:Community {
                        id: comm.id,
                        community: comm.community,
                        level: comm.level,
                        title: comm.title,
                        size: comm.size,
                        human_readable_id: comm.human_readable_id
                    })
                """, communities=batch)

        # Entity → BELONGS_TO → Community
        print("  連接 Entity → Community...")
        linked = 0
        for _, row in tqdm(df.iterrows(), total=len(df), desc="  BELONGS_TO"):
            entity_ids = row.get('entity_ids', [])
            if hasattr(entity_ids, 'tolist'):
                entity_ids = entity_ids.tolist()
            if not entity_ids or len(entity_ids) == 0:
                continue

            with self.driver.session() as session:
                result = session.run("""
                    MATCH (c:Community {id: $community_id})
                    UNWIND $entity_ids AS entity_id
                    MATCH (e:Entity {id: entity_id})
                    MERGE (e)-[:BELONGS_TO]->(c)
                    RETURN count(*) AS count
                """, community_id=row['id'], entity_ids=entity_ids)
                linked += result.single()['count']

        print(f"  ✓ {len(df)} 個社群，{linked} 個 BELONGS_TO 關係")

        # --- 7b: 補充 Community Reports（from community_reports.parquet）---
        reports_path = self.output_dir / "community_reports.parquet"
        if not reports_path.exists():
            print("  ⚠ community_reports.parquet 不存在，跳過報告匯入")
        else:
            df_reports = pd.read_parquet(reports_path)
            print(f"  community_reports.parquet: {len(df_reports)} 個報告")

            df_reports['summary'] = df_reports['summary'].fillna('') if 'summary' in df_reports.columns else ''
            df_reports['full_content'] = df_reports['full_content'].fillna('') if 'full_content' in df_reports.columns else ''
            df_reports['rank'] = df_reports['rank'].fillna(0.0).astype(float) if 'rank' in df_reports.columns else 0.0
            df_reports['rating_explanation'] = df_reports['rating_explanation'].fillna('') if 'rating_explanation' in df_reports.columns else ''

            updated = 0
            for _, row in tqdm(df_reports.iterrows(), total=len(df_reports), desc="  更新報告"):
                findings_value = row.get('findings', None)
                if findings_value is not None:
                    if hasattr(findings_value, 'tolist'):
                        findings_value = findings_value.tolist()
                    findings_json = json.dumps(findings_value, ensure_ascii=False)
                else:
                    findings_json = None

                with self.driver.session() as session:
                    result = session.run("""
                        MATCH (c:Community {community: $community, level: $level})
                        SET c.summary = $summary,
                            c.full_content = $full_content,
                            c.rank = $rank,
                            c.rating_explanation = $rating_explanation,
                            c.findings = $findings
                        RETURN count(c) AS count
                    """,
                        community=int(row['community']),
                        level=int(row['level']),
                        summary=row['summary'],
                        full_content=row['full_content'],
                        rank=float(row['rank']),
                        rating_explanation=row['rating_explanation'],
                        findings=findings_json
                    )
                    updated += result.single()['count']

            print(f"  ✓ 已更新 {updated} 個社群報告")

        # --- 7c: Community Embeddings（from LanceDB）---
        print("  從 LanceDB 讀取 community embeddings...")
        comm_embedding_map = self._load_lancedb_embeddings('default-community-full_content')
        print(f"  LanceDB: {len(comm_embedding_map)} 個 community embedding")

        # community_reports.parquet 的 id 對應 LanceDB 的 id
        # 需要把 LanceDB id → community_reports id → Community node（by community + level）
        if reports_path.exists():
            embedded_count = 0
            for _, row in tqdm(df_reports.iterrows(), total=len(df_reports), desc="  寫入 community embedding"):
                report_id = row['id']
                embedding = comm_embedding_map.get(report_id)
                if embedding is None:
                    continue

                with self.driver.session() as session:
                    session.run("""
                        MATCH (c:Community {community: $community, level: $level})
                        SET c.embedding = $embedding
                    """,
                        community=int(row['community']),
                        level=int(row['level']),
                        embedding=embedding
                    )
                    embedded_count += 1

            print(f"  ✓ 已寫入 {embedded_count} 個 community embedding")

    # ================================================================
    # Step 8: 匯入 TextUnits + MENTIONS + Embeddings
    # ================================================================

    def import_text_units(self, batch_size: int = 200):
        """匯入文本單元 + MENTIONS + embedding"""
        print("\n[Step 8] 匯入文本單元...")

        df = pd.read_parquet(self.output_dir / "text_units.parquet")
        print(f"  Parquet: {len(df)} 個文本單元")

        # 從 LanceDB 讀取 embedding
        print("  從 LanceDB 讀取 text_unit embeddings...")
        embedding_map = self._load_lancedb_embeddings('default-text_unit-text')
        print(f"  LanceDB: {len(embedding_map)} 個 embedding")

        df['n_tokens'] = df.get('n_tokens', pd.Series(dtype=int)).fillna(0).astype(int)

        # 批次匯入（含 embedding）
        total_batches = (len(df) + batch_size - 1) // batch_size
        embedded_count = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), batch_size), total=total_batches, desc="  匯入文本"):
                batch_df = df.iloc[i:i + batch_size]
                with_emb = []
                without_emb = []

                for _, row in batch_df.iterrows():
                    tu = {
                        'id': row['id'],
                        'text': row['text'],
                        'n_tokens': int(row['n_tokens']),
                    }
                    embedding = embedding_map.get(row['id'])
                    if embedding is not None:
                        tu['embedding'] = embedding
                        with_emb.append(tu)
                        embedded_count += 1
                    else:
                        without_emb.append(tu)

                if with_emb:
                    session.run("""
                        UNWIND $text_units AS tu
                        CREATE (t:TextUnit {
                            id: tu.id,
                            text: tu.text,
                            n_tokens: tu.n_tokens,
                            embedding: tu.embedding
                        })
                    """, text_units=with_emb)

                if without_emb:
                    session.run("""
                        UNWIND $text_units AS tu
                        CREATE (t:TextUnit {
                            id: tu.id,
                            text: tu.text,
                            n_tokens: tu.n_tokens
                        })
                    """, text_units=without_emb)

        print(f"  ✓ 已匯入 {len(df)} 個文本（{embedded_count} 個含 embedding）")

        # TextUnit → MENTIONS → Entity
        print("  連接 TextUnit → Entity...")
        linked = 0
        for _, row in tqdm(df.iterrows(), total=len(df), desc="  MENTIONS"):
            entity_ids = row.get('entity_ids', [])
            if hasattr(entity_ids, 'tolist'):
                entity_ids = entity_ids.tolist()
            if not entity_ids or len(entity_ids) == 0:
                continue

            with self.driver.session() as session:
                result = session.run("""
                    MATCH (t:TextUnit {id: $text_unit_id})
                    UNWIND $entity_ids AS entity_id
                    MATCH (e:Entity {id: entity_id})
                    MERGE (t)-[:MENTIONS]->(e)
                    RETURN count(*) AS count
                """, text_unit_id=row['id'], entity_ids=entity_ids)
                linked += result.single()['count']

        print(f"  ✓ {linked} 個 MENTIONS 關係")

    # ================================================================
    # Step 9: 驗證
    # ================================================================

    def verify_import(self) -> Dict[str, int]:
        """驗證匯入結果"""
        print("\n" + "=" * 60)
        print("[Step 9] 驗證匯入結果")
        print("=" * 60)

        counts = {}
        with self.driver.session() as session:
            # 節點
            counts['Entity'] = session.run("MATCH (e:Entity) RETURN count(e)").single()[0]
            counts['Community'] = session.run("MATCH (c:Community) RETURN count(c)").single()[0]
            counts['TextUnit'] = session.run("MATCH (t:TextUnit) RETURN count(t)").single()[0]

            # 關係
            counts['RELATED_TO'] = session.run("MATCH ()-[r:RELATED_TO]->() RETURN count(r)").single()[0]
            counts['BELONGS_TO'] = session.run("MATCH ()-[r:BELONGS_TO]->() RETURN count(r)").single()[0]
            counts['MENTIONS'] = session.run("MATCH ()-[r:MENTIONS]->() RETURN count(r)").single()[0]

            # Community 有 summary
            result = session.run("""
                MATCH (c:Community)
                WHERE c.summary IS NOT NULL AND c.summary <> ''
                RETURN count(c) AS count
            """)
            counts['Community (有報告)'] = result.single()['count']

            # Embedding 統計
            for label in ['Entity', 'Community', 'TextUnit']:
                result = session.run(f"""
                    MATCH (n:{label}) WHERE n.embedding IS NOT NULL
                    RETURN count(n) AS count
                """)
                counts[f'{label} (有 embedding)'] = result.single()['count']

            # Vector indexes
            result = session.run("""
                SHOW INDEXES YIELD name, type
                WHERE type = 'VECTOR'
                RETURN name
            """)
            vector_indexes = [r['name'] for r in result]

        print("\n節點統計:")
        print(f"  Entity:    {counts['Entity']}（有 embedding: {counts['Entity (有 embedding)']}）")
        print(f"  Community: {counts['Community']}（有報告: {counts['Community (有報告)']}，有 embedding: {counts['Community (有 embedding)']}）")
        print(f"  TextUnit:  {counts['TextUnit']}（有 embedding: {counts['TextUnit (有 embedding)']}）")

        print("\n關係統計:")
        print(f"  RELATED_TO: {counts['RELATED_TO']}")
        print(f"  BELONGS_TO: {counts['BELONGS_TO']}")
        print(f"  MENTIONS:   {counts['MENTIONS']}")

        print(f"\nVector Indexes: {vector_indexes if vector_indexes else '無'}")

        return counts

    # ================================================================
    # 完整匯入流程
    # ================================================================

    def run_import(self, clear_existing: bool = False, auto_confirm: bool = False):
        """執行完整匯入流程"""
        print("=" * 60)
        print("GraphRAG → Neo4j 完整匯入")
        print("=" * 60)

        try:
            if not self.verify_connection():             # Step 1
                return
            if clear_existing:                            # Step 2
                if not self.clear_database(auto_confirm):
                    return
            self.create_constraints_and_indexes()         # Step 3
            self.import_entities()                        # Step 4
            self.create_vector_indexes()                  # Step 5
            self.import_relationships()                   # Step 6
            self.import_communities()                     # Step 7 (結構 + 報告 + embedding)
            self.import_text_units()                      # Step 8 (文本 + MENTIONS + embedding)
            self.verify_import()                          # Step 9

            print("\n" + "=" * 60)
            print("✓ 匯入完成！")
            print("=" * 60)

        except Exception as e:
            print(f"\n✗ 錯誤: {e}")
            import traceback
            traceback.print_exc()
            raise

        finally:
            self.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="GraphRAG → Neo4j 完整匯入工具")
    parser.add_argument("--clear", action="store_true",
                        help="清空現有數據後重新匯入")
    parser.add_argument("--auto-confirm", action="store_true",
                        help="自動確認清空操作（不需手動輸入 yes）")
    parser.add_argument("--output-dir", default="output",
                        help="GraphRAG 輸出目錄（預設: output）")

    args = parser.parse_args()

    importer = GraphRAGImporter(output_dir=args.output_dir)
    importer.run_import(
        clear_existing=args.clear,
        auto_confirm=args.auto_confirm,
    )


if __name__ == "__main__":
    main()

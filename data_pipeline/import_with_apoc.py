"""
GraphRAG 至 Neo4j Aura 導入工具

專為 Neo4j Aura 雲端服務設計，使用純 Python + Cypher 導入
不依賴 APOC Parquet 功能（Aura 不支持本地文件訪問）
"""

import os
import pandas as pd
from pathlib import Path
from neo4j import GraphDatabase
from dotenv import load_dotenv
from tqdm import tqdm
from typing import Dict, List
import json

load_dotenv()


class AuraGraphRAGImporter:
    """Neo4j Aura GraphRAG 導入器"""
    
    def __init__(self, output_dir: str = "output"):
        """
        初始化導入器
        
        Args:
            output_dir: GraphRAG 輸出目錄
        """
        # Neo4j Aura 連接
        self.neo4j_uri = os.getenv("NEO4J_URI")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD")
        
        if not all([self.neo4j_uri, self.neo4j_password]):
            raise ValueError("請設置 NEO4J_URI 和 NEO4J_PASSWORD 環境變數")
        
        print(f"連接到 Neo4j Aura: {self.neo4j_uri}")
        
        self.driver = GraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password)
        )
        
        # GraphRAG 輸出目錄
        self.output_dir = Path(output_dir)
        if not self.output_dir.exists():
            raise ValueError(f"輸出目錄不存在: {self.output_dir}")
        
        print(f"GraphRAG 輸出目錄: {self.output_dir}")
    
    def close(self):
        """關閉連接"""
        self.driver.close()
    
    def verify_connection(self) -> bool:
        """驗證連接"""
        print("\n驗證 Neo4j Aura 連接...")
        try:
            with self.driver.session() as session:
                result = session.run("RETURN 1 AS test")
                result.single()
                print("  ✓ 連接成功")
                
                # 檢查 APOC
                try:
                    result = session.run("RETURN apoc.version() AS version")
                    version = result.single()["version"]
                    print(f"  ✓ APOC 版本: {version}")
                except Exception:
                    print("  ⚠ APOC 未安裝（部分功能可能受限）")
                
                return True
        except Exception as e:
            print(f"  ✗ 連接失敗: {e}")
            return False
    
    def clear_database(self, auto_confirm: bool = False):
        """清空數據庫"""
        if not auto_confirm:
            print("\n⚠️  警告: 此操作將刪除 Neo4j Aura 中的所有數據")
            response = input("確定要繼續嗎？ (yes/no): ")
            if response.lower() != 'yes':
                print("操作已取消")
                return False
        
        print("\n清空數據庫...")
        with self.driver.session() as session:
            # Aura 使用批次刪除（避免超時）
            batch_size = 10000
            while True:
                result = session.run(f"""
                    MATCH (n)
                    WITH n LIMIT {batch_size}
                    DETACH DELETE n
                    RETURN count(n) AS deleted
                """)
                deleted = result.single()["deleted"]
                print(f"  已刪除 {deleted} 個節點...")
                if deleted < batch_size:
                    break
        
        print("  ✓ 數據庫已清空")
        return True
    
    def create_constraints(self):
        """創建約束和索引"""
        print("\n創建約束和索引...")
        
        with self.driver.session() as session:
            constraints = [
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT community_id IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT text_unit_id IF NOT EXISTS FOR (t:TextUnit) REQUIRE t.id IS UNIQUE",
            ]
            
            indexes = [
                "CREATE INDEX entity_title IF NOT EXISTS FOR (e:Entity) ON (e.title)",
                "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
                "CREATE INDEX community_level IF NOT EXISTS FOR (c:Community) ON (c.level)",
            ]
            
            for constraint in constraints:
                try:
                    session.run(constraint)
                    name = constraint.split("CONSTRAINT")[1].split("IF")[0].strip()
                    print(f"  ✓ 約束: {name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"  - 約束已存在（跳過）")
                    else:
                        print(f"  ✗ 錯誤: {e}")
            
            for index in indexes:
                try:
                    session.run(index)
                    name = index.split("INDEX")[1].split("IF")[0].strip()
                    print(f"  ✓ 索引: {name}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"  - 索引已存在（跳過）")
    
    def import_entities(self, batch_size: int = 500):
        """導入實體"""
        print("\n導入實體...")
        
        # 讀取 Parquet
        parquet_path = self.output_dir / "entities.parquet"
        df = pd.read_parquet(parquet_path)
        
        print(f"  共 {len(df)} 個實體")
        
        # 準備數據
        df['type'] = df['type'].fillna('UNKNOWN').str.strip().str.strip('"')
        df['frequency'] = df.get('frequency', 0).fillna(0).astype(int)
        df['degree'] = df.get('degree', 0).fillna(0).astype(int)
        df['human_readable_id'] = df.get('human_readable_id', 0).fillna(0).astype(int)
        
        # 批次導入
        total_batches = (len(df) + batch_size - 1) // batch_size
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), batch_size), total=total_batches, desc="  導入進度"):
                batch = df.iloc[i:i+batch_size]
                
                entities = batch.to_dict('records')
                
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
                """, entities=entities)
        
        print(f"  ✓ 已導入 {len(df)} 個實體")
    
    def import_relationships(self, batch_size: int = 500):
        """導入關係"""
        print("\n導入關係...")
        
        parquet_path = self.output_dir / "relationships.parquet"
        df = pd.read_parquet(parquet_path)
        
        print(f"  共 {len(df)} 個關係")
        
        # 準備數據
        df['description'] = df.get('description', '').fillna('')
        df['weight'] = df.get('weight', 1.0).fillna(1.0).astype(float)
        df['human_readable_id'] = df.get('human_readable_id', 0).fillna(0).astype(int)
        
        # 批次導入
        total_batches = (len(df) + batch_size - 1) // batch_size
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), batch_size), total=total_batches, desc="  導入進度"):
                batch = df.iloc[i:i+batch_size]
                
                relationships = batch.to_dict('records')
                
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
                """, relationships=relationships)
        
        print(f"  ✓ 已導入 {len(df)} 個關係")
    
    def import_communities(self, batch_size: int = 100):
        """導入社群"""
        print("\n導入社群...")
        
        parquet_path = self.output_dir / "communities.parquet"
        df = pd.read_parquet(parquet_path)
        
        print(f"  共 {len(df)} 個社群")
        
        # 準備數據
        df['title'] = df.get('title', '').fillna('')
        df['size'] = df.get('size', 0).fillna(0).astype(int)
        df['level'] = df['level'].astype(int)
        df['community'] = df['community'].astype(int)
        df['human_readable_id'] = df.get('human_readable_id', 0).fillna(0).astype(int)
        
        # 批次導入社群節點
        total_batches = (len(df) + batch_size - 1) // batch_size
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), batch_size), total=total_batches, desc="  導入社群"):
                batch = df.iloc[i:i+batch_size]
                communities = batch.to_dict('records')
                
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
                """, communities=communities)
        
        # 連接實體到社群
        print("  連接實體到社群...")
        for _, row in tqdm(df.iterrows(), total=len(df), desc="  連接進度"):
            entity_ids = row.get('entity_ids', [])
            
            # 轉換 numpy array 為 list
            if hasattr(entity_ids, 'tolist'):
                entity_ids = entity_ids.tolist()
            
            # 檢查是否為非空列表
            if not entity_ids or len(entity_ids) == 0:
                continue
            
            with self.driver.session() as session:
                session.run("""
                    MATCH (c:Community {id: $community_id})
                    UNWIND $entity_ids AS entity_id
                    MATCH (e:Entity {id: entity_id})
                    MERGE (e)-[:BELONGS_TO]->(c)
                """, community_id=row['id'], entity_ids=entity_ids)
        
        print(f"  ✓ 已導入 {len(df)} 個社群")
    
    def import_community_reports(self):
        """導入社群摘要"""
        print("\n導入社群摘要...")
        
        parquet_path = self.output_dir / "community_reports.parquet"
        df = pd.read_parquet(parquet_path)
        
        print(f"  共 {len(df)} 個社群摘要")
        
        # 準備數據
        df['summary'] = df['summary'].fillna('') if 'summary' in df.columns else ''
        df['full_content'] = df['full_content'].fillna('') if 'full_content' in df.columns else ''
        df['rank'] = df['rank'].fillna(0.0).astype(float) if 'rank' in df.columns else 0.0
        df['rank_explanation'] = df['rank_explanation'].fillna('') if 'rank_explanation' in df.columns else ''
        df['findings'] = df['findings'] if 'findings' in df.columns else None
        
        for _, row in tqdm(df.iterrows(), total=len(df), desc="  更新社群"):
            # 處理 findings - 將 numpy array 轉換為 list
            findings_value = row['findings']
            if findings_value is not None:
                # 如果是 numpy array，轉換為 list
                if hasattr(findings_value, 'tolist'):
                    findings_value = findings_value.tolist()
                # 然後 JSON 序列化
                findings_json = json.dumps(findings_value)
            else:
                findings_json = None
            
            with self.driver.session() as session:
                session.run("""
                    MATCH (c:Community {community: $community, level: $level})
                    SET c.summary = $summary,
                        c.full_content = $full_content,
                        c.rank = $rank,
                        c.rank_explanation = $rank_explanation,
                        c.findings = $findings
                """, 
                    community=int(row['community']),
                    level=int(row['level']),
                    summary=row['summary'],
                    full_content=row['full_content'],
                    rank=row['rank'],
                    rank_explanation=row['rank_explanation'],
                    findings=findings_json
                )
        
        print(f"  ✓ 已更新 {len(df)} 個社群摘要")
    
    def import_text_units(self, batch_size: int = 500):
        """導入文本單元"""
        print("\n導入文本單元...")
        
        parquet_path = self.output_dir / "text_units.parquet"
        df = pd.read_parquet(parquet_path)
        
        print(f"  共 {len(df)} 個文本單元")
        
        # 準備數據
        df['n_tokens'] = df.get('n_tokens', 0).fillna(0).astype(int)
        
        # 批次導入
        total_batches = (len(df) + batch_size - 1) // batch_size
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), batch_size), total=total_batches, desc="  導入文本"):
                batch = df.iloc[i:i+batch_size]
                text_units = batch.to_dict('records')
                
                session.run("""
                    UNWIND $text_units AS tu
                    CREATE (t:TextUnit {
                        id: tu.id,
                        text: tu.text,
                        n_tokens: tu.n_tokens
                    })
                """, text_units=text_units)
        
        # 連接文本到實體
        print("  連接文本到實體...")
        for _, row in tqdm(df.iterrows(), total=len(df), desc="  連接進度"):
            entity_ids = row.get('entity_ids', [])
            
            # 轉換 numpy array 為 list
            if hasattr(entity_ids, 'tolist'):
                entity_ids = entity_ids.tolist()
            
            # 檢查是否為非空列表
            if not entity_ids or len(entity_ids) == 0:
                continue
            
            with self.driver.session() as session:
                session.run("""
                    MATCH (t:TextUnit {id: $text_unit_id})
                    UNWIND $entity_ids AS entity_id
                    MATCH (e:Entity {id: entity_id})
                    MERGE (t)-[:MENTIONS]->(e)
                """, text_unit_id=row['id'], entity_ids=entity_ids)
        
        print(f"  ✓ 已導入 {len(df)} 個文本單元")
    
    def verify_import(self) -> Dict[str, int]:
        """驗證導入結果"""
        print("\n" + "=" * 60)
        print("驗證導入結果")
        print("=" * 60)
        
        counts = {}
        
        with self.driver.session() as session:
            counts['Entity'] = session.run("MATCH (e:Entity) RETURN count(e)").single()[0]
            counts['RELATED_TO'] = session.run("MATCH ()-[r:RELATED_TO]->() RETURN count(r)").single()[0]
            counts['Community'] = session.run("MATCH (c:Community) RETURN count(c)").single()[0]
            counts['TextUnit'] = session.run("MATCH (t:TextUnit) RETURN count(t)").single()[0]
            counts['BELONGS_TO'] = session.run("MATCH ()-[r:BELONGS_TO]->() RETURN count(r)").single()[0]
            counts['MENTIONS'] = session.run("MATCH ()-[r:MENTIONS]->() RETURN count(r)").single()[0]
        
        print("\n導入統計:")
        for key, value in counts.items():
            print(f"  {key}: {value}")
        
        return counts
    
    def run_import(self, clear_existing: bool = False, auto_confirm: bool = False):
        """執行完整導入流程"""
        print("=" * 60)
        print("GraphRAG 至 Neo4j Aura 導入")
        print("=" * 60)
        
        try:
            # 驗證連接
            if not self.verify_connection():
                return
            
            # 清空數據庫
            if clear_existing:
                if not self.clear_database(auto_confirm):
                    return
            
            # 創建約束
            self.create_constraints()
            
            # 導入數據
            self.import_entities()
            self.import_relationships()
            self.import_communities()
            self.import_community_reports()
            self.import_text_units()
            
            # 驗證
            self.verify_import()
            
            print("\n" + "=" * 60)
            print("✓ 導入完成！")
            print("=" * 60)
        
        except Exception as e:
            print(f"\n✗ 錯誤: {e}")
            import traceback
            traceback.print_exc()
            raise
        
        finally:
            self.close()


def main():
    """主函數"""
    import argparse
    
    parser = argparse.ArgumentParser(description="GraphRAG 至 Neo4j Aura 導入工具")
    parser.add_argument("--clear", action="store_true", help="清空現有數據")
    parser.add_argument("--auto-confirm", action="store_true", help="自動確認")
    parser.add_argument("--output-dir", default="output", help="GraphRAG 輸出目錄")
    
    args = parser.parse_args()
    
    importer = AuraGraphRAGImporter(output_dir=args.output_dir)
    importer.run_import(clear_existing=args.clear, auto_confirm=args.auto_confirm)


if __name__ == "__main__":
    main()

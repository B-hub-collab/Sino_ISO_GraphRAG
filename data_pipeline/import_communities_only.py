"""
只導入 Community 和 Community Reports 到 Neo4j
用於補充現有數據庫
"""

import os
import pandas as pd
from pathlib import Path
from neo4j import GraphDatabase
from dotenv import load_dotenv
from tqdm import tqdm
import json

load_dotenv()


def import_communities_and_reports():
    """導入社群和社群報告到 Neo4j"""
    
    # 連接 Neo4j
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    
    print(f"連接到 Neo4j: {uri}")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    
    output_dir = Path("output")
    
    try:
        # 1. 創建約束
        print("\n創建約束...")
        with driver.session() as session:
            try:
                session.run("CREATE CONSTRAINT community_id IF NOT EXISTS FOR (c:__Community__) REQUIRE c.id IS UNIQUE")
                print("  ✓ Community 約束已創建")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print("  - Community 約束已存在")
                else:
                    raise
        
        # 2. 導入社群節點
        print("\n導入社群節點...")
        communities_df = pd.read_parquet(output_dir / "communities.parquet")
        print(f"  共 {len(communities_df)} 個社群")
        
        # 準備數據
        communities_df['title'] = communities_df.get('title', '').fillna('')
        communities_df['size'] = communities_df.get('size', 0).fillna(0).astype(int)
        communities_df['level'] = communities_df['level'].astype(int)
        communities_df['community'] = communities_df['community'].astype(int)
        
        batch_size = 100
        total_batches = (len(communities_df) + batch_size - 1) // batch_size
        
        with driver.session() as session:
            for i in tqdm(range(0, len(communities_df), batch_size), total=total_batches, desc="  導入社群"):
                batch = communities_df.iloc[i:i+batch_size]
                communities = batch.to_dict('records')
                
                session.run("""
                    UNWIND $communities AS comm
                    MERGE (c:__Community__ {id: comm.id})
                    SET c.community = comm.community,
                        c.level = comm.level,
                        c.title = comm.title,
                        c.size = comm.size
                """, communities=communities)
        
        print(f"  ✓ 已導入 {len(communities_df)} 個社群節點")
        
        # 3. 連接實體到社群
        print("\n連接實體到社群...")
        connected = 0
        for _, row in tqdm(communities_df.iterrows(), total=len(communities_df), desc="  連接進度"):
            entity_ids = row.get('entity_ids', [])
            
            # 轉換 numpy array 為 list
            if hasattr(entity_ids, 'tolist'):
                entity_ids = entity_ids.tolist()
            
            # 檢查是否為非空列表
            if not entity_ids or len(entity_ids) == 0:
                continue
            
            with driver.session() as session:
                result = session.run("""
                    MATCH (c:__Community__ {id: $community_id})
                    UNWIND $entity_ids AS entity_id
                    MATCH (e:__Entity__ {id: entity_id})
                    MERGE (e)-[:IN_COMMUNITY]->(c)
                    RETURN count(*) as count
                """, community_id=row['id'], entity_ids=entity_ids)
                connected += result.single()['count']
        
        print(f"  ✓ 已連接 {connected} 個實體到社群")
        
        # 4. 導入社群報告
        print("\n導入社群報告...")
        reports_df = pd.read_parquet(output_dir / "community_reports.parquet")
        print(f"  共 {len(reports_df)} 個社群報告")
        
        # 準備數據
        reports_df['summary'] = reports_df['summary'].fillna('') if 'summary' in reports_df.columns else ''
        reports_df['full_content'] = reports_df['full_content'].fillna('') if 'full_content' in reports_df.columns else ''
        reports_df['rank'] = reports_df['rank'].fillna(0.0).astype(float) if 'rank' in reports_df.columns else 0.0
        reports_df['title'] = reports_df['title'].fillna('') if 'title' in reports_df.columns else ''
        
        for _, row in tqdm(reports_df.iterrows(), total=len(reports_df), desc="  更新社群報告"):
            # 處理 findings
            findings_value = row.get('findings', None)
            if findings_value is not None:
                if hasattr(findings_value, 'tolist'):
                    findings_value = findings_value.tolist()
                findings_json = json.dumps(findings_value, ensure_ascii=False)
            else:
                findings_json = None
            
            with driver.session() as session:
                session.run("""
                    MATCH (c:__Community__ {community: $community, level: $level})
                    SET c.title = $title,
                        c.summary = $summary,
                        c.full_content = $full_content,
                        c.rank = $rank,
                        c.findings = $findings
                """, 
                    community=int(row['community']),
                    level=int(row['level']),
                    title=row.get('title', ''),
                    summary=row['summary'],
                    full_content=row['full_content'],
                    rank=row['rank'],
                    findings=findings_json
                )
        
        print(f"  ✓ 已更新 {len(reports_df)} 個社群報告")
        
        # 5. 驗證
        print("\n驗證導入結果...")
        with driver.session() as session:
            result = session.run("MATCH (c:__Community__) RETURN count(c) as count")
            count = result.single()['count']
            print(f"  __Community__ 節點: {count}")
            
            result = session.run("MATCH ()-[r:IN_COMMUNITY]->() RETURN count(r) as count")
            count = result.single()['count']
            print(f"  IN_COMMUNITY 關係: {count}")
            
            # 檢查有摘要的社群
            result = session.run("""
                MATCH (c:__Community__)
                WHERE c.summary IS NOT NULL AND c.summary <> ''
                RETURN count(c) as count
            """)
            count = result.single()['count']
            print(f"  有摘要的社群: {count}")
        
        print("\n✓ 導入完成！")
        
    except Exception as e:
        print(f"\n✗ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    finally:
        driver.close()


if __name__ == "__main__":
    import_communities_and_reports()

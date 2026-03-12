"""
建立 Neo4j 向量索引以支持實體對齊

此腳本用於：
1. 創建向量索引（用於實體對齊的向量搜索）
2. 為所有實體生成 embeddings
3. 驗證索引狀態
4. 測試向量搜索功能
"""

import os
from neo4j import GraphDatabase
from langchain_openai import AzureOpenAIEmbeddings
from dotenv import load_dotenv
from tqdm import tqdm
from typing import List, Dict
import time

load_dotenv()


class VectorIndexBuilder:
    """向量索引建立器"""
    
    def __init__(self):
        """初始化"""
        # Neo4j 連接
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))
        )
        
        # Azure OpenAI Embeddings
        self.embeddings = AzureOpenAIEmbeddings(
            azure_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"),
            openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY")
        )
        
        print("向量索引建立器已初始化")
        print(f"  Neo4j URI: {os.getenv('NEO4J_URI')}")
        print(f"  Embedding 模型: {os.getenv('AZURE_OPENAI_EMBEDDING_DEPLOYMENT')}")
    
    def close(self):
        """關閉連接"""
        self.driver.close()
    
    def create_vector_index(self):
        """創建向量索引"""
        print("\n創建向量索引...")
        
        with self.driver.session() as session:
            # 檢查索引是否已存在
            result = session.run("""
                SHOW INDEXES
                YIELD name, type
                WHERE type = 'VECTOR' AND name = 'entity_embeddings'
                RETURN count(*) AS count
            """)
            exists = result.single()["count"] > 0
            
            if exists:
                print("  向量索引 'entity_embeddings' 已存在")
                return
            
            # 創建向量索引
            # text-embedding-3-large 產生 3072 維向量
            try:
                session.run("""
                    CREATE VECTOR INDEX entity_embeddings IF NOT EXISTS
                    FOR (e:Entity)
                    ON e.embedding
                    OPTIONS {
                        indexConfig: {
                            `vector.dimensions`: 3072,
                            `vector.similarity_function`: 'cosine'
                        }
                    }
                """)
                print("  向量索引 'entity_embeddings' 已創建")
                print("  向量維度: 3072")
                print("  相似度函數: cosine")
            except Exception as e:
                print(f"  錯誤: {e}")
                raise
    
    def count_entities_without_embeddings(self) -> int:
        """計算沒有 embeddings 的實體數量"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Entity)
                WHERE e.embedding IS NULL
                RETURN count(e) AS count
            """)
            return result.single()["count"]
    
    def get_entities_without_embeddings(self, limit: int = None) -> List[Dict]:
        """獲取沒有 embeddings 的實體"""
        with self.driver.session() as session:
            query = """
                MATCH (e:Entity)
                WHERE e.embedding IS NULL
                RETURN e.id AS id, e.title AS title, e.description AS description
            """
            if limit:
                query += f" LIMIT {limit}"
            
            result = session.run(query)
            return [dict(record) for record in result]
    
    def generate_embeddings(self, batch_size: int = 100, rate_limit_delay: float = 0.5):
        """
        為所有實體生成 embeddings
        
        Args:
            batch_size: 每批處理的實體數量
            rate_limit_delay: 批次之間的延遲（秒），避免 API 速率限制
        """
        print("\n生成實體 embeddings...")
        
        # 計算需要生成的數量
        total_count = self.count_entities_without_embeddings()
        
        if total_count == 0:
            print("  所有實體已有 embeddings")
            return
        
        print(f"  需要生成 embedding 的實體數: {total_count}")
        print(f"  批次大小: {batch_size}")
        print(f"  批次間延遲: {rate_limit_delay}秒")
        
        # 分批處理
        processed = 0
        
        with tqdm(total=total_count, desc="  生成 embeddings") as pbar:
            while processed < total_count:
                # 獲取一批實體
                entities = self.get_entities_without_embeddings(limit=batch_size)
                
                if not entities:
                    break
                
                # 準備文本（組合 title 和 description）
                texts = [
                    f"{entity['title']}: {entity['description']}" 
                    for entity in entities
                ]
                
                try:
                    # 生成 embeddings
                    embeddings_list = self.embeddings.embed_documents(texts)
                    
                    # 更新 Neo4j
                    with self.driver.session() as session:
                        for entity, embedding in zip(entities, embeddings_list):
                            session.run("""
                                MATCH (e:Entity {id: $id})
                                SET e.embedding = $embedding
                            """, id=entity['id'], embedding=embedding)
                    
                    processed += len(entities)
                    pbar.update(len(entities))
                    
                    # 速率限制
                    if processed < total_count:
                        time.sleep(rate_limit_delay)
                
                except Exception as e:
                    print(f"\n  錯誤: {e}")
                    print(f"  已處理: {processed}/{total_count}")
                    raise
        
        print(f"\n  完成! 共生成 {processed} 個 embeddings")
    
    def verify_index(self):
        """驗證索引狀態"""
        print("\n驗證向量索引...")
        
        with self.driver.session() as session:
            # 檢查索引列表
            result = session.run("""
                SHOW INDEXES
                YIELD name, type, state, populationPercent
                WHERE type = 'VECTOR'
                RETURN name, state, populationPercent
            """)
            
            indices = list(result)
            
            if not indices:
                print("  未找到向量索引")
                return False
            
            for record in indices:
                print(f"  索引: {record['name']}")
                print(f"    狀態: {record['state']}")
                print(f"    填充百分比: {record['populationPercent']:.2f}%")
            
            # 檢查有 embedding 的實體數量
            result = session.run("""
                MATCH (e:Entity)
                WHERE e.embedding IS NOT NULL
                RETURN count(e) AS count
            """)
            with_embeddings = result.single()["count"]
            
            result = session.run("""
                MATCH (e:Entity)
                RETURN count(e) AS count
            """)
            total = result.single()["count"]
            
            print(f"\n  實體統計:")
            print(f"    總數: {total}")
            print(f"    有 embedding: {with_embeddings}")
            print(f"    無 embedding: {total - with_embeddings}")
            
            if with_embeddings < total:
                print(f"\n  警告: 有 {total - with_embeddings} 個實體缺少 embedding")
                print(f"  運行: python setup_vector_index.py --generate")
            
            return True
    
    def test_search(self, query: str, top_k: int = 5):
        """
        測試向量搜索
        
        Args:
            query: 查詢文本
            top_k: 返回前 k 個結果
        """
        print(f"\n測試向量搜索...")
        print(f"  查詢: {query}")
        print(f"  返回數量: {top_k}")
        
        # 生成查詢 embedding
        query_embedding = self.embeddings.embed_query(query)
        print(f"  查詢 embedding 維度: {len(query_embedding)}")
        
        # 執行向量搜索
        with self.driver.session() as session:
            try:
                result = session.run("""
                    CALL db.index.vector.queryNodes('entity_embeddings', $k, $embedding)
                    YIELD node, score
                    RETURN node.title AS title, 
                           node.type AS type,
                           node.description AS description, 
                           score
                    LIMIT $k
                """, k=top_k, embedding=query_embedding)
                
                records = list(result)
                
                if not records:
                    print("\n  未找到匹配結果")
                    return
                
                print(f"\n  搜索結果 ({len(records)} 個):")
                for i, record in enumerate(records, 1):
                    print(f"\n  {i}. {record['title']} ({record['type']})")
                    print(f"     相似度: {record['score']:.4f}")
                    print(f"     描述: {record['description'][:100]}...")
            
            except Exception as e:
                print(f"\n  錯誤: {e}")
                print("\n  可能的原因:")
                print("  1. 向量索引未創建 - 運行: python setup_vector_index.py --create")
                print("  2. 實體缺少 embeddings - 運行: python setup_vector_index.py --generate")
                raise
    
    def rebuild_index(self):
        """重建向量索引（刪除並重新創建）"""
        print("\n重建向量索引...")
        
        with self.driver.session() as session:
            # 刪除現有索引
            try:
                session.run("DROP INDEX entity_embeddings IF EXISTS")
                print("  舊索引已刪除")
            except Exception as e:
                print(f"  刪除舊索引時發生錯誤: {e}")
            
            # 創建新索引
            self.create_vector_index()


def main():
    """主函數"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="建立和管理 Neo4j 向量索引"
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="創建向量索引"
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="為實體生成 embeddings"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="驗證索引狀態"
    )
    parser.add_argument(
        "--test-search",
        type=str,
        help="測試向量搜索（提供查詢文本）"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="重建向量索引"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="生成 embeddings 的批次大小（默認: 100）"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="執行所有步驟：創建索引、生成 embeddings、驗證"
    )
    
    args = parser.parse_args()
    
    # 創建建立器
    builder = VectorIndexBuilder()
    
    try:
        if args.all:
            # 執行所有步驟
            builder.create_vector_index()
            builder.generate_embeddings(batch_size=args.batch_size)
            builder.verify_index()
        else:
            # 執行指定步驟
            if args.rebuild:
                builder.rebuild_index()
            
            if args.create:
                builder.create_vector_index()
            
            if args.generate:
                builder.generate_embeddings(batch_size=args.batch_size)
            
            if args.verify:
                builder.verify_index()
            
            if args.test_search:
                builder.test_search(args.test_search)
        
        # 如果沒有指定任何選項，顯示幫助
        if not any([args.create, args.generate, args.verify, args.test_search, 
                    args.rebuild, args.all]):
            parser.print_help()
    
    finally:
        builder.close()


if __name__ == "__main__":
    main()

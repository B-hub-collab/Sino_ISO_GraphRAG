"""
測試 Neo4j Global Search 功能

測試社群檢索和 Map-Reduce 查詢流程
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_neo4j import Neo4jGraph

# 添加專案根目錄到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from global_search.neo4j_global_search import Neo4jGlobalSearch

load_dotenv()


def test_retrieve_communities():
    """測試社群檢索"""
    print("\n" + "=" * 60)
    print("測試 1: 社群檢索")
    print("=" * 60)
    
    # 連接 Neo4j
    graph = Neo4jGraph(
        url=os.getenv("NEO4J_URI"),
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD"),
    )
    
    # 初始化 LLM (不需要，只測試檢索)
    llm = AzureChatOpenAI(
        azure_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    )
    
    # 創建 Global Search
    global_search = Neo4jGlobalSearch(graph=graph, llm=llm, level=0, max_communities=5)
    
    # 檢索社群
    communities = global_search._retrieve_communities()
    
    print(f"\n✓ 找到 {len(communities)} 個社群")
    
    # 顯示範例
    print("\n範例社群:")
    for i, comm in enumerate(communities[:3], 1):
        print(f"\n{i}. Community {comm['community']}")
        print(f"   Title: {comm['title']}")
        print(f"   Rank: {comm.get('rank', 'N/A')}")
        print(f"   Size: {comm.get('size', 'N/A')}")
        print(f"   Summary (前100字): {comm['summary'][:100]}...")
    
    return communities


def test_map_stage():
    """測試 Map 階段"""
    print("\n" + "=" * 60)
    print("測試 2: Map 階段 - 單一社群分析")
    print("=" * 60)
    
    # 連接
    graph = Neo4jGraph(
        url=os.getenv("NEO4J_URI"),
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD"),
    )
    
    llm = AzureChatOpenAI(
        azure_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    )
    
    global_search = Neo4jGlobalSearch(graph=graph, llm=llm, level=0, max_communities=3)
    
    # 獲取一個社群
    communities = global_search._retrieve_communities()
    if not communities:
        print("⚠️ 沒有社群可測試")
        return
    
    test_community = communities[0]
    test_query = "這份契約的主要風險有哪些？"
    
    print(f"\n測試社群: {test_community['title']}")
    print(f"測試查詢: {test_query}")
    print("\n執行 Map...")
    
    # 執行 Map
    response = global_search._map_community_to_response(test_community, test_query)
    
    print(f"\n✓ Map 完成")
    print(f"   評分: {response.rating}")
    print(f"   要點數: {len(response.points)}")
    print("\n提取的要點:")
    for i, point in enumerate(response.points, 1):
        print(f"   {i}. {point}")
    
    return response


def test_full_global_search():
    """測試完整 Global Search"""
    print("\n" + "=" * 60)
    print("測試 3: 完整 Global Search")
    print("=" * 60)
    
    # 連接
    graph = Neo4jGraph(
        url=os.getenv("NEO4J_URI"),
        username=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD"),
    )
    
    llm = AzureChatOpenAI(
        azure_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    )
    
    # 創建 Global Search（限制社群數量以加快測試）
    global_search = Neo4jGlobalSearch(
        graph=graph,
        llm=llm,
        level=0,
        max_communities=3,
        importance_threshold=3.0
    )
    
    # 測試查詢
    test_queries = [
        "這份契約的主要風險有哪些？",
        "契約中對於違約的規定是什麼？",
        "甲乙雙方的主要權利義務有哪些？",
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'─' * 60}")
        print(f"查詢 {i}: {query}")
        print('─' * 60)
        
        answer = global_search.search(query, verbose=True)
        
        print(f"\n【最終答案】\n{answer}\n")
    
    return True


def main():
    """主測試流程"""
    print("\n" + "=" * 60)
    print("🧪 Neo4j Global Search 測試套件")
    print("=" * 60)
    
    try:
        # 測試 1: 社群檢索
        communities = test_retrieve_communities()
        
        if not communities:
            print("\n⚠️ 沒有社群數據，請先運行 import_communities_only.py")
            return
        
        # 測試 2: Map 階段
        test_map_stage()
        
        # 測試 3: 完整 Global Search
        test_full_global_search()
        
        print("\n" + "=" * 60)
        print("✓ 所有測試完成！")
        print("=" * 60)
    
    except Exception as e:
        print(f"\n✗ 測試失敗: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

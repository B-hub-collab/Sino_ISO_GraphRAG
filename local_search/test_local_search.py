"""
Neo4j Local Search 測試腳本

測試 Neo4j Local Search 的各個功能組件：
1. 實體提取
2. 實體匹配
3. 局部子圖檢索
4. 完整的 Local Search 流程
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_neo4j import Neo4jGraph

# 添加 agent_graph 到路徑
sys.path.insert(0, str(Path(__file__).parent / "agent_graph"))
from neo4j_local_search import Neo4jLocalSearch

load_dotenv()

# ==========================================
# 配置
# ==========================================

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")


def initialize_components():
    """初始化所有組件"""
    print("\n" + "="*80)
    print("🔧 初始化組件...")
    print("="*80)
    
    # 1. Neo4j 連接
    print("\n[1/3] 連接 Neo4j...")
    print(f"   URI: {NEO4J_URI}")
    graph = Neo4jGraph(
        url=NEO4J_URI,
        username=NEO4J_USER,
        password=NEO4J_PASSWORD
    )
    print("   ✅ Neo4j 連接成功")
    
    # 2. LLM
    print("\n[2/3] 初始化 LLM...")
    llm = AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
        azure_deployment=AZURE_OPENAI_CHAT_DEPLOYMENT
        # 注意：o4-mini 不支持 temperature 參數，使用默認值
    )
    print(f"   ✅ LLM 初始化成功 (部署: {AZURE_OPENAI_CHAT_DEPLOYMENT})")
    
    # 3. Embeddings
    print("\n[3/3] 初始化 Embeddings...")
    embeddings = AzureOpenAIEmbeddings(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
        azure_deployment=AZURE_OPENAI_EMBEDDING_DEPLOYMENT
    )
    print(f"   ✅ Embeddings 初始化成功 (部署: {AZURE_OPENAI_EMBEDDING_DEPLOYMENT})")
    
    # 4. Local Search
    print("\n[4/4] 初始化 Local Search...")
    local_search = Neo4jLocalSearch(graph, llm, embeddings)
    print("   ✅ Local Search 初始化成功")
    
    print("\n" + "="*80)
    print("✅ 所有組件初始化完成")
    print("="*80)
    
    return graph, llm, embeddings, local_search


def test_entity_extraction(local_search: Neo4jLocalSearch):
    """測試 1: 實體提取"""
    print("\n\n" + "="*80)
    print("📋 測試 1: 實體提取功能")
    print("="*80)
    
    test_questions = [
        "甲方與哪些實體關聯最緊密？",
        "責任險的受益人是誰？",
        "違約金的計算方式是什麼？",
        "臺中市政府在契約中扮演什麼角色？",
    ]
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n[測試 1.{i}] 問題: {question}")
        entities = local_search.extract_entities_from_question(question)
        print(f"   提取結果: {entities}")
        print(f"   數量: {len(entities)}")


def test_entity_matching(local_search: Neo4jLocalSearch):
    """測試 2: 實體匹配"""
    print("\n\n" + "="*80)
    print("📋 測試 2: 實體匹配功能")
    print("="*80)
    
    test_entities = [
        ["甲方"],
        ["責任險", "保險"],
        ["違約金"],
        ["臺中市政府"],
        ["不存在的實體XYZ123"],  # 測試找不到的情況
    ]
    
    for i, entities in enumerate(test_entities, 1):
        print(f"\n[測試 2.{i}] 查找實體: {entities}")
        matched = local_search.find_matching_entities_in_neo4j(entities, top_k=3)
        print(f"   匹配數量: {len(matched)}")
        if matched:
            for m in matched[:3]:
                print(f"   - {m.get('title')} (type: {m.get('type')}, degree: {m.get('degree')})")


def test_subgraph_retrieval(local_search: Neo4jLocalSearch, graph: Neo4jGraph):
    """測試 3: 局部子圖檢索"""
    print("\n\n" + "="*80)
    print("📋 測試 3: 局部子圖檢索功能")
    print("="*80)
    
    # 先找一些高度數的實體
    print("\n[3.1] 查找高度數實體作為測試...")
    query = """
    MATCH (e:Entity)
    WHERE e.degree IS NOT NULL
    RETURN e.id AS id, e.title AS title, e.degree AS degree
    ORDER BY e.degree DESC
    LIMIT 5
    """
    high_degree_entities = graph.query(query)
    
    if not high_degree_entities:
        print("   ⚠️ 沒有找到高度數實體")
        return
    
    print(f"   找到 {len(high_degree_entities)} 個高度數實體:")
    for e in high_degree_entities:
        print(f"   - {e['title']} (degree: {e['degree']})")
    
    # 測試不同跳數的子圖檢索
    test_entity_id = high_degree_entities[0]['id']
    test_entity_title = high_degree_entities[0]['title']
    
    for hop in [1, 2]:
        print(f"\n[3.{hop+1}] 檢索 '{test_entity_title}' 的 {hop} 跳子圖...")
        entities, relationships = local_search.get_local_subgraph([test_entity_id], max_hops=hop)
        print(f"   實體數: {len(entities)}")
        print(f"   關係數: {len(relationships)}")
        
        if entities:
            print(f"   樣本實體（前5個）:")
            for e in entities[:5]:
                print(f"   - {e.get('title')} (type: {e.get('type')})")


def test_full_local_search(local_search: Neo4jLocalSearch):
    """測試 4: 完整的 Local Search 流程"""
    print("\n\n" + "="*80)
    print("📋 測試 4: 完整 Local Search 流程")
    print("="*80)
    
    test_questions = [
        {
            "question": "甲方與哪些實體關聯最緊密？",
            "description": "測試關係探索",
            "max_hops": 2
        },
        {
            "question": "責任險的受益人是誰？有什麼相關規定？",
            "description": "測試具體條款查詢",
            "max_hops": 2
        },
        {
            "question": "違約金的計算方式和相關條款有哪些？",
            "description": "測試複雜查詢",
            "max_hops": 1
        },
    ]
    
    for i, test_case in enumerate(test_questions, 1):
        print(f"\n{'='*80}")
        print(f"[測試 4.{i}] {test_case['description']}")
        print(f"{'='*80}")
        print(f"問題: {test_case['question']}")
        print(f"最大跳數: {test_case['max_hops']}\n")
        
        try:
            answer = local_search.search(
                question=test_case['question'],
                max_hops=test_case['max_hops']
            )
            
            print(f"\n{'='*80}")
            print(f"📝 回答:")
            print(f"{'='*80}")
            print(answer)
            print(f"\n{'='*80}\n")
            
        except Exception as e:
            print(f"\n❌ 測試失敗: {str(e)}")
            import traceback
            traceback.print_exc()


def test_via_main_api():
    """測試 5: 通過 main.py API 調用"""
    print("\n\n" + "="*80)
    print("📋 測試 5: 通過 main.py API 調用")
    print("="*80)
    
    try:
        from agent_graph.main import run_agent
        
        test_questions = [
            "甲方與哪些實體關聯最緊密？",
            "責任險的受益人是誰？",
        ]
        
        for i, question in enumerate(test_questions, 1):
            print(f"\n[測試 5.{i}] 問題: {question}\n")
            
            result = run_agent(
                question=question,
                verbose=True,
                force_engine="local_search"
            )
            
            print(f"\n結果:")
            print(f"  - 查詢類型: {result.get('query_type')}")
            print(f"  - 置信度: {result.get('confidence', 0)*100:.1f}%")
            print(f"  - 回答長度: {len(result.get('answer', ''))} 字元")
            print(f"\n{'='*80}\n")
            
    except Exception as e:
        print(f"\n❌ 測試失敗: {str(e)}")
        import traceback
        traceback.print_exc()


def run_all_tests():
    """運行所有測試"""
    print("\n" + "="*80)
    print("🚀 Neo4j Local Search 完整測試")
    print("="*80)
    
    # 初始化
    graph, llm, embeddings, local_search = initialize_components()
    
    # 執行測試
    tests = [
        ("實體提取", lambda: test_entity_extraction(local_search)),
        ("實體匹配", lambda: test_entity_matching(local_search)),
        ("子圖檢索", lambda: test_subgraph_retrieval(local_search, graph)),
        ("完整 Local Search", lambda: test_full_local_search(local_search)),
        ("main.py API", test_via_main_api),
    ]
    
    for test_name, test_func in tests:
        try:
            test_func()
        except KeyboardInterrupt:
            print("\n\n⚠️ 用戶中斷測試")
            break
        except Exception as e:
            print(f"\n\n❌ 測試 '{test_name}' 失敗: {str(e)}")
            import traceback
            traceback.print_exc()
    
    print("\n\n" + "="*80)
    print("✅ 測試完成")
    print("="*80)
    print("\n")


def interactive_test():
    """互動式測試"""
    print("\n" + "="*80)
    print("🧪 Neo4j Local Search 互動式測試")
    print("="*80)
    
    # 初始化
    graph, llm, embeddings, local_search = initialize_components()
    
    print("\n提示:")
    print("  - 輸入問題進行測試")
    print("  - 輸入 'exit' 或 'quit' 退出")
    print("  - 輸入 'all' 運行完整測試套件\n")
    
    while True:
        try:
            question = input("\n❓ 您的問題 (或 'exit'/'all'): ").strip()
            
            if not question:
                continue
            
            if question.lower() in ['exit', 'quit', 'q']:
                print("\n👋 再見！\n")
                break
            
            if question.lower() == 'all':
                run_all_tests()
                continue
            
            # 執行 Local Search
            print(f"\n{'='*80}")
            answer = local_search.search(question, max_hops=2)
            print(f"\n{'='*80}")
            print(f"📝 回答:")
            print(f"{'='*80}")
            print(answer)
            print(f"\n{'='*80}\n")
            
        except KeyboardInterrupt:
            print("\n\n👋 再見！\n")
            break
        except Exception as e:
            print(f"\n❌ 錯誤: {str(e)}\n")
            import traceback
            traceback.print_exc()


def main():
    """主函數"""
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            run_all_tests()
        elif sys.argv[1] == '--interactive' or sys.argv[1] == '-i':
            interactive_test()
        else:
            # 單次查詢
            question = " ".join(sys.argv[1:])
            graph, llm, embeddings, local_search = initialize_components()
            answer = local_search.search(question, max_hops=2)
            print(f"\n{'='*80}")
            print(f"📝 回答:")
            print(f"{'='*80}")
            print(answer)
            print(f"\n{'='*80}\n")
    else:
        # 默認互動模式
        interactive_test()


if __name__ == "__main__":
    main()

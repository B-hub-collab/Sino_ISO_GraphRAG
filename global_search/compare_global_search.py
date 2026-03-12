"""
Global Search 比較測試: Neo4j vs GraphRAG CLI

比較兩種 Global Search 實現的性能與答案品質
"""

import os
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_neo4j import Neo4jGraph

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from global_search.neo4j_global_search import Neo4jGlobalSearch

load_dotenv()

# 配置
GRAPHRAG_ROOT = Path(os.getenv("GRAPHRAG_ROOT", "/home/boya/Sino_ISO/contracts"))
GRAPHRAG_CONFIG = GRAPHRAG_ROOT / "settings.yaml"
GRAPHRAG_DATA = GRAPHRAG_ROOT / "output"
OUTPUT_DIR = Path(__file__).parent / "comparison_results"
OUTPUT_DIR.mkdir(exist_ok=True)


def query_neo4j_global_search(query: str, max_communities: int = 10) -> dict:
    """使用 Neo4j Global Search 查詢"""
    print(f"\n🔵 Neo4j Global Search")
    
    start_time = time.time()
    
    try:
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
        
        # 創建 Global Search
        global_search = Neo4jGlobalSearch(
            graph=graph,
            llm=llm,
            level=0,
            max_communities=max_communities,
            importance_threshold=3.0
        )
        
        # 執行搜索
        answer = global_search.search(query, verbose=False)
        
        elapsed_time = time.time() - start_time
        
        return {
            "success": True,
            "method": "Neo4j Global Search",
            "answer": answer,
            "time_seconds": elapsed_time,
            "error": None
        }
    
    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"   ❌ 失敗: {e}")
        return {
            "success": False,
            "method": "Neo4j Global Search",
            "answer": f"錯誤: {str(e)}",
            "time_seconds": elapsed_time,
            "error": str(e)
        }


def query_graphrag_cli_global_search(query: str) -> dict:
    """使用 GraphRAG CLI Global Search 查詢"""
    print(f"\n🟢 GraphRAG CLI Global Search")
    
    start_time = time.time()
    
    try:
        # 構建命令 - 使用 conda 環境
        cmd = [
            "conda", "run", "-n", "graphrag310",
            "graphrag",
            "query",
            "--method", "global",
            "--query", query,
            "--config", str(GRAPHRAG_CONFIG),
            "--data", str(GRAPHRAG_DATA),
        ]
        
        # 執行命令
        result = subprocess.run(
            cmd,
            cwd=str(GRAPHRAG_ROOT),
            capture_output=True,
            text=True,
            timeout=300
        )
        
        elapsed_time = time.time() - start_time
        
        if result.returncode == 0:
            return {
                "success": True,
                "method": "GraphRAG CLI Global Search",
                "answer": result.stdout.strip(),
                "time_seconds": elapsed_time,
                "error": None
            }
        else:
            error_msg = result.stderr or result.stdout
            return {
                "success": False,
                "method": "GraphRAG CLI Global Search",
                "answer": f"查詢失敗: {error_msg}",
                "time_seconds": elapsed_time,
                "error": error_msg
            }
    
    except subprocess.TimeoutExpired:
        elapsed_time = time.time() - start_time
        return {
            "success": False,
            "method": "GraphRAG CLI Global Search",
            "answer": "查詢超時（300秒）",
            "time_seconds": elapsed_time,
            "error": "Timeout"
        }
    
    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"   ❌ 失敗: {e}")
        return {
            "success": False,
            "method": "GraphRAG CLI Global Search",
            "answer": f"異常: {str(e)}",
            "time_seconds": elapsed_time,
            "error": str(e)
        }


def compare_results(neo4j_result: dict, graphrag_result: dict) -> dict:
    """比較兩種方法的結果"""
    comparison = {
        "performance": {
            "neo4j_time": neo4j_result["time_seconds"],
            "graphrag_time": graphrag_result["time_seconds"],
            "faster_method": None,
            "time_difference": 0,
            "speedup_ratio": 0
        },
        "success": {
            "neo4j": neo4j_result["success"],
            "graphrag": graphrag_result["success"],
            "both_success": neo4j_result["success"] and graphrag_result["success"]
        },
        "answer_length": {
            "neo4j": len(neo4j_result.get("answer", "")),
            "graphrag": len(graphrag_result.get("answer", ""))
        }
    }
    
    # 性能比較
    if neo4j_result["time_seconds"] < graphrag_result["time_seconds"]:
        comparison["performance"]["faster_method"] = "Neo4j"
        comparison["performance"]["time_difference"] = graphrag_result["time_seconds"] - neo4j_result["time_seconds"]
        comparison["performance"]["speedup_ratio"] = graphrag_result["time_seconds"] / neo4j_result["time_seconds"] if neo4j_result["time_seconds"] > 0 else 0
    else:
        comparison["performance"]["faster_method"] = "GraphRAG"
        comparison["performance"]["time_difference"] = neo4j_result["time_seconds"] - graphrag_result["time_seconds"]
        comparison["performance"]["speedup_ratio"] = neo4j_result["time_seconds"] / graphrag_result["time_seconds"] if graphrag_result["time_seconds"] > 0 else 0
    
    return comparison


def display_comparison(query: str, comparison: dict, neo4j_result: dict, graphrag_result: dict):
    """顯示比較結果"""
    print(f"\n{'='*80}")
    print(f"📊 Global Search 比較結果")
    print(f"{'='*80}")
    print(f"\n查詢: {query}")
    
    # 性能比較
    perf = comparison["performance"]
    print(f"\n⏱️  執行時間:")
    print(f"   Neo4j:    {perf['neo4j_time']:.2f} 秒")
    print(f"   GraphRAG: {perf['graphrag_time']:.2f} 秒")
    print(f"   更快:     {perf['faster_method']}")
    print(f"   差異:     {perf['time_difference']:.2f} 秒")
    if perf['speedup_ratio'] > 1:
        print(f"   加速比:   {perf['speedup_ratio']:.2f}x")
    
    # 成功狀態
    succ = comparison["success"]
    print(f"\n✅ 執行狀態:")
    print(f"   Neo4j:    {'成功' if succ['neo4j'] else '失敗'}")
    print(f"   GraphRAG: {'成功' if succ['graphrag'] else '失敗'}")
    
    # 回答長度
    ans_len = comparison["answer_length"]
    print(f"\n📝 回答長度:")
    print(f"   Neo4j:    {ans_len['neo4j']} 字元")
    print(f"   GraphRAG: {ans_len['graphrag']} 字元")
    
    # 回答預覽
    print(f"\n📄 回答比較:")
    print(f"\n【Neo4j Global Search】")
    neo4j_preview = neo4j_result['answer'][:300] + "..." if len(neo4j_result['answer']) > 300 else neo4j_result['answer']
    print(f"{neo4j_preview}")
    
    print(f"\n【GraphRAG CLI Global Search】")
    graphrag_preview = graphrag_result['answer'][:300] + "..." if len(graphrag_result['answer']) > 300 else graphrag_result['answer']
    print(f"{graphrag_preview}")
    
    print(f"\n{'='*80}")


def save_comparison_result(query: str, neo4j_result: dict, graphrag_result: dict, comparison: dict):
    """儲存比較結果"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = OUTPUT_DIR / f"comparison_{timestamp}.json"
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "neo4j_result": neo4j_result,
        "graphrag_result": graphrag_result,
        "comparison": comparison
    }
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 結果已儲存: {filename}")
    return filename


def main():
    """主測試流程"""
    print("\n" + "=" * 80)
    print("🔬 Global Search 比較測試: Neo4j vs GraphRAG CLI")
    print("=" * 80)
    
    # 測試查詢
    test_queries = [
        "這份契約的主要風險有哪些？",
        "契約中對於違約的規定是什麼？請詳細說明。",
        "甲乙雙方的主要權利義務有哪些？",
    ]
    
    results = []
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'▬'*80}")
        print(f"測試 {i}/{len(test_queries)}: {query}")
        print('▬'*80)
        
        # 執行 Neo4j Global Search
        neo4j_result = query_neo4j_global_search(query, max_communities=3)
        
        # 執行 GraphRAG CLI Global Search
        graphrag_result = query_graphrag_cli_global_search(query)
        
        # 比較結果
        comparison = compare_results(neo4j_result, graphrag_result)
        
        # 顯示比較
        display_comparison(query, comparison, neo4j_result, graphrag_result)
        
        # 儲存結果
        filename = save_comparison_result(query, neo4j_result, graphrag_result, comparison)
        
        results.append({
            "query": query,
            "comparison": comparison,
            "filename": str(filename)
        })
    
    # 總結
    print(f"\n{'='*80}")
    print("📈 總體統計")
    print(f"{'='*80}")
    
    total_neo4j_time = sum(r["comparison"]["performance"]["neo4j_time"] for r in results)
    total_graphrag_time = sum(r["comparison"]["performance"]["graphrag_time"] for r in results)
    avg_neo4j_time = total_neo4j_time / len(results)
    avg_graphrag_time = total_graphrag_time / len(results)
    
    print(f"\n平均執行時間:")
    print(f"   Neo4j:    {avg_neo4j_time:.2f} 秒")
    print(f"   GraphRAG: {avg_graphrag_time:.2f}秒")
    
    neo4j_success = sum(1 for r in results if r["comparison"]["success"]["neo4j"])
    graphrag_success = sum(1 for r in results if r["comparison"]["success"]["graphrag"])
    
    print(f"\n成功率:")
    print(f"   Neo4j:    {neo4j_success}/{len(results)} ({neo4j_success/len(results)*100:.1f}%)")
    print(f"   GraphRAG: {graphrag_success}/{len(results)} ({graphrag_success/len(results)*100:.1f}%)")
    
    print(f"\n{'='*80}")
    print("✓ 比較測試完成！")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()

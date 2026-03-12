"""
LangGraph 狀態圖定義

定義 Agent 的執行流程和狀態轉換邏輯
"""

from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import (
    route_query,
    generate_cypher,
    execute_cypher,
    graphrag_search,
    local_search_neo4j,
    hybrid_query,
    generate_answer,
    check_query_type,
    check_cypher_execution,
    handle_max_retries,
)


def create_agent_graph() -> StateGraph:
    """
    創建 Agent 狀態圖

    流程圖:
    ┌─────────────┐
    │   START     │
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │ route_query │  # 路由決策
    └──────┬──────┘
           │
           ▼
      ┌────┴────┐
      │ query   │  # 根據類型分流
      │  type   │
      └────┬────┘
           │
     ┌─────┼─────┬─────────┐
     │     │     │         │
     ▼     ▼     ▼         ▼
   cypher graphrag hybrid  (其他)
     │     │     │
     ▼     ▼     ▼
  ┌─────┬─────┬─────┐
  │ Cypher   GraphRAG  Hybrid
  │ Flow     Flow      Flow
  └──┬───┬───┬────┘
     │   │   │
     └───┴───┴─────> generate_answer
                           │
                           ▼
                         END

    Returns:
        編譯後的 StateGraph
    """

    # 創建狀態圖
    workflow = StateGraph(AgentState)

    # ============================================
    # 添加節點
    # ============================================

    # 1. 路由節點
    workflow.add_node("route_query", route_query)

    # 2. Cypher 路徑節點
    workflow.add_node("generate_cypher", generate_cypher)
    workflow.add_node("execute_cypher", execute_cypher)

    # 4. Local Search 路徑節點 (新增)
    workflow.add_node("local_search_neo4j", local_search_neo4j)

    # 5. GraphRAG 路徑節點
    workflow.add_node("graphrag_search", graphrag_search)

    # 6. 混合模式節點
    workflow.add_node("hybrid_query", hybrid_query)

    # 7. 最終回答生成節點
    workflow.add_node("generate_answer", generate_answer)

    # 8. 錯誤處理節點
    workflow.add_node("handle_max_retries", handle_max_retries)

    # ============================================
    # 設置入口點（使用條件入口以支持強制引擎）
    # ============================================

    def get_entry_point(state: AgentState) -> str:
        """
        決定入口點
        - 如果已設置 query_type（強制引擎），跳過路由
        - 否則進行正常路由
        """
        if state.get("query_type"):
            # 已指定引擎，直接跳轉
            query_type = state["query_type"]
            if query_type == "cypher":
                return "generate_cypher"
            elif query_type == "local_search":
                return "local_search_neo4j"
            elif query_type == "graphrag":
                return "graphrag_search"
            elif query_type == "hybrid":
                return "hybrid_query"
        return "route_query"

    workflow.set_conditional_entry_point(
        get_entry_point,
        {
            "route_query": "route_query",
            "generate_cypher": "generate_cypher",
            "local_search_neo4j": "local_search_neo4j",
            "graphrag_search": "graphrag_search",
            "hybrid_query": "hybrid_query",
        }
    )

    # ============================================
    # 添加條件邊 (根據查詢類型路由)
    # ============================================

    workflow.add_conditional_edges(
        "route_query",
        check_query_type,
        {
            "cypher": "generate_cypher",           # Cypher 路徑
            "local_search": "local_search_neo4j",  # Local Search 路徑（Vector Search 已內建）
            "graphrag": "graphrag_search",         # GraphRAG 路徑
            "hybrid": "hybrid_query",              # 混合模式
        }
    )

    # ============================================
    # Cypher 路徑的自我修正循環
    # ============================================

    # generate_cypher -> execute_cypher
    workflow.add_edge("generate_cypher", "execute_cypher")

    # execute_cypher -> (檢查結果)
    workflow.add_conditional_edges(
        "execute_cypher",
        check_cypher_execution,
        {
            "retry": "generate_cypher",           # 重試
            "success": "generate_answer",         # 成功，生成回答
            "max_retries": "handle_max_retries",  # 達到最大重試，降級
        }
    )

    # ============================================
    # Local Search 路徑（Vector Search 已內建，跳過 align_entities）
    # ============================================

    # local_search_neo4j -> generate_answer
    workflow.add_edge("local_search_neo4j", "generate_answer")

    # ============================================
    # GraphRAG 路徑
    # ============================================

    # graphrag_search -> generate_answer
    workflow.add_edge("graphrag_search", "generate_answer")

    # ============================================
    # 混合模式路徑
    # ============================================

    # hybrid_query -> generate_answer
    workflow.add_edge("hybrid_query", "generate_answer")

    # ============================================
    # 錯誤處理路徑
    # ============================================

    # handle_max_retries -> END (已在函數內生成答案)
    workflow.add_edge("handle_max_retries", END)

    # ============================================
    # 最終節點到結束
    # ============================================

    workflow.add_edge("generate_answer", END)

    # ============================================
    # 編譯圖
    # ============================================

    return workflow.compile()


# ============================================
# 輔助函數：可視化圖結構
# ============================================

def visualize_graph(graph: StateGraph, output_path: str = "agent_graph.png"):
    """
    將圖結構可視化為圖片

    需要安裝: pip install pygraphviz

    Args:
        graph: 編譯後的 StateGraph
        output_path: 輸出圖片路徑
    """
    try:
        from IPython.display import Image, display

        # 生成 Mermaid 圖
        display(Image(graph.get_graph().draw_mermaid_png()))

    except ImportError:
        print("⚠️  可視化需要安裝 pygraphviz 或在 Jupyter 環境中運行")
        print("   安裝: pip install pygraphviz")


# ============================================
# 輔助函數：打印執行路徑
# ============================================

def print_execution_summary(state: AgentState):
    """
    打印執行摘要

    Args:
        state: 最終的 AgentState
    """
    print("\n" + "=" * 60)
    print("📊 執行摘要")
    print("=" * 60)

    print(f"\n❓ 問題: {state.get('question', 'N/A')}")
    print(f"\n🧭 查詢類型: {state.get('query_type', 'N/A')}")
    print(f"   路由原因: {state.get('routing_reason', 'N/A')}")

    print(f"\n🛤️  執行路徑: {' -> '.join(state.get('execution_path', []))}")

    if state.get('cypher_query'):
        print(f"\n📝 Cypher 查詢:")
        print(f"   {state['cypher_query']}")
        print(f"   重試次數: {state.get('cypher_retry_count', 0)}")

    if state.get('cypher_results'):
        print(f"\n📊 Cypher 結果: {len(state['cypher_results'])} 條記錄")

    if state.get('local_search_result'):
        result = state['local_search_result']
        preview = result[:200] + "..." if len(result) > 200 else result
        print(f"\n🔍 Local Search 結果: {preview}")

    if state.get('graphrag_result'):
        result = state['graphrag_result']
        preview = result[:200] + "..." if len(result) > 200 else result
        print(f"\n🌐 GraphRAG 結果: {preview}")

    if state.get('error_log'):
        print(f"\n⚠️  錯誤日誌:")
        for i, error in enumerate(state['error_log'], 1):
            print(f"   {i}. {error}")

    print(f"\n💬 最終回答:")
    print(f"   {state.get('final_answer', 'N/A')}")

    print(f"\n📈 置信度: {state.get('confidence', 0.0):.2%}")

    print("\n" + "=" * 60 + "\n")

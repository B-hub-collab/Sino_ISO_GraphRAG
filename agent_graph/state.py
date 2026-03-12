"""
Agent State 定義

使用 TypedDict 定義 LangGraph 的狀態結構
"""

from typing import TypedDict, List, Optional, Literal


class AgentState(TypedDict, total=False):
    """
    Agent 狀態定義

    LangGraph 會在各個節點之間傳遞這個狀態
    """

    # 用戶輸入
    question: str                          
    chat_history: List[dict]                

    # 路由決策
    query_type: Literal["cypher", "local_search", "graphrag", "hybrid"] 
    routing_reason: str                  

    # 實體識別與對齊
    identified_entities: List[dict]   
    aligned_entities: List[dict]         

    # Cypher 路徑相關
    cypher_query: str                      
    cypher_errors: Optional[str]        
    cypher_retry_count: int            
    cypher_results: List[dict]           

    # Local Search 路徑相關 (新增)
    local_search_result: str            
    local_search_data: dict                

    # GraphRAG 路徑相關
    graphrag_result: str                    # GraphRAG Global Search 結果
    graphrag_sources: List[str]             # 來源文件

    # 混合模式
    hybrid_cypher_results: Optional[List[dict]]   # 混合模式的 Cypher 結果
    hybrid_graphrag_result: Optional[str]         # 混合模式的 GraphRAG 結果

    # 最終輸出
    final_answer: str                       # 最終回答
    sources: List[dict]                     # 來源追蹤
    confidence: float                       # 置信度 (0-1)

    # 元數據
    execution_path: List[str]               # 執行路徑 (用於調試)
    error_log: List[str]                    # 錯誤日誌

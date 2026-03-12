"""
Agent 節點函數

定義 LangGraph 中的各個處理節點
"""

import os
import json
import subprocess
import time
from typing import Any
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_neo4j import Neo4jGraph
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser

from .state import AgentState
from .prompts import (
    ROUTER_PROMPT,
    CYPHER_GENERATION_PROMPT,
    CYPHER_CORRECTION_PROMPT,
    QA_GENERATION_PROMPT,
    ENTITY_ALIGNMENT_PROMPT,
    HYBRID_FUSION_PROMPT,
)
from .neo4j_local_search import Neo4jLocalSearch


# ============================================
# 全局配置
# ============================================

# 初始化 Azure OpenAI LLM
# 注意：o4-mini 推理模型只支持 temperature=1 (默認值)
llm = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    # o4-mini 推理模型不支持自定義 temperature，使用默認值 1
    # 速率限制處理
    max_retries=3,  # 最多重試 3 次
    request_timeout=60,  # 請求超時 60 秒
)

# 初始化 Neo4j 連接
graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    username=os.getenv("NEO4J_USER", "neo4j"),
    password=os.getenv("NEO4J_PASSWORD"),
)

# 初始化 Azure OpenAI Embeddings (用於實體對齊)
embeddings = AzureOpenAIEmbeddings(
    azure_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)

# 初始化 Neo4j Local Search
neo4j_local_search = Neo4jLocalSearch(
    graph=graph,
    llm=llm,
    embeddings=embeddings
)

# GraphRAG 配置
GRAPHRAG_ROOT = os.getenv("GRAPHRAG_ROOT", "/home/boya/Sino_ISO/contracts")
GRAPHRAG_CONFIG = os.path.join(GRAPHRAG_ROOT, "settings.yaml")
GRAPHRAG_DATA = os.path.join(GRAPHRAG_ROOT, "output")

# 最大重試次數
MAX_CYPHER_RETRIES = 3


# ============================================
# 節點 1: 路由 Agent
# ============================================

def route_query(state: AgentState) -> AgentState:
    """
    根據問題類型路由到不同的引擎

    Returns:
        更新後的 state，包含 query_type 和 routing_reason
    """
    question = state["question"]
    state.setdefault("execution_path", []).append("route_query")

    try:
        # 使用 LLM 判斷路由
        chain = ROUTER_PROMPT | llm | JsonOutputParser()
        routing_decision = chain.invoke({"question": question})

        state["query_type"] = routing_decision["query_type"]
        state["routing_reason"] = routing_decision.get("reasoning", "")

        print(f"\n🧭 路由決策: {state['query_type']}")
        print(f"   原因: {state['routing_reason']}\n")

    except Exception as e:
        # 降級到默認路由
        state["query_type"] = "cypher"
        state["routing_reason"] = f"路由失敗，默認使用 Cypher: {str(e)}"
        state.setdefault("error_log", []).append(f"路由錯誤: {str(e)}")

    return state


# ============================================
# 節點 2: 實體對齊 (可選優化)
# ============================================

def align_entities(state: AgentState) -> AgentState:
    """
    使用向量搜索對齊實體名稱

    這個節點是可選的優化，用於提高查詢準確度

    工作流程：
    1. 使用 LLM 從問題中提取可能的實體名稱
    2. 對提取的實體進行 embedding
    3. 在 Neo4j 向量索引中搜索最相似的標準實體
    4. 返回對齊結果供後續 Cypher 生成使用
    """
    state.setdefault("execution_path", []).append("align_entities")

    question = state["question"]
    aligned_entities = []

    try:
        # 步驟 1: 使用 LLM 提取實體
        extraction_prompt = f"""從以下問題中提取所有實體名稱（組織、人物、地點等）。

問題: {question}

請以 JSON 格式返回提取的實體列表。格式：
{{"entities": ["實體1", "實體2", ...]}}

如果沒有明確的實體，返回空列表。只返回 JSON，不要其他文字。"""

        chain = llm | StrOutputParser()
        response = chain.invoke(extraction_prompt)

        # 解析 JSON
        import json
        response_clean = response.strip()
        if response_clean.startswith("```json"):
            response_clean = response_clean.replace("```json", "").replace("```", "").strip()
        elif response_clean.startswith("```"):
            response_clean = response_clean.replace("```", "").strip()

        extracted = json.loads(response_clean)
        entity_mentions = extracted.get("entities", [])

        if not entity_mentions:
            print("  ℹ️  未提取到實體，跳過對齊\n")
            state["aligned_entities"] = []
            return state

        print(f"  📍 提取到 {len(entity_mentions)} 個實體: {entity_mentions}\n")

        # 步驟 2 & 3: 對每個提取的實體進行向量搜索
        for mention in entity_mentions:
            # 生成 embedding
            mention_embedding = embeddings.embed_query(mention)

            # 在 Neo4j 中進行向量相似度搜索
            # 注意：需要先創建向量索引（見下方說明）
            vector_search_query = """
            CALL db.index.vector.queryNodes('entity_embeddings', $k, $embedding)
            YIELD node, score
            WHERE score > $threshold
            RETURN node.title AS title,
                   node.type AS type,
                   node.description AS description,
                   score
            ORDER BY score DESC
            LIMIT 1
            """

            try:
                results = graph.query(vector_search_query, {
                    "embedding": mention_embedding,
                    "k": 3,  # 搜索前 3 個最相似的
                    "threshold": 0.7  # 相似度閾值
                })

                if results:
                    best_match = results[0]
                    aligned_entities.append({
                        "mention": mention,
                        "aligned_title": best_match["title"],
                        "aligned_type": best_match["type"],
                        "similarity": best_match["score"]
                    })
                    print(f"  ✓ '{mention}' → '{best_match['title']}' (相似度: {best_match['score']:.3f})")
                else:
                    print(f"  ⚠️  '{mention}' 未找到匹配實體")

            except Exception as e:
                # 向量索引可能不存在
                if "no such index" in str(e).lower() or "not found" in str(e).lower():
                    print(f"  ⚠️  向量索引不存在，跳過實體對齊")
                    print(f"     提示：執行 setup_vector_index.py 來創建索引\n")
                    state["aligned_entities"] = []
                    return state
                else:
                    print(f"  ⚠️  向量搜索錯誤: {str(e)}")

        state["aligned_entities"] = aligned_entities

        if aligned_entities:
            print(f"\n  📊 對齊摘要: {len(aligned_entities)}/{len(entity_mentions)} 個實體成功對齊\n")

    except Exception as e:
        print(f"  ⚠️  實體對齊失敗: {str(e)}\n")
        state["aligned_entities"] = []
        state.setdefault("error_log", []).append(f"實體對齊錯誤: {str(e)}")

    return state


# ============================================
# 節點 3: 生成 Cypher 查詢
# ============================================

def generate_cypher(state: AgentState) -> AgentState:
    """
    生成 Cypher 查詢

    如果是重試，會包含之前的錯誤信息
    """
    state.setdefault("execution_path", []).append("generate_cypher")
    state.setdefault("cypher_retry_count", 0)

    question = state["question"]
    retry_count = state["cypher_retry_count"]

    # 獲取 Schema
    schema = graph.schema

    # 構建實體對齊上下文
    aligned_entities_context = ""
    aligned_entities = state.get("aligned_entities", [])
    if aligned_entities:
        aligned_entities_context = "\n## 🎯 實體對齊信息\n\n以下實體已對齊到圖譜中的標準名稱：\n"
        for entity in aligned_entities:
            aligned_entities_context += f"- '{entity['mention']}' → '{entity['aligned_title']}' (類型: {entity['aligned_type']}, 相似度: {entity['similarity']:.2f})\n"
        aligned_entities_context += "\n請在生成 Cypher 查詢時使用對齊後的標準名稱。\n"

    # 構建錯誤上下文 (用於自我修正)
    error_context = ""
    if state.get("cypher_errors"):
        error_context = f"""
## ⚠️ 上一次查詢失敗

錯誤信息: {state['cypher_errors']}
失敗的查詢: {state.get('cypher_query', 'N/A')}

請根據錯誤信息修正查詢。
"""

    try:
        # 生成 Cypher
        if error_context:
            # 自我修正模式
            prompt_text = CYPHER_CORRECTION_PROMPT.format(
                error_message=state["cypher_errors"],
                failed_query=state.get("cypher_query", ""),
            )
            chain = llm | StrOutputParser()
            raw_output = chain.invoke(prompt_text)
        else:
            # 首次生成
            chain = CYPHER_GENERATION_PROMPT | llm | StrOutputParser()
            raw_output = chain.invoke({
                "schema": schema,
                "question": question,
                "aligned_entities_context": aligned_entities_context,
                "error_context": error_context,
            })

        # 調試：打印原始輸出
        print(f"\n🔍 LLM 原始輸出 (長度: {len(raw_output)}):")
        print(f"--- 開始 ---")
        print(repr(raw_output[:500]))  # 顯示前 500 字符，包含轉義字符
        print(f"--- 結束 ---\n")

        # 清理生成的查詢 (移除 markdown 標記)
        cypher_query = raw_output.strip()

        # 處理空輸出
        if not cypher_query:
            raise ValueError("LLM 返回空輸出")

        # 處理 o4-mini 可能返回的 JSON 格式
        if cypher_query.startswith('{') and 'query' in cypher_query.lower():
            try:
                json_response = json.loads(cypher_query)
                # 嘗試不同的 JSON 鍵
                for key in ['query', 'cypher', 'cypher_query', 'answer', 'result']:
                    if key in json_response:
                        cypher_query = json_response[key]
                        print(f"  ℹ️  從 JSON 響應中提取查詢（鍵: {key}）\n")
                        break
            except json.JSONDecodeError:
                pass  # 不是有效的 JSON，繼續原有處理

        # 移除 markdown 代碼塊標記
        if cypher_query.startswith("```cypher"):
            cypher_query = cypher_query.replace("```cypher", "").replace("```", "").strip()
        elif cypher_query.startswith("```"):
            cypher_query = cypher_query.replace("```", "").strip()

        # 提取 Cypher 查詢（處理可能的多行文本）
        lines = cypher_query.split('\n')
        cypher_lines = []
        in_query = False

        for line in lines:
            line_stripped = line.strip()
            # 跳過空行和註釋
            if not line_stripped or line_stripped.startswith('#') or line_stripped.startswith('//'):
                continue
            # 檢測 Cypher 關鍵字開始
            if any(line_stripped.upper().startswith(kw) for kw in ['MATCH', 'CREATE', 'MERGE', 'WITH', 'RETURN', 'WHERE', 'OPTIONAL', 'CALL']):
                in_query = True
            # 收集查詢行
            if in_query:
                cypher_lines.append(line_stripped)

        # 重組 Cypher 查詢
        if cypher_lines:
            cypher_query = ' '.join(cypher_lines)

        # 最終驗證
        if not cypher_query or len(cypher_query) < 5:
            raise ValueError(f"無法從 LLM 輸出中提取有效的 Cypher 查詢。原始輸出: {raw_output[:200]}")

        state["cypher_query"] = cypher_query
        state["cypher_retry_count"] = retry_count + 1

        print(f"\n📝 生成的 Cypher (嘗試 {state['cypher_retry_count']}):")
        print(f"{cypher_query}\n")

    except Exception as e:
        state["cypher_errors"] = f"Cypher 生成失敗: {str(e)}"
        state.setdefault("error_log", []).append(state["cypher_errors"])

    return state


# ============================================
# 節點 4: 執行 Cypher 查詢
# ============================================

def execute_cypher(state: AgentState) -> AgentState:
    """
    執行 Cypher 查詢

    如果執行失敗，設置 cypher_errors 觸發重試
    """
    state.setdefault("execution_path", []).append("execute_cypher")

    cypher_query = state.get("cypher_query", "")

    try:
        # 執行查詢
        results = graph.query(cypher_query)

        state["cypher_results"] = results
        state["cypher_errors"] = None  # 清除錯誤標記

        print(f"✅ Cypher 執行成功，返回 {len(results)} 條結果\n")

        # 如果結果為空，記錄警告
        if not results:
            print("⚠️  查詢成功但結果為空\n")

    except Exception as e:
        error_msg = str(e)
        state["cypher_errors"] = error_msg
        state.setdefault("error_log", []).append(f"Cypher 執行錯誤: {error_msg}")

        print(f"❌ Cypher 執行失敗: {error_msg}\n")

    return state


# ============================================
# 節點 5: GraphRAG Global Search
# ============================================

def graphrag_search(state: AgentState) -> AgentState:
    """
    調用 Microsoft GraphRAG 的 Global Search

    使用 subprocess 調用 graphrag CLI
    """
    state.setdefault("execution_path", []).append("graphrag_search")

    question = state["question"]

    try:
        # 構建命令
        cmd = [
            "graphrag",
            "query",
            "--method", "global",
            "--query", question,
            "--config", GRAPHRAG_CONFIG,
            "--data", GRAPHRAG_DATA,
        ]

        print(f"\n🌐 執行 GraphRAG Global Search...")
        print(f"   命令: {' '.join(cmd)}\n")

        # 執行命令（無 timeout 限制，允許長時間運行）
        result = subprocess.run(
            cmd,
            cwd=GRAPHRAG_ROOT,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            # 成功
            output = result.stdout.strip()
            state["graphrag_result"] = output

            print(f"✅ GraphRAG 查詢成功\n")
            print(f"--- 結果預覽 ---")
            print(output[:500] + "...\n" if len(output) > 500 else output + "\n")

        else:
            # 失敗
            error_msg = result.stderr or result.stdout
            state["graphrag_result"] = f"GraphRAG 查詢失敗: {error_msg}"
            state.setdefault("error_log", []).append(error_msg)

            print(f"❌ GraphRAG 執行失敗: {error_msg}\n")

    except Exception as e:
        state["graphrag_result"] = f"GraphRAG 調用異常: {str(e)}"
        state.setdefault("error_log", []).append(str(e))

    return state


# ============================================
# 節點 5.5: GraphRAG Local Search
# ============================================

def local_search_neo4j(state: AgentState) -> AgentState:
    """
    執行 Neo4j Local Search（使用 Vector Search + 豐富上下文）

    直接使用已初始化的 Neo4jLocalSearch 類，不再呼叫 subprocess。
    """
    state.setdefault("execution_path", []).append("local_search")

    question = state["question"]

    try:
        result = neo4j_local_search.search(question, max_hops=2)
        state["local_search_result"] = result
    except Exception as e:
        state["local_search_result"] = f"Local Search 失敗: {str(e)}"
        state.setdefault("error_log", []).append(str(e))

    return state


# ============================================
# 節點 6: 混合模式 (並行執行)
# ============================================

def hybrid_query(state: AgentState) -> AgentState:
    """
    混合模式：並行執行 Cypher 和 GraphRAG

    這個節點會同時觸發兩個查詢引擎
    """
    state.setdefault("execution_path", []).append("hybrid_query")

    # 並行執行兩個查詢 (簡化版，實際可用 asyncio 優化)
    # 1. 執行 Cypher 路徑
    state = generate_cypher(state)
    state = execute_cypher(state)

    # 2. 執行 GraphRAG 路徑
    state = graphrag_search(state)

    # 保存到混合模式結果
    state["hybrid_cypher_results"] = state.get("cypher_results")
    state["hybrid_graphrag_result"] = state.get("graphrag_result")

    return state


# ============================================
# 節點 7: 生成最終回答
# ============================================

def generate_answer(state: AgentState) -> AgentState:
    """
    根據查詢結果生成最終回答
    """
    state.setdefault("execution_path", []).append("generate_answer")

    question = state["question"]
    query_type = state["query_type"]

    try:
        # 根據查詢類型準備結果
        if query_type == "cypher":
            results = state.get("cypher_results", [])
            results_text = json.dumps(results, ensure_ascii=False, indent=2)

        elif query_type == "local_search":
            results_text = state.get("local_search_result", "無結果")

        elif query_type == "graphrag":
            results_text = state.get("graphrag_result", "無結果")

        elif query_type == "hybrid":
            # 使用混合融合 Prompt
            cypher_results = state.get("hybrid_cypher_results", [])
            graphrag_result = state.get("hybrid_graphrag_result", "")

            fusion_prompt = HYBRID_FUSION_PROMPT.format(
                question=question,
                cypher_results=json.dumps(cypher_results, ensure_ascii=False, indent=2),
                graphrag_results=graphrag_result,
            )

            chain = llm | StrOutputParser()
            final_answer = chain.invoke(fusion_prompt)

            state["final_answer"] = final_answer
            state["confidence"] = 0.85  # 混合模式置信度較高

            print(f"\n💬 生成最終回答 (混合模式):\n")
            print(final_answer + "\n")

            return state

        else:
            results_text = "未知查詢類型"

        # 生成回答
        chain = QA_GENERATION_PROMPT | llm | StrOutputParser()
        final_answer = chain.invoke({
            "question": question,
            "results": results_text,
            "query_type": query_type,
        })

        state["final_answer"] = final_answer

        # 計算置信度 (簡化版)
        if query_type == "cypher" and state.get("cypher_results"):
            state["confidence"] = 0.9
        elif query_type == "local_search" and state.get("local_search_result"):
            state["confidence"] = 0.85  # Local search 結合拓撲分析，置信度較高
        elif query_type == "graphrag":
            state["confidence"] = 0.8
        else:
            state["confidence"] = 0.5

        print(f"\n💬 生成最終回答 ({query_type}):\n")
        print(final_answer + "\n")

    except Exception as e:
        state["final_answer"] = f"回答生成失敗: {str(e)}"
        state["confidence"] = 0.0
        state.setdefault("error_log", []).append(str(e))

    return state


# ============================================
# 條件判斷函數 (用於 LangGraph 路由)
# ============================================

def check_query_type(state: AgentState) -> str:
    """
    檢查查詢類型，決定下一步路徑
    """
    query_type = state.get("query_type", "cypher")
    return query_type


def check_cypher_execution(state: AgentState) -> str:
    """
    檢查 Cypher 執行結果，決定是否重試

    Returns:
        "retry" - 重試生成 Cypher
        "success" - 成功，生成回答
        "max_retries" - 達到最大重試次數，放棄
    """
    errors = state.get("cypher_errors")
    retry_count = state.get("cypher_retry_count", 0)

    if errors:
        if retry_count >= MAX_CYPHER_RETRIES:
            print(f"⚠️  達到最大重試次數 ({MAX_CYPHER_RETRIES})，停止重試\n")
            return "max_retries"
        else:
            print(f"🔄 觸發自我修正，重試 Cypher 生成...\n")
            return "retry"
    else:
        return "success"


def handle_max_retries(state: AgentState) -> AgentState:
    """
    處理達到最大重試次數的情況

    降級到 GraphRAG 或返回錯誤信息
    """
    state.setdefault("execution_path", []).append("handle_max_retries")

    print("⚠️  Cypher 查詢重試失敗，降級到 GraphRAG...\n")

    # 降級到 GraphRAG
    state["query_type"] = "graphrag"
    state = graphrag_search(state)
    state = generate_answer(state)

    return state

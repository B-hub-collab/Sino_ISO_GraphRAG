"""
Neo4j Global Search - Map-Reduce over Community Summaries

實現類似 GraphRAG 的 Global Search，使用 Map-Reduce 架構處理社群摘要
"""

from typing import List, Dict, Optional, Any
from langchain_core.language_models import BaseChatModel
from langchain_neo4j import Neo4jGraph
from pydantic import BaseModel, Field
import json


class IntermediateResponse(BaseModel):
    """Map 階段的中間回答"""
    points: List[str] = Field(description="從社群摘要中提取的要點列表")
    rating: float = Field(description="回答的重要性評分 (0-10)")


class Neo4jGlobalSearch:
    """
    Neo4j Global Search 實現
    
    使用 Map-Reduce 模式查詢 Community 摘要來回答全域性問題
    """
    
    def __init__(
        self,
        graph: Neo4jGraph,
        llm: BaseChatModel,
        level: int = 0,
        max_communities: Optional[int] = None,
        importance_threshold: float = 5.0,
        max_tokens_per_chunk: int = 2000,
    ):
        """
        初始化 Global Search
        
        Args:
            graph: Neo4j 圖資料庫連接
            llm: LLM 模型
            level: 要查詢的社群層級 (預設 0 為最高層)
            max_communities: 最多檢索的社群數量
            importance_threshold: 重要性閾值，低於此值的要點會被過濾
            max_tokens_per_chunk: 每個文本塊的最大 token 數
        """
        self.graph = graph
        self.llm = llm
        self.level = level
        self.max_communities = max_communities
        self.importance_threshold = importance_threshold
        self.max_tokens_per_chunk = max_tokens_per_chunk
    
    def _retrieve_communities(self, level: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        從 Neo4j 檢索指定層級的社群
        
        Args:
            level: 社群層級，None 則使用初始化時的 level
            
        Returns:
            社群列表，包含 id, title, summary, full_content, rank
        """
        query_level = level if level is not None else self.level
        
        query = """
        MATCH (c:__Community__)
        WHERE c.level = $level
          AND c.summary IS NOT NULL
          AND c.summary <> ''
        RETURN 
            c.id as id,
            c.community as community,
            c.title as title,
            c.summary as summary,
            c.full_content as full_content,
            c.rank as rank,
            c.size as size
        ORDER BY c.rank DESC
        """
        
        if self.max_communities:
            query += f" LIMIT {self.max_communities}"
        
        result = self.graph.query(query, params={"level": query_level})
        
        return result
    
    def _chunk_text(self, text: str, max_tokens: int = 2000) -> List[str]:
        """
        將文本切分成塊
        
        Args:
            text: 要切分的文本
            max_tokens: 每塊的最大 token 數（簡化：使用字符數估算）
            
        Returns:
            文本塊列表
        """
        # 簡化版：假設平均 1 token ≈ 2 中文字符 or 4 英文字符
        max_chars = max_tokens * 2
        
        if len(text) <= max_chars:
            return [text]
        
        chunks = []
        current_chunk = ""
        
        # 按段落切分
        paragraphs = text.split('\n')
        
        for para in paragraphs:
            if len(current_chunk) + len(para) + 1 <= max_chars:
                current_chunk += para + '\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + '\n'
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _map_community_to_response(
        self, 
        community: Dict[str, Any], 
        query: str
    ) -> IntermediateResponse:
        """
        Map 階段：針對單個社群摘要生成中間回答
        
        Args:
            community: 社群資訊
            query: 用戶查詢
            
        Returns:
            中間回答（要點 + 評分）
        """
        # 使用 full_content 或 summary
        content = community.get('full_content') or community.get('summary', '')
        
        # 如果內容太長，切分處理
        chunks = self._chunk_text(content, self.max_tokens_per_chunk)
        
        # 對每個塊生成要點（簡化版：只處理第一塊）
        chunk = chunks[0] if chunks else content
        
        map_prompt = f"""你是一位專業的資訊分析師。請根據以下社群摘要，針對用戶問題提取相關的重要資訊。\n\n【社群摘要】\n{chunk}\n\n【用戶問題】\n{query}\n\n請提取與問題相關的關鍵要點，並評估這些要點的重要性。\n\n請以 JSON 格式回覆：\n{{"points": ["要點1", "要點2", ...], "rating": 重要性評分(0-10)}}\n\n如果此社群摘要與問題無關，請返回空的 points 列表和 0 分。"""
        
        try:
            response = self.llm.invoke(map_prompt)
            content = response.content
            
            # 解析 JSON
            # 嘗試提取 JSON（可能包含在 markdown code block 中）
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            
            result = json.loads(json_str)
            return IntermediateResponse(**result)
        
        except Exception as e:
            print(f"  ⚠️ Map 階段錯誤: {e}")
            # 降級：返回空結果
            return IntermediateResponse(points=[], rating=0.0)
    
    def _reduce_responses(
        self,
        intermediate_responses: List[IntermediateResponse],
        query: str
    ) -> str:
        """
        Reduce 階段：聚合中間回答，生成最終答案
        
        Args:
            intermediate_responses: Map 階段的中間回答列表
            query: 用戶查詢
            
        Returns:
            最終答案
        """
        # 過濾低分要點
        filtered_points = []
        for response in intermediate_responses:
            if response.rating >= self.importance_threshold:
                filtered_points.extend(response.points)
        
        if not filtered_points:
            return "抱歉，根據現有社群摘要，我無法找到與您問題相關的資訊。"
        
        # 聚合要點
        aggregated_context = "\n".join([f"- {point}" for point in filtered_points])
        
        reduce_prompt = f"""你是一位專業的契約分析專家。請根據以下從多個社群摘要中提取的關鍵要點，針對用戶問題生成一個全面、準確的回答。\n\n【用戶問題】\n{query}\n\n【提取的關鍵要點】\n{aggregated_context}\n\n請生成一個詳細且有結構的回答，確保：\n1. 直接回答用戶的問題\n2. 整合所有相關要點\n3. 使用清晰的組織結構（如分點或段落）\n4. 基於提取的要點，不要過度推測\n\n回答："""
        
        try:
            response = self.llm.invoke(reduce_prompt)
            return response.content
        
        except Exception as e:
            print(f"  ✗ Reduce 階段錯誤: {e}")
            # 降級：直接返回要點列表
            return f"根據社群摘要分析：\n\n{aggregated_context}"
    
    def search(
        self,
        query: str,
        level: Optional[int] = None,
        verbose: bool = True
    ) -> str:
        """
        執行 Global Search
        
        Args:
            query: 用戶查詢
            level: 社群層級（覆蓋初始化時的設定）
            verbose: 是否顯示詳細過程
            
        Returns:
            最終答案
        """
        if verbose:
            print(f"\n🌐 Neo4j Global Search")
            print(f"   Query: {query}")
            print(f"   Level: {level if level is not None else self.level}")
        
        # 1. 檢索社群
        if verbose:
            print(f"\n   📊 檢索社群摘要...")
        
        communities = self._retrieve_communities(level)
        
        if not communities:
            return "抱歉，沒有找到可用的社群摘要。"
        
        if verbose:
            print(f"   ✓ 找到 {len(communities)} 個社群")
        
        # 2. Map 階段：對每個社群生成中間回答
        if verbose:
            print(f"\n   🗺️  Map 階段：分析社群摘要...")
        
        intermediate_responses = []
        for i, community in enumerate(communities, 1):
            if verbose:
                print(f"      處理社群 {i}/{len(communities)}: {community.get('title', 'Untitled')[:50]}...")
            
            response = self._map_community_to_response(community, query)
            intermediate_responses.append(response)
            
            if verbose and response.rating > 0:
                print(f"         評分: {response.rating:.1f}, 要點數: {len(response.points)}")
        
        # 3. Reduce 階段：聚合生成最終答案
        if verbose:
            print(f"\n   📝 Reduce 階段：聚合要點生成答案...")
        
        final_answer = self._reduce_responses(intermediate_responses, query)
        
        if verbose:
            print(f"\n   ✓ Global Search 完成\n")
        
        return final_answer


# 便利函數
def create_global_search(
    graph: Neo4jGraph,
    llm: BaseChatModel,
    **kwargs
) -> Neo4jGlobalSearch:
    """創建 Global Search 實例"""
    return Neo4jGlobalSearch(graph=graph, llm=llm, **kwargs)

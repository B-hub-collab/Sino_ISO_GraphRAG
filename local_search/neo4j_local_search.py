"""
Neo4j 版本的 Local Search

完全基於 Neo4j 數據庫實現，復刻 GraphRAG Local Search 的功能
不依賴 parquet 文件，直接查詢 Neo4j

升級版 v2：
- Entity + Community 雙向量搜尋
- 完整 community reports（summary + full_content）
- TextUnit + MENTIONS 原文檢索
- 動態 schema 偵測
"""

import os
import json
from typing import List, Dict, Any, Tuple, Optional
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_neo4j import Neo4jGraph
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False


class Neo4jLocalSearch:
    """基於 Neo4j 的 Local Search 引擎"""

    def __init__(
        self,
        graph: Neo4jGraph,
        llm: AzureChatOpenAI,
        embeddings: AzureOpenAIEmbeddings,
        max_context_tokens: int = 12000,
        community_prop: float = 0.15,
        text_unit_prop: float = 0.50,
    ):
        """
        初始化 Local Search

        Args:
            graph: Neo4j 連接
            llm: LLM 模型
            embeddings: Embedding 模型
            max_context_tokens: 總 token 預算
            community_prop: Community reports 佔總預算比例
            text_unit_prop: Text units 佔總預算比例
        """
        self.graph = graph
        self.llm = llm
        self.embeddings = embeddings
        self.max_context_tokens = max_context_tokens
        self.community_prop = community_prop
        self.text_unit_prop = text_unit_prop

        # Token 計數器
        if _TIKTOKEN_AVAILABLE:
            self._encoding = tiktoken.get_encoding("cl100k_base")
        else:
            self._encoding = None

        # 偵測 Neo4j schema
        self._schema = self._detect_schema()

        # Local Search Prompt（參考 GraphRAG）
        self.prompt_template = """---Role---

You are a helpful assistant responding to questions about data in the tables provided.


---Goal---

Generate a response of the target length and format that responds to the user's question, summarizing all information in the input data tables appropriate for the response length and format, and incorporating any relevant general knowledge.

If you don't know the answer, just say so. Do not make anything up.

Points supported by data should list their data references as follows:

"This is an example sentence supported by multiple data references [Data: <dataset name> (record ids); <dataset name> (record ids)]."

Do not list more than 5 record ids in a single reference. Instead, list the top 5 most relevant record ids and add "+more" to indicate that there are more.

For example:

"Person X is the owner of Company Y and subject to many allegations of wrongdoing [Data: Entities (5, 7); Relationships (23)]."

Do not include information where the supporting evidence for it is not provided.


---Target response length and format---

Multiple paragraphs in Chinese (Traditional). Add sections and commentary to the response as appropriate. Style the response in markdown.


---Data tables---

{context_data}


---User Question---

{question}


---Response---

請根據上述數據表格回答問題。使用繁體中文，以 Markdown 格式回答，並引用數據來源。
"""

    # ================================================================
    # Token 計數
    # ================================================================

    def _count_tokens(self, text: str) -> int:
        """計算文字的 token 數。使用 tiktoken，fallback 到 len//2（中文約 1 字 ≈ 2 tokens）"""
        if not text:
            return 0
        if self._encoding:
            return len(self._encoding.encode(text))
        return len(text) // 2

    # ================================================================
    # Step 1: Schema 偵測
    # ================================================================

    def _detect_schema(self) -> Dict[str, Any]:
        """
        偵測 Neo4j 中的 schema，確認 Community / TextUnit 的標籤、關係、向量索引。

        Returns:
            schema dict with keys:
              - community_label: str or None
              - community_rel: str or None
              - has_text_units: bool
              - has_vector_index: bool (entity_embeddings)
              - has_community_vector: bool (community_embeddings)
              - has_text_unit_vector: bool (text_unit_embeddings)
        """
        schema: Dict[str, Any] = {
            "community_label": None,
            "community_rel": None,
            "has_text_units": False,
            "has_vector_index": False,
            "has_community_vector": False,
            "has_text_unit_vector": False,
        }

        # --- Community 標籤 + 關係（優先選有關係的標籤）---
        for candidate_label in ["Community", "__Community__"]:
            try:
                result = self.graph.query(
                    f"MATCH (:Entity)-[r]->(:`{candidate_label}`) "
                    "RETURN type(r) AS rel_type LIMIT 1"
                )
                if result:
                    schema["community_label"] = candidate_label
                    schema["community_rel"] = result[0]["rel_type"]
                    print(f"  ℹ️  Community: {candidate_label} (關係: {schema['community_rel']})")
                    break
            except Exception:
                pass

        if not schema["community_label"]:
            try:
                result = self.graph.query(
                    "MATCH (c) WHERE c:Community OR c:`__Community__` "
                    "RETURN CASE WHEN 'Community' IN labels(c) THEN 'Community' "
                    "ELSE '__Community__' END AS label LIMIT 1"
                )
                if result:
                    schema["community_label"] = result[0]["label"]
                    print(f"  ℹ️  Community: {schema['community_label']} (無關係)")
            except Exception:
                pass

        # --- TextUnit ---
        try:
            result = self.graph.query(
                "MATCH (t:TextUnit)-[:MENTIONS]->(:Entity) "
                "RETURN count(t) AS cnt LIMIT 1"
            )
            if result and result[0]["cnt"] > 0:
                schema["has_text_units"] = True
                print(f"  ℹ️  TextUnit: MENTIONS 關係 ✓")
        except Exception:
            try:
                result = self.graph.query(
                    "MATCH (:Entity)<-[:MENTIONS]-(t:TextUnit) "
                    "RETURN count(t) AS cnt LIMIT 1"
                )
                if result and result[0]["cnt"] > 0:
                    schema["has_text_units"] = True
                    print(f"  ℹ️  TextUnit: 反向 MENTIONS ✓")
            except Exception:
                pass

        # --- Vector indexes（偵測全部三個）---
        try:
            result = self.graph.query(
                "SHOW INDEXES YIELD name, type WHERE type = 'VECTOR' RETURN name"
            )
            index_names = {r["name"] for r in result}

            if "entity_embeddings" in index_names:
                schema["has_vector_index"] = True
            if "community_embeddings" in index_names:
                schema["has_community_vector"] = True
            if "text_unit_embeddings" in index_names:
                schema["has_text_unit_vector"] = True

            found = [n for n in ["entity_embeddings", "community_embeddings", "text_unit_embeddings"] if n in index_names]
            if found:
                print(f"  ℹ️  Vector indexes: {', '.join(found)}")
        except Exception:
            pass

        return schema

    # ================================================================
    # Step 2: Vector Search
    # ================================================================

    def find_entities_by_vector_search(
        self, question: str, top_k: int = 10, score_threshold: float = 0.7
    ) -> List[Dict]:
        """
        使用向量搜索找到與問題最相關的實體。

        Args:
            question: 用戶問題
            top_k: 返回的最大實體數量
            score_threshold: 最低相似度分數

        Returns:
            含 score 的實體列表
        """
        # 產生 embedding
        query_embedding = self.embeddings.embed_query(question)

        query = """
        CALL db.index.vector.queryNodes('entity_embeddings', $top_k, $embedding)
        YIELD node, score
        WHERE score > $threshold
        RETURN node.id AS id,
               node.title AS title,
               node.type AS type,
               node.description AS description,
               node.degree AS degree,
               node.human_readable_id AS human_readable_id,
               score
        ORDER BY score DESC
        """

        results = self.graph.query(query, {
            "embedding": query_embedding,
            "top_k": top_k,
            "threshold": score_threshold,
        })

        if results:
            print(f"  ✓ Vector Search 找到 {len(results)} 個實體 (threshold={score_threshold})")
            for r in results[:5]:
                print(f"    - {r['title']} (score={r['score']:.3f})")

        return results

    # ================================================================
    # Step 2b: Community Vector Search
    # ================================================================

    def find_communities_by_vector_search(
        self, question: str, top_k: int = 5, score_threshold: float = 0.7
    ) -> List[Dict]:
        """
        使用向量搜索找到與問題最相關的社群報告。

        Args:
            question: 用戶問題
            top_k: 返回的最大社群數量
            score_threshold: 最低相似度分數

        Returns:
            含 score 的社群列表（id, title, summary, full_content, rank, score）
        """
        query_embedding = self.embeddings.embed_query(question)

        query = """
        CALL db.index.vector.queryNodes('community_embeddings', $top_k, $embedding)
        YIELD node, score
        WHERE score > $threshold
        RETURN node.id AS id,
               node.title AS title,
               node.summary AS summary,
               node.full_content AS full_content,
               node.rank AS rank,
               node.community AS community,
               node.level AS level,
               score
        ORDER BY score DESC
        """

        results = self.graph.query(query, {
            "embedding": query_embedding,
            "top_k": top_k,
            "threshold": score_threshold,
        })

        if results:
            print(f"  ✓ Community Vector Search 找到 {len(results)} 個社群 (threshold={score_threshold})")
            for r in results[:3]:
                print(f"    - {r['title']} (rank={r['rank']}, score={r['score']:.3f})")

        return results

    # ================================================================
    # 原有 fallback 方法（保留）
    # ================================================================

    def extract_entities_from_question(self, question: str) -> List[str]:
        """
        從問題中提取實體名稱（LLM call — 作為 vector search 的 fallback）

        Args:
            question: 用戶問題

        Returns:
            實體名稱列表
        """
        extraction_prompt = f"""從以下問題中提取所有實體名稱（組織、人物、地點、術語等）。

問題: {question}

請以 JSON 格式返回提取的實體列表。格式：
{{"entities": ["實體1", "實體2", ...]}}

如果沒有明確的實體，返回空列表。只返回 JSON，不要其他文字。"""

        try:
            chain = self.llm | StrOutputParser()
            response = chain.invoke(extraction_prompt)

            # 清理並解析 JSON
            response_clean = response.strip()
            if response_clean.startswith("```json"):
                response_clean = response_clean.replace("```json", "").replace("```", "").strip()
            elif response_clean.startswith("```"):
                response_clean = response_clean.replace("```", "").strip()

            extracted = json.loads(response_clean)
            entities = extracted.get("entities", [])

            print(f"  📍 提取到 {len(entities)} 個實體: {entities}")
            return entities

        except Exception as e:
            print(f"  ⚠️  實體提取失敗: {e}")
            return []

    def find_matching_entities_in_neo4j(self, entity_mentions: List[str], top_k: int = 3) -> List[Dict]:
        """
        在 Neo4j 中找到匹配的實體（文字比對 — 作為 vector search 的 fallback）

        使用多種策略：
        1. 精確匹配
        2. 模糊匹配（CONTAINS）
        3. 高度數節點（如果找不到匹配）

        Args:
            entity_mentions: 提取的實體名稱列表
            top_k: 每個實體返回的最佳匹配數量

        Returns:
            匹配的實體列表
        """
        matched_entities = []

        for mention in entity_mentions:
            # 嘗試精確匹配
            query = """
            MATCH (e:Entity)
            WHERE toLower(e.title) = toLower($mention)
            RETURN e.id AS id,
                   e.title AS title,
                   e.type AS type,
                   e.description AS description,
                   e.degree AS degree,
                   e.human_readable_id AS human_readable_id
            LIMIT $top_k
            """
            results = self.graph.query(query, {"mention": mention, "top_k": top_k})

            if results:
                matched_entities.extend(results)
                print(f"  ✓ 精確匹配 '{mention}': {len(results)} 個實體")
                continue

            # 如果精確匹配失敗，嘗試模糊匹配
            query = """
            MATCH (e:Entity)
            WHERE toLower(e.title) CONTAINS toLower($mention)
            RETURN e.id AS id,
                   e.title AS title,
                   e.type AS type,
                   e.description AS description,
                   e.degree AS degree,
                   e.human_readable_id AS human_readable_id
            ORDER BY e.degree DESC
            LIMIT $top_k
            """
            results = self.graph.query(query, {"mention": mention, "top_k": top_k})

            if results:
                matched_entities.extend(results)
                print(f"  ✓ 模糊匹配 '{mention}': {len(results)} 個實體")
            else:
                print(f"  ⚠️  未找到 '{mention}' 的匹配實體")

        # 如果沒有找到任何匹配，返回度數最高的實體
        if not matched_entities:
            print(f"  ℹ️  未找到匹配實體，返回度數最高的實體")
            query = """
            MATCH (e:Entity)
            WHERE e.degree IS NOT NULL
            RETURN e.id AS id,
                   e.title AS title,
                   e.type AS type,
                   e.description AS description,
                   e.degree AS degree,
                   e.human_readable_id AS human_readable_id
            ORDER BY e.degree DESC
            LIMIT $top_k
            """
            matched_entities = self.graph.query(query, {"top_k": 5})

        return matched_entities

    # ================================================================
    # Step 3: 豐富上下文檢索
    # ================================================================

    def get_enriched_context(self, entity_ids: List[str], max_hops: int = 2) -> Dict[str, List[Dict]]:
        """
        從種子實體出發，透過 graph traversal 收集 entities, relationships, text_units。
        （Community reports 改由 vector search 獨立取得，不在此查詢）

        Args:
            entity_ids: 種子實體 ID 列表
            max_hops: 圖遍歷的最大跳數

        Returns:
            dict with keys: entities, relationships, text_units
        """
        # TextUnit 子查詢
        if self._schema["has_text_units"]:
            text_unit_subquery = """
            collect {
                UNWIND all_nodes AS tu_node
                MATCH (tu_node)<-[:MENTIONS]-(t:TextUnit)
                WITH t, count(*) AS freq
                ORDER BY freq DESC
                LIMIT 5
                RETURN {id: t.id, text: t.text, n_tokens: t.n_tokens} AS tu
            } AS text_units,
            """
        else:
            text_unit_subquery = "[] AS text_units,"

        # Community 子查詢（透過圖遍歷取得，作為 vector search 的補充）
        cl = self._schema.get("community_label")
        cr = self._schema.get("community_rel")
        if cl and cr:
            community_subquery = f"""
            collect {{
                UNWIND all_nodes AS cm_node
                MATCH (cm_node)-[:`{cr}`]->(c:`{cl}`)
                WHERE c.summary IS NOT NULL AND c.summary <> ''
                WITH c, count(*) AS member_count
                ORDER BY c.rank DESC
                LIMIT 5
                RETURN {{
                    id: c.id,
                    title: c.title,
                    summary: c.summary,
                    full_content: c.full_content,
                    rank: c.rank
                }} AS cr
            }} AS community_reports,
            """
        else:
            community_subquery = "[] AS community_reports,"

        query = f"""
        // 從種子實體出發，N-hop 擴展
        MATCH (start:Entity)
        WHERE start.id IN $entity_ids
        OPTIONAL MATCH path = (start)-[r:RELATED_TO*1..{max_hops}]-(neighbor:Entity)
        WITH collect(DISTINCT start) + collect(DISTINCT neighbor) AS node_list
        UNWIND node_list AS n
        WITH collect(DISTINCT n) AS all_nodes

        // 1. 實體間關係
        WITH all_nodes,
        collect {{
            UNWIND all_nodes AS rel_src
            MATCH (rel_src)-[r:RELATED_TO]-(rel_tgt:Entity)
            WHERE rel_tgt IN all_nodes
            RETURN DISTINCT {{
                source: startNode(r).title,
                target: endNode(r).title,
                description: r.description,
                weight: r.weight,
                human_readable_id: r.human_readable_id
            }} AS rel
        }} AS relationships,

        // 2. TextUnit 原文
        {text_unit_subquery}

        // 3. Community 摘要（圖遍歷）
        {community_subquery}

        // 4. 實體資訊
        [n IN all_nodes | {{
            id: n.id,
            title: n.title,
            type: n.type,
            description: n.description,
            degree: n.degree,
            human_readable_id: n.human_readable_id
        }}] AS entities

        RETURN entities, relationships, text_units, community_reports
        """

        try:
            results = self.graph.query(query, {"entity_ids": entity_ids})

            if results:
                row = results[0]
                entities = row.get("entities", [])
                relationships = row.get("relationships", [])
                text_units = row.get("text_units", [])
                community_reports = row.get("community_reports", [])

                print(f"  📊 Graph context: {len(entities)} 實體, {len(relationships)} 關係, "
                      f"{len(text_units)} 原文段, {len(community_reports)} 社群報告(圖)")

                return {
                    "entities": entities,
                    "relationships": relationships,
                    "text_units": text_units,
                    "community_reports": community_reports,
                }
            else:
                return {"entities": [], "relationships": [], "text_units": [], "community_reports": []}

        except Exception as e:
            print(f"  ⚠️  豐富上下文查詢失敗，fallback 到基本子圖: {e}")
            entities, relationships = self.get_local_subgraph(entity_ids, max_hops)
            return {
                "entities": entities,
                "relationships": relationships,
                "text_units": [],
                "community_reports": [],
            }

    # ================================================================
    # 原有基本子圖方法（保留作為 fallback）
    # ================================================================

    def get_local_subgraph(self, entity_ids: List[str], max_hops: int = 2) -> Tuple[List[Dict], List[Dict]]:
        """
        獲取實體的局部子圖

        Args:
            entity_ids: 實體 ID 列表
            max_hops: 最大跳數

        Returns:
            (實體列表, 關係列表)
        """
        # 獲取 N 跳內的鄰居實體和關係
        query = f"""
        MATCH (start:Entity)
        WHERE start.id IN $entity_ids
        CALL (start) {{
            WITH start
            MATCH path = (start)-[r:RELATED_TO*1..{max_hops}]-(neighbor:Entity)
            RETURN DISTINCT neighbor, relationships(path) AS rels
        }}
        WITH collect(DISTINCT neighbor) AS neighbors,
             collect(DISTINCT rels) AS all_rels

        // 獲取所有相關實體
        UNWIND neighbors AS n
        WITH collect({{
            id: n.id,
            human_readable_id: n.human_readable_id,
            title: n.title,
            type: n.type,
            description: n.description,
            degree: n.degree
        }}) AS entities, all_rels

        // 獲取所有關係
        UNWIND all_rels AS rel_path
        UNWIND rel_path AS r
        WITH entities, collect(DISTINCT {{
            source: startNode(r).title,
            target: endNode(r).title,
            description: r.description,
            weight: r.weight,
            human_readable_id: r.human_readable_id
        }}) AS relationships

        RETURN entities, relationships
        """

        try:
            results = self.graph.query(query, {"entity_ids": entity_ids})

            if results:
                entities = results[0].get("entities", [])
                relationships = results[0].get("relationships", [])
                print(f"  📊 局部子圖: {len(entities)} 個實體, {len(relationships)} 個關係")
                return entities, relationships
            else:
                return [], []

        except Exception as e:
            print(f"  ⚠️  獲取子圖失敗: {e}")
            return [], []

    # ================================================================
    # Step 4: Token-Budgeted 上下文格式化
    # ================================================================

    def _format_entities(self, entities: List[Dict], max_tokens: int) -> Tuple[str, int]:
        """格式化 Entities 表格，逐筆加入直到超過 token 預算。按 score(desc) → degree(desc) 排序。"""
        if not entities:
            return "", 0

        # 排序：score (desc) → degree (desc)
        sorted_entities = sorted(
            entities,
            key=lambda e: (e.get("score", 0), e.get("degree", 0)),
            reverse=True,
        )

        header = "## Entities\n\n| id | title | type | description | degree |\n|---|---|---|---|---|\n"
        header_tokens = self._count_tokens(header)
        if header_tokens >= max_tokens:
            return "", 0

        lines = []
        used_tokens = header_tokens
        for e in sorted_entities:
            desc = e.get("description") or ""
            if len(desc) > 200:
                desc = desc[:200] + "..."
            line = f"| {e.get('human_readable_id', 0)} | {e.get('title', '')} | {e.get('type', '')} | {desc} | {e.get('degree', 0)} |\n"
            line_tokens = self._count_tokens(line)
            if used_tokens + line_tokens > max_tokens:
                break
            lines.append(line)
            used_tokens += line_tokens

        if not lines:
            return "", 0
        return header + "".join(lines) + "\n", used_tokens

    def _format_relationships(self, rels: List[Dict], max_tokens: int) -> Tuple[str, int]:
        """格式化 Relationships 表格，逐筆加入直到超過 token 預算。按 weight(desc) 排序。"""
        if not rels:
            return "", 0

        sorted_rels = sorted(rels, key=lambda r: r.get("weight", 0), reverse=True)

        header = "## Relationships\n\n| id | source | target | description | weight |\n|---|---|---|---|---|\n"
        header_tokens = self._count_tokens(header)
        if header_tokens >= max_tokens:
            return "", 0

        lines = []
        used_tokens = header_tokens
        for r in sorted_rels:
            desc = r.get("description") or ""
            if len(desc) > 200:
                desc = desc[:200] + "..."
            line = f"| {r.get('human_readable_id', 0)} | {r.get('source', '')} | {r.get('target', '')} | {desc} | {r.get('weight', 0)} |\n"
            line_tokens = self._count_tokens(line)
            if used_tokens + line_tokens > max_tokens:
                break
            lines.append(line)
            used_tokens += line_tokens

        if not lines:
            return "", 0
        return header + "".join(lines) + "\n", used_tokens

    def _truncate_text_to_budget(self, text: str, token_budget: int) -> str:
        """截斷文字使其不超過 token 預算（含 '...' 後綴）。使用二分搜尋找到最佳截斷點。"""
        if self._count_tokens(text) <= token_budget:
            return text
        ellipsis = "..."
        ellipsis_tokens = self._count_tokens(ellipsis)
        budget_for_text = token_budget - ellipsis_tokens
        if budget_for_text <= 0:
            return ""
        # 二分搜尋：找最大 char_len 使得 text[:len] 的 tokens <= budget_for_text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._count_tokens(text[:mid]) <= budget_for_text:
                lo = mid
            else:
                hi = mid - 1
        if lo == 0:
            return ""
        return text[:lo] + ellipsis

    def _format_text_units(self, text_units: List[Dict], max_tokens: int) -> Tuple[str, int]:
        """格式化 TextUnit 原文，逐筆加入直到超過 token 預算。保持原順序。"""
        if not text_units:
            return "", 0

        header = "## Source Text\n\n"
        header_tokens = self._count_tokens(header)
        if header_tokens >= max_tokens:
            return "", 0

        parts = []
        used_tokens = header_tokens
        for i, tu in enumerate(text_units, 1):
            text = (tu.get("text") or "") if isinstance(tu, dict) else ""
            if not text:
                continue
            chunk_id = (tu.get("chunk_id") or tu.get("id") or i) if isinstance(tu, dict) else i
            section = f"### Text Unit {chunk_id}\n\n{text}\n\n"
            section_tokens = self._count_tokens(section)
            if used_tokens + section_tokens > max_tokens:
                # 嘗試截斷這一段以填滿剩餘預算
                remaining = max_tokens - used_tokens
                if remaining > 50:
                    prefix = f"### Text Unit {chunk_id}\n\n"
                    prefix_tokens = self._count_tokens(prefix)
                    text_budget = remaining - prefix_tokens - 3
                    if text_budget > 0:
                        truncated = self._truncate_text_to_budget(text, text_budget)
                        if truncated:
                            section = prefix + truncated + "\n\n"
                            section_tokens = self._count_tokens(section)
                            if used_tokens + section_tokens <= max_tokens:
                                parts.append(section)
                                used_tokens += section_tokens
                break
            parts.append(section)
            used_tokens += section_tokens

        if not parts:
            return "", 0
        return header + "".join(parts), used_tokens

    def _format_communities(self, community_reports: List[Dict], max_tokens: int) -> Tuple[str, int]:
        """格式化 Community Reports，逐筆加入直到超過 token 預算。按 score(desc) → rank(desc) 排序。"""
        if not community_reports:
            return "", 0

        sorted_communities = sorted(
            [cr for cr in community_reports if isinstance(cr, dict)],
            key=lambda c: (c.get("score", 0), c.get("rank", 0)),
            reverse=True,
        )

        header = "## Community Reports\n\n"
        header_tokens = self._count_tokens(header)
        if header_tokens >= max_tokens:
            return "", 0

        parts = []
        used_tokens = header_tokens
        for i, cr in enumerate(sorted_communities, 1):
            title = cr.get("title") or f"Community {i}"
            rank = cr.get("rank") or "N/A"
            content = cr.get("full_content") or cr.get("summary") or ""
            if not content:
                continue
            score_info = f", score: {cr['score']:.3f}" if "score" in cr else ""
            section = f"### {title} (rank: {rank}{score_info})\n\n{content}\n\n"
            section_tokens = self._count_tokens(section)
            if used_tokens + section_tokens > max_tokens:
                # 嘗試截斷 content 以填滿剩餘預算
                remaining = max_tokens - used_tokens
                if remaining > 50:
                    prefix = f"### {title} (rank: {rank}{score_info})\n\n"
                    prefix_tokens = self._count_tokens(prefix)
                    content_budget = remaining - prefix_tokens - 3
                    if content_budget > 0:
                        truncated = self._truncate_text_to_budget(content, content_budget)
                        if truncated:
                            section = prefix + truncated + "\n\n"
                            section_tokens = self._count_tokens(section)
                            if used_tokens + section_tokens <= max_tokens:
                                parts.append(section)
                                used_tokens += section_tokens
                break
            parts.append(section)
            used_tokens += section_tokens

        if not parts:
            return "", 0
        return header + "".join(parts), used_tokens

    def format_context_data(
        self,
        data,
        relationships=None,
        max_tokens: Optional[int] = None,
        community_prop: Optional[float] = None,
        text_unit_prop: Optional[float] = None,
    ) -> str:
        """
        格式化上下文數據為表格形式，按 token 預算分配各類別。

        支持兩種輸入格式：
        - 新格式：dict with keys entities, relationships, text_units, community_reports
        - 舊格式：(entities: List[Dict], relationships: List[Dict])

        Args:
            data: 上下文數據
            relationships: 關係列表（舊格式）
            max_tokens: 總 token 預算（None = 使用 self.max_context_tokens）
            community_prop: Community 佔比（None = 使用 self.community_prop）
            text_unit_prop: Text unit 佔比（None = 使用 self.text_unit_prop）

        Returns:
            格式化的上下文字符串
        """
        total = max_tokens or self.max_context_tokens
        c_prop = community_prop if community_prop is not None else self.community_prop
        t_prop = text_unit_prop if text_unit_prop is not None else self.text_unit_prop

        # 預算分配
        community_budget = int(total * c_prop)
        text_unit_budget = int(total * t_prop)
        local_budget = total - community_budget - text_unit_budget
        entity_budget = int(local_budget * 0.6)
        rel_budget = local_budget - entity_budget

        # 解析輸入
        if isinstance(data, list):
            entities = data
            rels = relationships or []
            text_units: List[Dict] = []
            community_reports: List[Dict] = []
        else:
            entities = data.get("entities", [])
            rels = data.get("relationships", [])
            text_units = data.get("text_units", [])
            community_reports = data.get("community_reports", [])

        # 按預算格式化各區塊
        entity_text, entity_used = self._format_entities(entities, entity_budget)
        rel_text, rel_used = self._format_relationships(rels, rel_budget)
        text_unit_text, text_unit_used = self._format_text_units(text_units, text_unit_budget)
        community_text, community_used = self._format_communities(community_reports, community_budget)

        # 印出 token 使用統計
        total_used = entity_used + rel_used + text_unit_used + community_used
        print(f"  📊 Token budget: {total_used}/{total} tokens used")
        print(f"     Entities:     {entity_used}/{entity_budget} ({len(entities)} available)")
        print(f"     Relationships:{rel_used}/{rel_budget} ({len(rels)} available)")
        print(f"     Text Units:   {text_unit_used}/{text_unit_budget} ({len(text_units)} available)")
        print(f"     Communities:  {community_used}/{community_budget} ({len(community_reports)} available)")

        return entity_text + rel_text + text_unit_text + community_text

    # ================================================================
    # Step 5: 更新 search() 流程
    # ================================================================

    def search(
        self,
        question: str,
        max_hops: int = 2,
        max_context_tokens: Optional[int] = None,
        community_prop: Optional[float] = None,
        text_unit_prop: Optional[float] = None,
    ) -> str:
        """
        執行 Local Search（升級版 — 5 步流程 + Token Budgeting）

        流程：
        [1/5] Entity Vector Search（失敗則 fallback 到文字匹配）
        [2/5] Community Vector Search（獨立取得最相關社群報告）
        [3/5] Graph Enrichment（N-hop 擴展 + TextUnits + 圖遍歷社群）
        [4/5] Token-Budgeted 格式化上下文
        [5/5] LLM 生成回答

        Args:
            question: 用戶問題
            max_hops: 圖遍歷的最大跳數
            max_context_tokens: 覆蓋總 token 預算
            community_prop: 覆蓋 community 佔比
            text_unit_prop: 覆蓋 text unit 佔比

        Returns:
            生成的回答
        """
        ctx_tokens = max_context_tokens or self.max_context_tokens
        print(f"\n🔍 執行 Neo4j Local Search...")
        print(f"   最大跳數: {max_hops}, Token 預算: {ctx_tokens}\n")

        # ---- 步驟 1: Entity Vector Search ----
        print("[1/5] Entity Vector Search...")
        matched_entities = []

        if self._schema["has_vector_index"]:
            try:
                matched_entities = self.find_entities_by_vector_search(
                    question, top_k=10, score_threshold=0.7
                )
            except Exception as e:
                print(f"  ⚠️  Vector Search 失敗: {e}")

        # Fallback: LLM 提取 + 文字匹配
        if not matched_entities:
            print("  ℹ️  Fallback 到文字匹配...")
            entity_mentions = self.extract_entities_from_question(question)
            matched_entities = self.find_matching_entities_in_neo4j(entity_mentions, top_k=3)

        if not matched_entities:
            return "未找到相關實體，無法回答問題。"

        entity_ids = [e["id"] for e in matched_entities]

        # ---- 步驟 2: Community Vector Search ----
        print("\n[2/5] Community Vector Search...")
        vector_communities = []

        if self._schema["has_community_vector"]:
            try:
                vector_communities = self.find_communities_by_vector_search(
                    question, top_k=5, score_threshold=0.7
                )
            except Exception as e:
                print(f"  ⚠️  Community Vector Search 失敗: {e}")
        else:
            print("  ℹ️  無 community_embeddings 索引，跳過")

        # ---- 步驟 3: Graph Enrichment ----
        print("\n[3/5] Graph Enrichment（N-hop + TextUnits + 圖遍歷社群）...")
        context = self.get_enriched_context(entity_ids, max_hops)

        # 合併種子實體（確保種子實體出現在 context 中）
        existing_ids = {e["id"] for e in context["entities"]}
        for e in matched_entities:
            if e["id"] not in existing_ids:
                context["entities"].append({
                    "id": e["id"],
                    "title": e.get("title", ""),
                    "type": e.get("type", ""),
                    "description": e.get("description", ""),
                    "degree": e.get("degree", 0),
                    "human_readable_id": e.get("human_readable_id", 0),
                })

        # 合併 community reports：vector search 結果 + 圖遍歷結果（去重）
        graph_community_ids = {cr.get("id") for cr in context["community_reports"] if isinstance(cr, dict)}
        merged_communities = list(context["community_reports"])  # 圖遍歷的先保留
        for vc in vector_communities:
            if vc.get("id") not in graph_community_ids:
                merged_communities.append(vc)
        # 按 rank 降序排列（有 score 的向量搜尋結果優先）
        merged_communities.sort(key=lambda c: (c.get("score", 0), c.get("rank", 0)), reverse=True)
        context["community_reports"] = merged_communities

        # ---- 步驟 4: Token-Budgeted 格式化上下文 ----
        print("\n[4/5] Token-Budgeted 格式化上下文數據...")
        context_data = self.format_context_data(
            context,
            max_tokens=max_context_tokens or self.max_context_tokens,
            community_prop=community_prop or self.community_prop,
            text_unit_prop=text_unit_prop or self.text_unit_prop,
        )

        print(f"   上下文長度: {len(context_data)} 字元")
        print(f"   實體數量: {len(context['entities'])}")
        print(f"   關係數量: {len(context['relationships'])}")
        print(f"   原文段數: {len(context['text_units'])}")
        print(f"   社群報告: {len(context['community_reports'])} (向量: {len(vector_communities)}, 圖: {len(context['community_reports']) - len(vector_communities)})")

        # ---- 步驟 5: 生成回答 ----
        print("\n[5/5] 生成回答...")
        prompt = ChatPromptTemplate.from_template(self.prompt_template)
        chain = prompt | self.llm | StrOutputParser()

        answer = chain.invoke({
            "context_data": context_data,
            "question": question
        })

        print(f"✅ Local Search 完成\n")
        return answer

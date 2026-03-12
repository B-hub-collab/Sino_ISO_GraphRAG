# Neo4j Global Search Implementation

本目錄包含針對 GraphRAG 數據實現的 Neo4j Global Search 功能。

## 🔍 原理說明

### 1. 什麼是 Global Search？
Global Search 是一種針對「全域性問題」（Global Questions）的檢索方法，例如「這份資料集的主題是什麼？」或「這份契約的主要風險有哪些？」。這類問題無法通過檢索特定的實體（Local Search）來回答，而是需要聚合更廣泛的上下文資訊。

GraphRAG 的解決方案是利用 **社群摘要（Community Summaries）**。數據預處理階段會將知識圖譜劃分為多個層級的社群，並為每個社群生成摘要。Global Search 的本質就是對這些社群摘要進行 **Map-Reduce** 處理。

### 2. Neo4j Global Search 實現原理
我們的實現 (`neo4j_global_search.py`) 直接利用儲存在 Neo4j 中的社群摘要數據，流程如下：

1.  **檢索 (Retrieve)**：從 Neo4j 資料庫中選取指定層級（Level）的社群節點。
    *   **關鍵參數 `max_communities`**：這決定了我們一次要分析多少個社群。
2.  **映射 (Map)**：將每個檢索到的社群摘要（Summary）與用戶問題一起送入 LLM。
    *   LLM 任務：從摘要中提取與問題相關的「要點 (Points)」並給予「評分 (Rating)」。
3.  **歸約 (Reduce)**：收集所有 Map 階段提取的高分要點，聚合成一個上下文，再次送入 LLM 生成最終的完整回答。

---

## ⚠️ 現行方案的局限與優化策略 (User QA)

**用戶提問**：「如果我們只選取 Rank/Size 最高的 5 個社群摘要，那是否不管問什麼問題，它都看這相同的 5 個社群？這是不是不合理？」

**分析**：
是的，您說得非常正確。目前的「Top-K 靜態篩選」是一個**為了速度而做的妥協 (Optimization for Speed)**。
*   對於「宏觀問題」（如：這份文件的摘要、主要風險），主要社群通常就包含了答案，所以效果不錯。
*   但對於「包含在小型社群的細節問題」，目前的 Top-K 機制確實會漏掉。

**改進方案：Dynamic Global Search (動態全域搜尋)**
為了讓搜尋更聰明，正確的做法應該是引入 **Vector Search** 來動態挑選社群。

| 策略 | 挑選機制 | 優點 | 缺點 |
| :--- | :--- | :--- | :--- |
| **Static Top-K (目前版本)** | 固定選 Rank 最高的 5 個 | 極快，適合測試和概要性問題 | 可能漏掉位於小社群的相關資訊 |
| **All Scan (GraphRAG 原始版)** | 隨機打亂並讀取全部社群 | 覆蓋率 100%，不會漏 | 極慢，成本高 |
| **Vector-based Dynamic (未來優化)** | 將社群摘要向量化，先找出與「問題向量」最相似的 5-10 個社群 | **既快又準**，能針對問題動態調整關注點 | 需要額外建立社群摘要的 Vector Index |

**結論**：目前的 `max_communities=5` 是一個「快速展示版」。在生產環境中，我們會建議實作上述的 **Vector-based Dynamic** 策略。

---

## 🆚 Neo4j vs GraphRAG CLI 比較 (技術細節)

| 特性 | GraphRAG CLI (原始版) | Neo4j Global Search (我們的版本) |
| :--- | :--- | :--- |
| **社群遍歷** | **Shuffle & Fill**<br>它會把社群隨機打亂，然後嘗試塞滿 Context Window。實際上它是在做「隨機抽樣 (Random Sampling)」。 | **Priority-based Top-K**<br>我們選擇相信 `PageRank` 或 `Community Size` 較大的社群包含更重要的資訊。 |
| **適用場景** | 不計時間成本，想要盡可能探索所有角落的資訊。 | 需要即時回應，且問題通常是針對文件核心內容的。 |

### Python API
```python
from langchain_neo4j import Neo4jGraph
from langchain_openai import AzureChatOpenAI
from global_search.neo4j_global_search import Neo4jGlobalSearch

# 初始化
graph = Neo4jGraph(...)
llm = AzureChatOpenAI(...)
# 使用 max_communities=5 進行快速檢索
search_engine = Neo4jGlobalSearch(graph=graph, llm=llm, level=0, max_communities=5)

# 執行查詢
result = search_engine.search("這份契約的主要風險有哪些？")
print(result)
```

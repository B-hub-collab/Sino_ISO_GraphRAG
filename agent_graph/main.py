"""
Agent 執行入口

提供命令行和 Python API 兩種使用方式
"""

import os
import sys
import json
from datetime import datetime
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv

from .graph import create_agent_graph, print_execution_summary
from .state import AgentState

load_dotenv()

# 創建查詢歷史目錄
HISTORY_DIR = Path("query_history")
HISTORY_DIR.mkdir(exist_ok=True)

# 創建 Agent Graph 實例
app = create_agent_graph()


def run_agent(question: str,verbose: bool = True,return_state: bool = False,force_engine: Optional[str] = None) -> Optional[dict]:
    """
    運行 Agent 回答問題

    Args:
        question: 用戶問題
        verbose: 是否打印詳細日誌
        return_state: 是否返回完整狀態 (用於調試)
        force_engine: 強制使用特定引擎 ('cypher', 'local_search', 'graphrag', 'hybrid')

    Returns:
        如果 return_state=True，返回完整的 AgentState
        否則返回簡化的結果字典
    """
    initial_state: AgentState = {
        "question": question,
        "execution_path": [],
        "error_log": [],
        "cypher_retry_count": 0,
    }

    # 如果指定了引擎，直接设置查询类型
    if force_engine:
        valid_engines = ["cypher", "local_search", "graphrag", "hybrid"]
        if force_engine not in valid_engines:
            print(f"⚠️  無效的引擎名稱: {force_engine}")
            print(f"   可用引擎: {', '.join(valid_engines)}\n")
            force_engine = None
        else:
            initial_state["query_type"] = force_engine
            print(f"🎯 強制使用引擎: {force_engine}\n")

    try:
        # 執行圖
        print(f"\n{'='*60}")
        print(f"🧠 Agentic Legal Graph RAG")
        print(f"{'='*60}\n")
        print(f"❓ 問題: {question}\n")

        final_state = app.invoke(initial_state)

        # 打印執行摘要
        if verbose:
            print_execution_summary(final_state)

        # 返回結果
        if return_state:
            return final_state
        else:
            return {
                "answer": final_state.get("final_answer", "無法生成回答"),
                "query_type": final_state.get("query_type"),
                "confidence": final_state.get("confidence", 0.0),
                "sources": final_state.get("sources", []),
                "execution_path": final_state.get
                ("execution_path", []),
            }

    except Exception as e:
        print(f"\n❌ Agent 執行失敗: {str(e)}\n")
        import traceback
        traceback.print_exc()

        return {
            "answer": f"執行錯誤: {str(e)}",
            "query_type": "error",
            "confidence": 0.0,
            "error": str(e),
        }


def save_query_result(question: str, result: dict, state: Optional[dict] = None):
    """
    保存查詢結果到歷史記錄

    Args:
        question: 用戶問題
        result: 查詢結果
        state: 完整狀態 (可選)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = HISTORY_DIR / f"query_{timestamp}.json"

    record = {
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "query_type": result.get("query_type"),
        "answer": result.get("answer"),
        "confidence": result.get("confidence"),
        "execution_path": result.get("execution_path", []),
    }

    # 如果有完整狀態，添加更多細節
    if state:
        record["cypher_query"] = state.get("cypher_query")
        record["cypher_results"] = state.get("cypher_results")
        record["local_search_result"] = state.get("local_search_result")
        record["graphrag_result"] = state.get("graphrag_result")
        record["error_log"] = state.get("error_log", [])

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return filename


def export_result_to_markdown(question: str, result: dict, state: Optional[dict] = None) -> str:
    """
    將查詢結果導出為 Markdown 格式

    Args:
        question: 用戶問題
        result: 查詢結果
        state: 完整狀態 (可選)

    Returns:
        Markdown 格式的結果
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md = f"""# 合同分析查詢結果

## 查詢信息
- **時間**: {timestamp}
- **問題**: {question}
- **查詢類型**: {result.get('query_type', 'N/A')}
- **置信度**: {result.get('confidence', 0) * 100:.1f}%

## 回答

{result.get('answer', '無回答')}

"""

    # 添加執行路徑
    if result.get('execution_path'):
        md += f"""## 執行路徑

{' → '.join(result['execution_path'])}

"""

    # 如果有詳細狀態，添加更多資訊
    if state:
        if state.get('cypher_query'):
            md += f"""## Cypher 查詢

```cypher
{state['cypher_query']}
```

"""

        if state.get('cypher_results'):
            md += f"""## Cypher 結果

```json
{json.dumps(state['cypher_results'], ensure_ascii=False, indent=2)}
```

"""

    # 添加頁腳
    md += f"""---
*生成時間: {timestamp}*
*查詢引擎: Agentic Legal Graph RAG*
"""

    return md


def save_result_as_markdown(question: str, result: dict, state: Optional[dict] = None) -> Path:
    """
    將結果保存為 Markdown 文件

    Returns:
        保存的文件路徑
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = HISTORY_DIR / f"result_{timestamp}.md"

    md_content = export_result_to_markdown(question, result, state)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(md_content)

    return filename


def interactive_mode():
    """
    互動模式：持續接受用戶輸入

    輸入 'exit' 或 'quit' 退出
    支持多行輸入：輸入 '"""' 進入多行模式，再次輸入 '"""' 結束
    """
    print("\n" + "=" * 80)
    print("🧠 Agentic Legal Graph RAG - 互動模式")
    print("=" * 80)
    print("\n提示:")
    print("  - 輸入問題後按 Enter 查詢")
    print("  - 輸入 '\"\"\"' 進入多行輸入模式，再次輸入 '\"\"\"' 結束")
    print("  - 輸入 'help' 查看範例問題")
    print("  - 輸入 'engines' 查看可用引擎")
    print("  - 使用 '@引擎名 問題' 指定引擎（例如：@cypher 列出所有組織）")
    print("  - 輸入 'exit' 或 'quit' 退出\n")
    print("=" * 80 + "\n")

    while True:
        try:
            # 獲取用戶輸入
            question = input("\n❓ 您的問題: ").strip()

            if not question:
                continue

            # 檢查是否進入多行模式
            if question == '"""':
                print("📝 多行輸入模式（輸入 '\"\"\"' 結束）:")
                lines = []
                while True:
                    line = input()
                    if line.strip() == '"""':
                        break
                    lines.append(line)
                question = "\n".join(lines).strip()
                print(f"\n✅ 收到多行問題（{len(lines)} 行）")

                if not question:
                    print("⚠️  問題內容為空")
                    continue

            if question.lower() in ["exit", "quit", "q"]:
                print("\n👋 再見！\n")
                break

            if question.lower() == "help":
                print_example_questions()
                continue

            if question.lower() == "engines":
                print_available_engines()
                continue

            # 檢查是否指定了引擎
            force_engine = None
            if question.startswith("@"):
                parts = question.split(" ", 1)
                if len(parts) == 2:
                    force_engine = parts[0][1:].lower()  # 移除 @ 符號
                    question = parts[1]
                    print(f"\n🎯 指定使用引擎: {force_engine}")
                else:
                    print("\n⚠️  格式錯誤，應該是: @引擎名 問題")
                    continue

            # 執行查詢
            run_agent(question, verbose=True, force_engine=force_engine)

        except KeyboardInterrupt:
            print("\n\n👋 再見！\n")
            break
        except Exception as e:
            print(f"\n❌ 錯誤: {str(e)}\n")
            import traceback
            traceback.print_exc()


def print_available_engines():
    """
    打印可用的查询引擎
    """
    print("\n" + "=" * 80)
    print("🔧 可用查詢引擎")
    print("=" * 80 + "\n")

    engines = {
        "cypher": {
            "名稱": "Cypher 查詢",
            "適用場景": "精確的結構化查詢、統計、過濾",
            "速度": "⚡ 快（< 5 秒）",
            "示例": "@cypher 列出所有類型為 ORGANIZATION 的實體"
        },
        "local_search": {
            "名稱": "Local Search",
            "適用場景": "實體局部關係探索、找出關聯實體",
            "速度": "⚡⚡ 中等（10-30 秒）",
            "示例": "@local_search 甲方與哪些實體關聯最緊密？"
        },
        "graphrag": {
            "名稱": "GraphRAG Global",
            "適用場景": "概念性問題、摘要分析、理解合同內容",
            "速度": "🐌 慢（30秒 - 3分鐘）",
            "示例": "@graphrag 這份契約的主要風險是什麼？"
        },
        "hybrid": {
            "名稱": "混合模式",
            "適用場景": "需要結合結構化數據和概念分析",
            "速度": "🐌 慢（取決於組合）",
            "示例": "@hybrid 列出所有違約金實體並分析風險"
        }
    }

    for engine_id, info in engines.items():
        print(f"📌 {info['名稱']} (@{engine_id})")
        print(f"   適用: {info['適用場景']}")
        print(f"   速度: {info['速度']}")
        print(f"   示例: {info['示例']}\n")

    print("=" * 80)
    print("\n💡 提示:")
    print("   - 不指定引擎時，系統會自動選擇最合適的")
    print("   - 使用 @引擎名 來強制指定引擎")
    print("   - 對於速度敏感的查詢，建議使用 cypher 或 local_search\n")
    print("=" * 80 + "\n")


def print_example_questions():
    """
    打印範例問題 - 根据实际合同分析场景分类
    """
    print("\n" + "=" * 80)
    print("📝 實際合同分析場景範例")
    print("=" * 80 + "\n")

    examples = {
        "🎯 Cypher 查詢 (精確結構化查詢)": [
            "列出所有類型為 'ORGANIZATION' 的實體，並計算數量",
            "有多少個實體的度數大於 10？",
            "找出所有涉及違約金的條款",
            "顯示度數最高的前 5 個實體",
            "列出所有與保險相關的實體",
        ],

        "🔍 Local Search (局部圖探索 - 實體關係網絡)": [
            "甲方與哪些實體關聯最緊密？找出重要的關聯實體",
            "找出連接甲方和臺中市政府的關鍵中間實體",
            "探索 PARTY B 的關係網絡，找出與其相關的重要實體",
            "分析違約金相關實體的局部關係圖",
            "找出連接保險和賠償責任的關鍵節點",
        ],

        "🌐 GraphRAG 查詢 (概念性摘要分析)": [
            "這份契約的主要風險是什麼？",
            "總結保險相關的所有條款內容",
            "違約的主要後果有哪些？請詳細說明",
            "契約中對於遲延履約的完整規定是什麼？",
            "分析契約中甲乙雙方的權利義務平衡",
            "契約中有哪些不可抗力條款？如何處理？",
        ],

        "🔄 混合模式查詢 (結構化 + 概念性)": [
            "列出所有涉及違約金的實體，並分析相關風險",
            "找出度數最高的 5 個實體，並解釋它們的重要性",
            "統計所有組織類型實體，並分析它們在契約中的角色",
        ],

        "💼 實際業務場景": [
            "如果乙方延遲履約，會有什麼後果？",
            "契約中對於變更設計的處理流程是什麼？",
            "發生不可抗力事件時，雙方的責任如何劃分？",
            "甲方有哪些單方面終止契約的權利？",
            "保險要求有哪些？保額是多少？",
            "工程款支付的條件和流程是什麼？",
        ],
    }

    for category, questions in examples.items():
        print(f"\n{category}:")
        for i, q in enumerate(questions, 1):
            print(f"  {i}. {q}")

    print("\n" + "=" * 80)
    print("\n💡 提示: 系統會自動根據問題類型選擇最合適的查詢引擎")
    print("   - Cypher: 精確的結構化查詢")
    print("   - Local Search: 實體局部關係探索")
    print("   - GraphRAG: 概念性摘要和分析")
    print("   - Hybrid: 結合多種方法\n")
    print("=" * 80 + "\n")


def main():
    """
    主函數：解析命令行參數

    支持 @engine 語法：python -m agent_graph.main "@local_search 你的問題"
    """

    # 檢查環境變數
    required_env = ["OPENAI_API_KEY", "NEO4J_PASSWORD"]
    missing_env = [var for var in required_env if not os.getenv(var)]

    if missing_env:
        print(f"\n❌ 錯誤: 缺少環境變數: {', '.join(missing_env)}")
        print(f"\n請在 .env 文件中設置這些變數，或使用以下命令:")
        for var in missing_env:
            print(f"  export {var}=your_value_here")
        print()
        sys.exit(1)

    # 解析命令行參數
    if len(sys.argv) > 1:
        # 單次查詢模式
        question = " ".join(sys.argv[1:])

        # 檢查是否指定了引擎
        force_engine = None
        if question.startswith("@"):
            parts = question.split(" ", 1)
            if len(parts) == 2:
                force_engine = parts[0][1:].lower()  # 移除 @ 符號
                question = parts[1]
                print(f"\n🎯 指定使用引擎: {force_engine}")
            else:
                print("\n⚠️  格式錯誤，應該是: @引擎名 問題")
                sys.exit(1)

        run_agent(question, verbose=True, force_engine=force_engine)
    else:
        # 互動模式
        interactive_mode()


if __name__ == "__main__":
    main()
